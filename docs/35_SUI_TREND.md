# 35 · SUI Isolated Trend Paper Lane

**Status:** isolated deterministic paper lane. No live order path.

**Code:** `src/tradingbot/ops/runner.py` (shared runner), `src/tradingbot/strategies/trend.py`  
**Config:** `config/sui.yaml`  
**Universe:** `config/sui_universe.csv`  
**Task:** `TradingBotSui`, daily at 07:10 local

SUI has two separate roles in the bot:

1. **This isolated lane:** a standalone $10k SUI-only trend account.
2. **The main universe:** since 28 Oct 2026, SUIUSDT is also a member of the
   daily 9-asset campaign and the AI agent/squad universe. That universe change
   is documented in `docs/36_SUI_UNIVERSE.md`; prior 8-asset evidence was
   archived and the main paper books were reset.

This lane still keeps its own data, state, risk state, and performance history.
It is not the main campaign, and it does not use the main campaign's paper
account.

---

## 1. Scope

| Item | Value |
|---|---|
| Asset | `SUIUSDT` |
| Venue/data | Binance public spot daily bars |
| History start | 2023-05-03 (SUIUSDT listing) |
| Strategy | Long-only 200-day trend with volatility targeting |
| Starting paper capital | $10,000 |
| Max asset weight | 25% |
| Max drawdown / auto-kill | 35% |
| Broker | paper |

The strategy is long-only. A flat signal exits to cash; there are no short
positions and no leverage.

## 2. Data and artifacts

```text
data/normalized/bars_sui.parquet
artifacts/sui/backtest_trend_*.csv
artifacts/sui/backtest_trend_*.png
artifacts/sui/backtest_trend_metrics.json
artifacts/sui/paper_state.json
artifacts/sui/performance.jsonl
artifacts/sui/heartbeat.json
artifacts/sui/orders.sqlite
artifacts/sui/risk_state.json
```

These are separate from `artifacts/performance_trend.jsonl`,
`artifacts/reports/evaluation_trend.json`, and every AI/options account.

## 3. Commands

```powershell
uv run python -m tradingbot --config config/sui.yaml download
uv run python -m tradingbot --config config/sui.yaml backtest --strategy trend
uv run python -m tradingbot --config config/sui.yaml `
  run --mode paper --once --strategy trend --no-evaluate

powershell -ExecutionPolicy Bypass -File scripts/run_sui.ps1
powershell -ExecutionPolicy Bypass -File scripts/register_sui.ps1
```

`--no-evaluate` is intentional. The shared evaluation writer keys reports by
strategy name, so a SUI `trend` evaluation would overwrite the 9-asset trend
report. The SUI dashboard computes its own view from the SUI state and
performance files instead.

## 4. First full-sample backtest

Run on 27 Oct 2026 over 1,273 daily bars:

```text
final equity     $11,780.96
total return     17.81%
CAGR             4.81%
volatility       9.96%
Sharpe           0.52
max drawdown     -13.68%
profit factor    1.13
hit rate         18.85%
```

This is a research result, not forward evidence of edge. The hit rate is low
because the trend rule trades infrequently and must win on large moves.

## 5. First paper cycle

The first paper cycle opened a long SUI position:

```text
equity           $9,997.66
cash             $8,438.71
SUI quantity     1,697.47
average entry    $0.9188592
gross exposure   ~15.6%
fills            1
```

No live order was sent. The position and all future SUI fills remain paper-only.

## 6. Dashboard

- **Overview** includes a SUI trend lane card and equity curve.
- **SUI trend** is a dedicated read-only page with paper equity, position,
  target weight, data age, backtest research metrics, and the scheduled task.
- The Vercel lite snapshot includes a SUI trend lane card.

## 7. Limits

- One asset only; this is not a cross-sectional SUI allocation strategy.
- SUI has a shorter history than BTC/ETH and higher idiosyncratic risk.
- The lane is not part of the 56-day options evidence. It is separate from the
  9-asset campaign even though both may hold SUI.
- Live spot remains **NO_GO**; this config cannot place live orders.
