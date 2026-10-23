# 14 — Live/Paper Evaluation, TCA, and Dashboard

**Goal:** make the bot evaluate its own paper/live behavior without letting it change its own strategy.

---

## 1. What is now automated

Every paper/live cycle now:

1. Runs the strategy on the latest **completed** bar.
2. Applies risk limits and drawdown checks.
3. Plans and executes orders.
4. Writes the heartbeat, order journal, and performance history.
5. Computes an evaluation report:
   - live/paper vs backtest
   - realized slippage (TCA)
   - rolling Sharpe/drawdown
   - signal drift
   - order health
   - data freshness
   - alerts

The report is written to:

```text
artifacts/reports/evaluation_{strategy}.md
artifacts/reports/evaluation_{strategy}.json
```

Performance history:

```text
artifacts/performance_{strategy}.jsonl
```

Order journal:

```text
artifacts/orders_{strategy}.sqlite
```

---

## 2. Commands

```powershell
# One evaluation report
uv run python -m tradingbot evaluate --strategy trend
uv run python -m tradingbot --config config/xsmom.yaml evaluate --strategy xsmom

# Or the standalone script
uv run python scripts/daily_report.py --config config/base.yaml --strategy trend

# Read the report
Get-Content artifacts/reports/evaluation_trend.md
```

The runner generates the report automatically after every successful cycle:

```powershell
uv run python -m tradingbot run --mode paper --once
```

---

## 3. Metrics and alerts

| Metric | Meaning | Alert threshold |
|---|---|---|
| `tracking_difference` | paper/live vs backtest | > 5% |
| `tracking_error` | volatility of return gap | informational |
| `weighted_slip_bps` | fill vs reference price | > 2× expected |
| `median_slip_bps` | typical fill slippage | informational |
| `signal_drift` | current weights vs target | > 25% |
| `rolling 60d Sharpe` | recent risk-adjusted return | < 0 |
| `current_drawdown` | peak-to-current | > 1.5× backtest max DD |
| `reject_rate` | rejected / total orders | > 5% |
| `data_age` | days since latest bar | > 2 |
| `heartbeat age` | last successful run | > 2 days |

Alerts appear in the report and dashboard. They do **not** auto-change the strategy.

---

## 4. Dashboard

Read-only Streamlit dashboard:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_dashboard.ps1
```

Then open:

```text
http://localhost:8501
```

It shows:

- equity, cash, data age, TCA, signal drift
- paper/live equity vs backtest
- live-vs-backtest stats
- rolling metrics
- order health
- positions
- alerts

The dashboard cannot place orders or change config. It now also has a `Both` view and an `AI agent` view for the separate paper pipeline; see `docs/16_AI_AGENT_PIPELINE.md`.

---

## 5. Daily paper campaign

Run both sleeves + evaluation:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_campaign.ps1
```

Reset the paper accounts first (only once):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_campaign.ps1 -Reset
```

A Windows scheduled task is registered:

```text
TradingBotPaperCampaign
Daily at 07:00 local time
```

Check:

```powershell
schtasks /Query /TN "TradingBotPaperCampaign"
```

The task runs `run_campaign.ps1`, so the PC must be on. `StartWhenAvailable` is enabled, so a missed run starts when the PC wakes.

Campaign log:

```text
logs/campaign.log
```

---

## 6. Current campaign state (23 Oct 2026)

| Sleeve | Equity | Cash | TCA | Signal drift | Alerts |
|---|---:|---:|---:|---:|---|
| Trend | $9,995.26 | $6,836.99 | 5.0 bps | 0.01% | none |
| XSMOM | $9,991.00 | $9,991.00 | 5.0 bps | 0.03% | none |

The paper campaign is now running daily. Treat the first 8 weeks as an operational/statistical test, not as proof of edge.

---

## 7. What this does not do

- It does not auto-tune parameters.
- It does not promote a strategy to live.
- It does not use future data or LLM discretion.
- It does not replace the 8-week paper track record.
- It does not fix the strategy's weak DSR/PBO. It only measures whether live behavior matches the backtest.

The next research step remains funding/carry, delisted assets, and a macro regime overlay.
