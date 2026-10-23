# 11 — Paper Trading Runbook

**Scope:** running the v1 paper trader on this PC.  
**No real orders are placed.** The CLI does not expose a `live` command.

---

## 1. Daily paper run

```powershell
cd C:\projects\tradingbot
powershell -ExecutionPolicy Bypass -File scripts/run_paper.ps1 -Strategy trend
```

Options:

```powershell
# Reset the paper account to the starting cash
powershell -ExecutionPolicy Bypass -File scripts/run_paper.ps1 -Strategy trend -Reset

# Run the cross-sectional momentum sleeve (separate config/state/journal)
powershell -ExecutionPolicy Bypass -File scripts/run_paper.ps1 -Config config/xsmom.yaml -Strategy xsmom

# Use the US equities config (requires Alpaca paper keys + downloaded data)
powershell -ExecutionPolicy Bypass -File scripts/run_paper.ps1 -Config config/alpaca.yaml -Strategy trend
```

The run:
1. Loads `data/normalized/bars.parquet`.
2. Computes target weights from the latest bar.
3. Loads `artifacts/paper_state.json` (unless `-Reset`).
4. Plans orders against the paper positions.
5. Fills at the last close with configured costs.
6. Writes orders to `artifacts/orders.sqlite`.
7. Saves updated state.

Logs: `logs/paper.log`.

---

## 2. Schedule it (Windows Task Scheduler)

Run once per weekday at 06:30 local time:

```powershell
schtasks /Create /TN "TradingBotPaper" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 06:30 /TR "powershell -ExecutionPolicy Bypass -File C:\projects\tradingbot\scripts\run_paper.ps1 -Strategy trend"
```

Check:

```powershell
schtasks /Query /TN "TradingBotPaper"
```

Delete:

```powershell
schtasks /Delete /TN "TradingBotPaper" /F
```

**Running two sleeves:** `config/base.yaml` is the trend sleeve; `config/xsmom.yaml` is the momentum sleeve. They use separate paper state, journal, heartbeat, risk-state, and kill files. Do not point both at the same state path. The bot does not net across sleeves; for live, use separate sub-accounts or maintain an explicit capital-allocation table.

**Notes:**
- The PC must be on and awake. Use a UPS and disable sleep during the scheduled window.
- Crypto trades 24/7; stocks only on exchange sessions. Adjust the schedule/timezone.
- The runner uses the last **completed** daily bar for signals and the last close for paper fills. This is a simulation, not an execution model.

---

## 2b. Campaign health

The scheduled paper tasks run at 07:00, 07:15, and 07:20 local time. A health
check runs at 07:30:

```powershell
uv run python -m tradingbot health
Get-Content artifacts\CAMPAIGN_HEALTH.md
```

It fails if any of trend, XSMOM, breakout, reversal, meta, or AI did not write a
fresh performance row for today's Singapore date, or if its heartbeat reports an
error. A failed health check should be fixed before counting that day toward the
56-day gate.

## 3. Kill switch

Activate:

```powershell
uv run python -m tradingbot kill
```

Resume:

```powershell
uv run python -m tradingbot resume
```

The next paper/live/preview cycle refuses to run (`RiskLimitBreached`) while the file exists.
A drawdown breach automatically creates the same file when `risk.auto_kill_on_drawdown` is true.

Flatten paper positions:

```powershell
uv run python -m tradingbot flatten
```

Flatten a live account (requires explicit confirmation and `LIVE_TRADING=YES`):

```powershell
uv run python -m tradingbot --config config/live.alpaca.yaml flatten --confirm-live
```

This is a **local** kill switch. For live trading, it must also cancel open orders and flatten positions at the broker — use `flatten` for that.

---

## 4. Inspect state and orders

```powershell
uv run python -m tradingbot status
Get-Content artifacts\heartbeat.json
Get-Content artifacts\paper_state.json
uv run python -c "from tradingbot.execution.orders import OrderJournal; j=OrderJournal('artifacts/orders.sqlite'); print(j.recent(20)); j.close()"
```

Or use any SQLite viewer:

```powershell
uv run python -c "import sqlite3; c=sqlite3.connect('artifacts/orders.sqlite'); print(c.execute('select * from orders order by ts desc limit 20').fetchall())"
```

---

## 5. Daily checks

| Check | Command |
|---|---|
| Config + keys + data audit | `uv run python -m tradingbot.cli check` |
| Data quality | `uv run python -m tradingbot.cli validate-data` |
| Backtest | `uv run python -m tradingbot.cli backtest --strategy trend` |
| Paper-broker replay | `uv run python -m tradingbot.cli paper-replay --strategy trend` |
| Walk-forward / DSR / PBO | `uv run python -m tradingbot.cli walkforward --strategy trend` |
| Unit/integration tests | `uv run pytest -q` |
| Lint / types | `uv run ruff check src scripts tests` and `uv run mypy src` |
| Full self-eval | `uv run python scripts/self_eval.py` |

---

## 6. Data refresh

Crypto:

```powershell
uv run python -m tradingbot.cli download
```

US equities (requires `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` in `.env`):

```powershell
uv run python -m tradingbot.cli --config config/alpaca.yaml download
```

Macro (requires `FRED_API_KEY`):

```powershell
uv run python -m tradingbot.cli download-macro
```

The Binance downloader combines monthly archives with recent bars from the public
`data-api.binance.vision` endpoint (no key), so the current month is included.
It reuses cached ZIPs in `data/raw`; delete a ZIP to force a refresh.

---

## 7. What to do when something breaks

| Symptom | Action |
|---|---|
| `missing ...bars.parquet` | Run `download` for the matching config |
| `RiskLimitBreached` | Check `artifacts/KILL`; check gross/net/asset weights |
| `insufficient cash` in paper | Reset paper state or reduce target weights |
| Data gaps / stale bars | Run `validate-data`; re-download the affected month |
| Duplicate orders | Stop, inspect journal, reconcile; do not rerun blindly |
| Broker API error (future live) | Do not resubmit; reconcile positions first |
| Strategy decay | Freeze, re-run walk-forward, reduce size or retire |

---

## 7b. Gated live mode

The command exists but is locked behind four checks:

1. `--confirm-live`
2. `LIVE_TRADING=YES`
3. `broker.paper=false`
4. for ccxt, `broker.sandbox=false`

```powershell
$env:LIVE_TRADING = "YES"
uv run python -m tradingbot --config config/live.alpaca.yaml live --confirm-live
```

Or one cycle through the generic runner:

```powershell
uv run python -m tradingbot --config config/live.alpaca.yaml run --mode live --once --confirm-live
```

The command prints a heartbeat and writes the order journal. It is still your
responsibility to verify the broker account, symbol mapping, and risk limits.
Do not run it until the validation gates are met.

---

## 8. Before enabling real money

The repo deliberately has no `live` CLI. To add one safely:

1. Add a separate `live` config per broker/asset class.
2. Require an explicit `--confirm-live` flag **and** an environment variable.
3. Keep trade-only API keys with withdrawals disabled.
4. Add an order state machine with retries, partial fills, and startup reconciliation.
5. Test the kill switch by cancelling/flattening in a paper account.
6. Run 8+ weeks of paper trading and compare slippage vs the backtest.
7. Start at 25–50% of intended risk, and only scale after 3 months within limits.

**Do not enable live trading because a backtest looks good.** The current self-eval does not clear the validation gates.
