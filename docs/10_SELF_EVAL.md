# 10 — Self-Evaluation Summary (v1 Build)

**Date:** 22 October 2026  
**Scope:** working v1 research + backtest + paper-execution system, plus a separate AI-agent paper lane  
**Status:** engineering checks pass; **not validated for live capital**

Full generated report: `artifacts/SELF_EVAL.md` (regenerate with `uv run python scripts/self_eval.py`).

---

## 1. What was built

| Component | Status |
|---|---|
| Binance Vision downloader + checksum + UTC normalization | Working |
| Combined Parquet bar store (8 crypto assets, 2020–2026) | Working |
| Data-quality audit | Working |
| Trend strategy (time-series momentum, vol-aware) | Working |
| Cross-sectional momentum strategy (long/short, long-only) | Working |
| Breakout strategy (Donchian/ATR/volume) | Working; DSR 0.354 |
| Reversal strategy (z-score/RSI regime-filtered) | Research-only; OOS Sharpe −0.367 |
| Meta allocator across four sleeves | Working; OOS Sharpe 1.120, DSR 0.867 |
| Partial-fill completion + order chunking | Working |
| Cost-aware vectorized backtester (next-open fills) | Working |
| Historical paper-broker replay | Working (1,341 trend fills, 1,689 XSMOM fills) |
| Risk limits + kill-switch check | Working |
| Walk-forward validation | Working |
| Deflated Sharpe Ratio (DSR) | Working |
| Probability of Backtest Overfitting (PBO/CSCV) | Working |
| Paper broker + persistent state + order planning + SQLite journal | Working |
| Alpaca data/broker adapters | Implemented, not live-tested (no keys) |
| ccxt broker adapter | Implemented, not live-tested (no keys) |
| Gated live runner, scheduler, heartbeat, kill/flatten | Working in paper; live path implemented but untested |
| Persistent order state machine + startup reconciliation | Working |
| Evaluation/TCA/signal drift/daily reports | Working |
| Separate AI-agent paper pipeline + audit | Working |
| Jev typed-decision adapter (optional, no key = fail closed) | Working; live-tested 23 Oct 2026 with 10 dry decisions |
| AI paper scorecard + confidence calibration | Working |
| Hard live-capital gate (`live-gate`, currently NO_GO) | Working |
| Read-only Streamlit dashboard (deterministic + AI + 3D office views) | Working |
| Two-floor 51 x 36 m 3D office: partitioned agent floor, quant workflow, competition, weather | Working |
| Scheduled daily paper campaign | Registered at 07:00/07:15/07:20 local |
| Campaign health check (`TradingBotHealth`) | Registered at 07:30 local; fresh-row verification |
| Listing-aware PIT span filter | Working; delisted-inclusive data still missing |
| Binance funding-rate data layer | Working; carry sleeve not built |
| FRED macro downloader | Implemented (requires `FRED_API_KEY`) |
| CLI: download, backtest, walkforward, paper, ai-run, ai-status, check, validate-data | Working |
| Tests | **102 passing** |
| Lint / type check | `ruff` pass, `mypy src` pass |

A `live` command now exists but is locked behind `--confirm-live`, `LIVE_TRADING=YES`, a non-paper broker, and `sandbox=false` for ccxt. It has not been exercised against a real broker because no keys are configured.

---

## 2. Reproducible results

Commands:

```powershell
uv run python -m tradingbot.cli download
uv run python -m tradingbot.cli validate-data
uv run python -m tradingbot.cli backtest --strategy trend
uv run python -m tradingbot.cli backtest --strategy xsmom
uv run python -m tradingbot.cli walkforward --strategy trend
uv run python -m tradingbot.cli walkforward --strategy xsmom
uv run python -m tradingbot.cli paper --strategy trend
uv run python scripts/self_eval.py
```

### Data audit

- 19,673 rows, 8 assets, 2020-01-01 → 2026-10-22
- 0 duplicate rows, 0 OHLC violations, 0 null prices

### Full-sample backtests

| Metric | Trend | XSMOM |
|---|---:|---:|
| Final equity | $35,434.64 | $8,115.31 |
| Total return | 254.4% | −18.9% |
| CAGR | 20.4% | −3.0% |
| Volatility | 16.0% | 18.4% |
| Sharpe | 1.24 | −0.08 |
| Sortino | 1.52 | −0.11 |
| Max drawdown | −29.6% | −50.4% |
| Annual turnover | 3.85× | 16.43× |
| Avg gross exposure | 18% | 53% |

### Paper-broker replay vs vectorized backtest

The historical paper replay walks every rebalance through the same `PaperBroker`, order planner, and accounting code used by the live/paper runner.

| Metric | Trend replay | Trend backtest | XSMOM replay | XSMOM backtest |
|---|---:|---:|---:|---:|
| Final equity | $35,922.63 | $35,434.64 | $7,760.34 | $8,115.31 |
| CAGR | 20.65% | 20.40% | −3.65% | −3.02% |
| Volatility | 15.62% | 15.98% | 19.46% | 18.44% |
| Sharpe | 1.28 | 1.24 | −0.10 | −0.08 |
| Max drawdown | −29.37% | −29.55% | −49.91% | −50.36% |
| Annual turnover | 4.09× | 3.85× | 18.16× | 16.43× |
| Fills | 1,341 | — | 1,689 | — |

The trend execution path reconciles closely: final equity differs by ~1.5%, CAGR by 0.28 pp, and max drawdown by 0.18 pp. XSMOM diverges more because its turnover is ~18×/year, so small per-trade cost differences compound. This is exactly the cost sensitivity the backtest warned about.

