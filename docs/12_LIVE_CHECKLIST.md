# 12 — Live Readiness Checklist

**Do not skip this.** The code is gated, but the gates are only as good as the operator.

---

## 1. Account setup

- [ ] Dedicated brokerage/exchange account (or sub-account) for the bot.
- [ ] Funded with money you can afford to lose.
- [ ] API key has **trade** permission only — **withdrawals disabled**.
- [ ] IP allowlist enabled if the venue supports it.
- [ ] 2FA enabled on the account.
- [ ] Separate keys per sleeve/strategy where possible.
- [ ] Confirm the venue/asset is legal in your jurisdiction.
- [ ] Confirm tax/recordkeeping requirements.

---

## 2. Configuration

- [ ] `config/live.alpaca.yaml` or `config/live.crypto.yaml` reviewed.
- [ ] `broker.paper: false`.
- [ ] `broker.sandbox: false` for ccxt.
- [ ] Symbols match the venue (ccxt uses `BTC/USDT`, Alpaca uses `SPY`).
- [ ] `data.source` matches the broker (`alpaca` or `binance`).
- [ ] Separate `state_path`, `journal_path`, `heartbeat_path`, `risk.state_path`, and kill file per sleeve.
- [ ] `risk.max_drawdown`, `max_gross`, `max_asset_weight` are set conservatively.
- [ ] `broker.allow_short` is false unless you explicitly intend to short.
- [ ] `.env` contains keys; `.env` is not in git.

---

## 3. Paper evidence

- [ ] 8+ weeks of paper trading.
- [ ] Realized slippage ≤ 1.5× model.
- [ ] No duplicate/missed orders.
- [ ] Reconciliation clean every day.
- [ ] Kill switch tested.
- [ ] Flatten tested in paper.
- [ ] Heartbeat/status monitored.
- [ ] At least one drawdown episode handled.

---

## 4. Pre-live dry run

```powershell
uv run python -m tradingbot --config config/live.alpaca.yaml check
uv run python -m tradingbot --config config/live.alpaca.yaml run --mode preview --once
uv run python -m tradingbot --config config/live.alpaca.yaml status

# Hard evidence/environment gate; writes artifacts/LIVE_GATE.md
uv run python -m tradingbot --config config/live.alpaca.yaml live-gate
uv run python -m tradingbot --config config/live.alpaca.yaml live-gate --include-ai
```

The gate returns `NO_GO` until DSR/PBO, paper days, TCA, data freshness, keys,
and environment flags all pass. It does not place orders.

- [ ] Preview shows the expected target weights and orders.
- [ ] Account equity/positions match the broker UI.
- [ ] Order notionals are small.
- [ ] Kill file is present? Test `kill` then `resume`.
- [ ] `flatten` is tested on paper first.

---

## 5. First live cycle

```powershell
$env:LIVE_TRADING = "YES"
uv run python -m tradingbot --config config/live.alpaca.yaml live --confirm-live
```

- [ ] Start with 25–50% of intended risk.
- [ ] Check the broker UI immediately after the cycle.
- [ ] Compare fills/journal/reconciliation.
- [ ] Confirm heartbeat status `ok`.
- [ ] Do not increase size for at least 3 months.

---

## 6. Ongoing

- [ ] Daily: `status`, heartbeat, positions, kill switch.
- [ ] Weekly: slippage/TCA, PnL vs backtest, error log.
- [ ] Monthly: drawdown, exposure, correlation, strategy decay.
- [ ] Quarterly: re-run walk-forward/DSR/PBO; retire or resize.
- [ ] Back up `artifacts/` and `data/` nightly.
- [ ] Rotate API keys periodically.

---

## 7. Emergency

```powershell
uv run python -m tradingbot kill
uv run python -m tradingbot --config config/live.alpaca.yaml flatten --confirm-live
```

If the broker UI and bot disagree, **stop trading and reconcile manually**. Do not
place "fix" orders until you understand the position.

---

## 8. Hard stops

Do not go live if any of these are true:

- Backtest DSR < 0.95 or PBO > 0.2.
- No 8-week paper record.
- No delisted-asset/funding modeling for the strategy that needs it.
- Realized slippage > 2× model.
- You cannot explain the edge and the kill criteria in one page.
- You are using money you need.
- You have not tested `flatten` and `kill`.
