# 19 — Multi-Sleeve Build: Breakout, Reversal, Meta, Execution

**Built:** 23 Oct 2026  
**Status:** paper/research only. None of these sleeves is approved for live capital.

---

## 1. What was built

| Item | File | Purpose |
|---|---|---|
| Breakout sleeve | `strategies/breakout.py` | Donchian breakout + ATR sizing + volume filter |
| Reversal sleeve | `strategies/reversal.py` | Short-horizon mean reversion + trend regime filter |
| Meta allocator | `portfolio/allocator.py`, `strategies/meta.py` | Allocate across trend, breakout, reversal, XSMOM |
| Execution hardening | `execution/manager.py` | Partial completion, order chunking, reconciliation |

New configs:

```text
config/breakout.yaml
config/reversal.yaml
config/meta.yaml
```

New daily paper task:

```text
TradingBotSleeves   07:20 daily
```

It runs breakout, reversal, and meta paper cycles plus evaluation. The original
trend/XSMOM campaign remains at 07:00, and the AI agent remains at 07:15.

---

## 2. Breakout sleeve

**Logic**

- Entry when close breaks the prior N-day high.
- Exit when close breaks the prior exit-channel low.
- Optional ATR-based stop distance.
- Position size = risk budget / stop distance, capped.
- Optional volume confirmation.
- Long-only by default.
- Weekly rebalance; volatility-scaled and gross-capped.

**Full-sample backtest (2020–2026, 15 bps cost/slippage):**

| Metric | Value |
|---|---:|
| Final equity | $30,989.55 |
| CAGR | 18.06% |
| Vol | 16.61% |
| Sharpe | 1.082 |
| Max drawdown | −31.52% |
| Turnover | 4.23×/yr |
| Avg gross | 17.9% |

**Walk-forward OOS (3 folds):**

| Metric | Value |
|---|---:|
| OOS CAGR | 9.82% |
| OOS Sharpe | 0.763 |
| OOS max DD | −15.83% |
| DSR | 0.354 |
| PBO | 0.190 |

**Verdict:** research/paper only. PBO is acceptable; DSR is far below 0.95. It is correlated with trend and should not be treated as independent diversification.

---

## 3. Reversal sleeve

**Logic**

- Long when z-score of close vs its 20-day mean is deeply negative, or RSI(2) is oversold.
- Optional regime filter: only buy above the 200-day mean.
- Exit when z-score/RSI normalizes or regime breaks.
- Daily rebalance; small position caps; high turnover by design.

**Full-sample backtest:**

| Metric | Value |
|---|---:|
| Final equity | $10,429.03 |
| CAGR | 0.62% |
| Vol | 8.20% |
| Sharpe | 0.115 |
| Max drawdown | −20.29% |
| Turnover | 20.19×/yr |
| Avg gross | 4.8% |

**Walk-forward OOS:**

| Metric | Value |
|---|---:|
| OOS CAGR | −3.16% |
| OOS Sharpe | −0.367 |
| OOS max DD | −16.10% |
| DSR | 0.008 |
| PBO | 0.792 |

**Verdict:** reject for capital. It is kept as a research sleeve only. The high turnover and weak OOS make it a clear example of why a plausible-sounding agent is not automatically useful.

---

## 4. Meta allocator

**Logic**

- Inputs: trend, breakout, reversal, XSMOM weights.
- Forward-fills sleeve weights onto one daily grid.
- Measures trailing sleeve volatility and correlation using only returns through the decision date.
- Adjusts fixed sleeve budgets by inverse volatility and a positive-correlation penalty.
- Caps per-sleeve budget, per-asset weight, gross exposure, and target volatility.
- One consolidated portfolio, one risk engine, one execution path.

**Full-sample backtest:**

| Metric | Value |
|---|---:|
| Final equity | $22,606.36 |
| CAGR | 12.72% |
| Vol | 11.88% |
| Sharpe | 1.067 |
| Max drawdown | −22.29% |
| Turnover | 3.89×/yr |
| Avg gross | 13.9% |

**Walk-forward OOS:**

| Metric | Value |
|---|---:|
| OOS CAGR | 14.38% |
| OOS Sharpe | 1.120 |
| OOS max DD | −13.05% |
| DSR | 0.867 |
| PBO | 0.038 |

**Verdict:** the most promising of the new sleeves, but DSR 0.867 is still below the 0.95 gate. It is not live-ready. The allocator is doing real work: lower drawdown and lower gross than the standalone trend sleeve, with a better OOS Sharpe than breakout/reversal.

**Caveat:** only three walk-forward folds and no funding/PIT universe yet. Treat this as encouraging, not proven.

---

## 5. Paper replay comparison

| Sleeve | Paper replay | Backtest | Replay fills |
|---|---:|---:|---:|
| Breakout | $32,153 | $30,990 | 1,063 |
| Reversal | $10,404 | $10,429 | 3,359 |
| Meta | $23,167 | $22,606 | 1,579 |

Replay is close to the vectorized backtest. That is an execution-plumbing check, not additional evidence.

---

## 6. Execution hardening

### Partial fills

- An open partial is left alone.
- A terminal partial submits the remaining quantity as a child intent (`...-r1`, `...-r2`), up to a retry limit.
- Child intents are persisted, journalled, and idempotent.
- Startup reconciliation completes terminal partials and still blocks unresolved/untracked orders.

### Order chunking

`broker.max_child_notional` and `broker.max_children` split a large order into deterministic child orders (`...-s1`, `...-s2`).

This is **order chunking**, not time-based TWAP. The daily runner does not schedule intraday slices. Real TWAP/VWAP needs an intraday event loop and venue-specific child-order handling.

### What remains manual

- Ambiguous `UNKNOWN` orders.
- Flatten after a reconciliation break.
- Retrying a partial beyond the child limit.
- Live promotion.

---

## 7. Commands

```powershell
# Backtests
uv run python -m tradingbot --config config/breakout.yaml backtest
uv run python -m tradingbot --config config/reversal.yaml backtest
uv run python -m tradingbot --config config/meta.yaml backtest

# Walk-forward / DSR / PBO
uv run python -m tradingbot --config config/breakout.yaml walkforward
uv run python -m tradingbot --config config/reversal.yaml walkforward
uv run python -m tradingbot --config config/meta.yaml walkforward

# Paper replay
uv run python -m tradingbot --config config/breakout.yaml paper-replay
uv run python -m tradingbot --config config/reversal.yaml paper-replay
uv run python -m tradingbot --config config/meta.yaml paper-replay

# Daily paper sleeves
powershell -ExecutionPolicy Bypass -File scripts/run_sleeves.ps1
powershell -ExecutionPolicy Bypass -File scripts/register_sleeves_campaign.ps1
```

---

## 8. Reality check

- **Breakout and trend are correlated.** Running both is not free diversification.
- **Reversal is a research sleeve**, not a capital candidate.
- **Meta is one portfolio**, not four independent bots. That is deliberate.
- **No funding/basis, no delisted-asset PIT universe, no live execution.**
- The live gate remains **NO_GO**: DSR/PBO, paper days, and AI live execution all fail.

The next evidence work is funding/basis and PIT data, then rerun the meta walk-forward. Do not increase capital because a backtest looks better.