### Walk-forward (3 folds, 1-year OOS each)

| Strategy | Trials | DSR | PBO | OOS Sharpe | OOS CAGR | OOS Max DD | OOS turnover |
|---|---:|---:|---:|---:|---:|---:|---:|
| Trend | 72 | 0.264 | 0.312 | 1.05 | 12.5% | −11.7% | 6.5× |
| XSMOM | 36 | 0.266 | 0.394 | 1.27 | 27.7% | −20.6% | 5.6× |

**Important:** DSR is the probability the true Sharpe exceeds the selection-adjusted benchmark. Values around 0.26 are **weak**. PBO > 0.3 is a **red flag**. These results are not sufficient to deploy capital.

### Sensitivity: 180-day OOS folds

Re-running with 180-day test/step windows gives 7 folds and more trials:

| Strategy | Trials | DSR | PBO | OOS Sharpe | OOS CAGR | OOS Max DD |
|---|---:|---:|---:|---:|---:|---:|
| Trend | 168 | 0.032 | 0.270 | 0.86 | 8.5% | −12.7% |
| XSMOM | 84 | 0.057 | 0.363 | 1.20 | 23.7% | −24.3% |

The DSR collapses when the trial count rises. That is exactly what a multiple-testing-aware metric should do: the apparent OOS Sharpe is not strong enough to survive a realistic search budget.

---

## 3. Interpretation

### Trend
- Plausible risk-adjusted performance, lower drawdown than buy-and-hold, low exposure.
- OOS performance decays across folds (2.27 → 0.73 → 0.19 Sharpe).
- DSR 0.26 after 72 trials: cannot rule out selection bias.
- PBO 0.31: meaningful overfitting risk.

### XSMOM
- Full-sample default loses money; walk-forward selects long-only lookback-120 and looks good OOS.
- The last fold (2025–2026) is negative (−4.6%), suggesting regime dependence.
- PBO 0.39: high overfitting risk.
- High turnover (16.4× full-sample) makes it cost-sensitive.

### Verdict
**Do not trade real money from this build.** It is a solid research/engineering foundation, not a validated strategy. The next step is more data (delisted assets, funding), more OOS folds, and paper trading.

---

## 4. Bugs found and fixed during self-evaluation

1. Walk-forward passed a `StrategyResult` object instead of `.weights` to the backtester.
2. OOS turnover/exposure were not carried into the walk-forward report; fixed.
3. `PaperBroker` did not record a short position when shorting was enabled; fixed.
4. Binance header variants (`count`, `taker_buy_volume`) were not normalized; fixed.
5. Test fixtures for OHLC violations and timestamp time zones were corrected.
6. Type annotations for Alpaca/ccxt/Polars were tightened; `mypy src` passes.
7. `latest_weights` dropped the timestamp, breaking `plan_orders`; fixed.
8. `plan_orders` ignored positions absent from the target, so orphan positions were never closed; fixed.
9. The runner used the still-forming current daily bar; it now uses the last completed bar.
10. The first Binance parser read only 12 rows per file because `pl.all().head(12)` selected rows, not columns; fixed.
11. Added gated live execution, heartbeat, risk-state drawdown control, kill/flatten, and a scheduled runner.

The parser bug is a good example of why self-evaluation matters: the backtest would have looked plausible on a truncated dataset.

---

## 5. Known limitations

- **Crypto-only demo.** Alpaca/ccxt adapters are implemented but untested live.
- **Survivorship bias.** Listing dates are now enforced with `config/pit_universe_crypto.csv`, but current listed coins only; no complete delisted-asset universe.
- **No funding/borrow/carry sleeve.** Raw Binance funding data is downloaded, but the two-leg delta-neutral carry strategy is not modeled yet.
- **No macro/sentiment features** in the live strategies.
- **Paper fills at the last close**, not next open/order book.
- **Short OOS sample.** Three 1-year folds cannot prove an edge.
- **Taxes not modeled.**
- **Scheduler/ops are new.** The runner, heartbeat, kill, flatten, and risk-state controls are tested in paper, but there has been no long-running production drill or Telegram alert test with real credentials.
- **No full live order state machine** (advanced retries, partial-fill accounting, startup reconciliation across restarts).

---

## 6. Next steps (in order)

1. Add **funding/basis** data and a delta-neutral carry research module.
2. Add **PIT crypto universe + delisted symbols**; reduce survivorship bias.
3. Add **Alpaca stock sleeve** with PIT universe and delisted stocks.
4. Add a **paper-trading scheduler** and Telegram heartbeat/alerts.
5. Add a **live order state machine** with retries, partial fills, reconciliation.
6. Add **macro regime overlay** (rates, credit, VIX, DXY) as a risk throttle.
7. Re-run self-eval after each change; archive reports.

---

## 7. Reproduce / audit

```powershell
uv sync --extra dev
uv run python -m tradingbot.cli download
uv run python -m tradingbot.cli validate-data
uv run python scripts/self_eval.py
uv run pytest -q
uv run ruff check src scripts tests
uv run mypy src
```

Artifacts:
- `artifacts/SELF_EVAL.md`
- `artifacts/self_eval.json`
- `artifacts/backtest_trend_daily.csv`
- `artifacts/backtest_trend.png`
- `artifacts/backtest_xsmom_daily.csv`
- `artifacts/backtest_xsmom.png`
- `artifacts/walkforward_trend.json`
- `artifacts/walkforward_xsmom.json`
- `artifacts/orders.sqlite`
