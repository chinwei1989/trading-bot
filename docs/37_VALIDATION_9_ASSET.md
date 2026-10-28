# 37 - 9-Asset Walk-Forward Validation

**Date:** 28 October 2026  
**Status:** **FAIL** - no strategy clears the DSR/PBO gate. Live capital remains **NO_GO**.

This is the first validation run on the 9-asset universe that includes SUIUSDT.
The prior 8-asset DSR/PBO figures are not comparable and must not be used for a
live decision.

---

## 1. Scope and data

| Item | Value |
|---|---|
| Universe | 9 crypto assets: BTC, ETH, BNB, SOL, XRP, ADA, DOGE, LINK, SUI |
| Data | `data/normalized/bars.parquet` |
| Rows | 20,987 daily bars |
| Period | 2020-01-01 through 2026-10-27 |
| Data SHA-256 | `01bfda9ab096bb2b2afceff51ce5af3b1d43487143c86a140ac68c49ec9599e0` |
| SUI history | Starts 2023-05-03; no synthetic backfill |
| Costs | 10 bps commission + 5 bps slippage |
| Execution | Next-bar, no same-bar fills |

The 9-asset change was made on 28 October 2026. It resets the forward paper
evidence. This report answers the separate question: **does the strategy family
still survive multiple-testing-aware validation after the universe change?**

## 2. Method

- Train window: 900 days
- Test window: 365 days
- Step: 365 days
- Warm-up: 260 days
- Folds: 3
- DSR gate: **>= 0.95**
- PBO gate: **<= 0.20**

Each fold re-selects parameters on the training window only. OOS returns are
concatenated across the test windows. The trial count includes every parameter
tested in every fold, as recorded by the walk-forward runner.

The 365-day folds end on 2026-03-04. Bars after that date are not in the final
test window; the 180-day sensitivity run extends the final test window through
2026-08-16 for the faster sleeves.

## 3. Results

| Strategy | Folds | Trials | DSR | PBO | OOS Sharpe | OOS CAGR | OOS Max DD | Turnover | Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Trend | 3 | 72 | 0.016 | 0.267 | 0.45 | 6.2% | -20.6% | 11.1x | FAIL |
| XSMOM | 3 | 36 | 0.299 | 0.707 | 1.15 | 26.1% | -25.6% | 5.9x | FAIL |
| Breakout | 3 | 72 | 0.310 | 0.104 | 1.08 | 13.6% | -20.4% | 5.3x | FAIL |
| Reversal | 3 | 72 | 0.078 | 0.783 | -0.22 | -2.5% | -18.8% | 36.2x | FAIL |
| Meta | 3 | 9 | 0.671 | 0.597 | 0.93 | 12.4% | -13.0% | 10.2x | FAIL |

### 180-day sensitivity

The faster sleeves were rerun with 180-day test/step windows. This produces
seven folds and extends the final test window through **2026-08-16**:

| Strategy | Folds | Trials | DSR | PBO | OOS Sharpe | OOS CAGR | OOS Max DD | Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Trend | 7 | 168 | 0.014 | 0.248 | 0.67 | 9.6% | -18.2% | FAIL |
| XSMOM | 7 | 84 | 0.044 | 0.719 | 0.82 | 16.2% | -35.6% | FAIL |
| Breakout | 7 | 168 | 0.063 | 0.076 | 0.93 | 11.5% | -19.8% | FAIL |
| Meta | 7 | 21 | 0.342 | 0.485 | 0.84 | 10.3% | -13.6% | FAIL |

The shorter-fold test does not rescue any sleeve. Breakout still has the best
PBO (0.076), but its DSR falls from 0.310 to 0.063 as the number of selection
events rises. Reversal was not rerun at 180 days because its daily-rebalance
grid is materially slower; its 365-day result is already a clear failure.

### Primary findings

- **Trend is the worst result relative to the old 8-asset run.** OOS Sharpe is
  only 0.45 and DSR is 0.016. Adding SUI and re-selecting parameters materially
  changed the result.
- **XSMOM has the highest OOS Sharpe but is not trustworthy.** PBO is 0.707,
  meaning the in-sample winner frequently ranks below the OOS median. The 1.15
  Sharpe is not evidence of a durable edge.
- **Breakout is the closest to investable evidence but still fails.** PBO is
  acceptable at 0.104, but DSR is 0.310, far below 0.95.
- **Reversal remains research-only.** Negative OOS return, PBO 0.783, and 36x
  annual turnover make it unusable after costs.
- **Meta is not a rescue.** DSR 0.671 and PBO 0.597 fail; the sleeve weights are
  also selected over only three allocations, so the trial count is small.

## 4. What changed versus the 8-asset run

The old artifacts were generated before SUI was added. They are archived under
`artifacts/validation_20261028/before_walkforward_*.json` on this machine.

| Strategy | Old 8-asset DSR | Old PBO | Old OOS Sharpe | New 9-asset DSR | New PBO | New OOS Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| Trend | 0.264 | 0.312 | 1.05 | 0.016 | 0.267 | 0.45 |
| XSMOM | 0.266 | 0.394 | 1.27 | 0.299 | 0.707 | 1.15 |
| Breakout | 0.354 | 0.190 | 0.76 | 0.310 | 0.104 | 1.08 |
| Reversal | 0.008 | 0.792 | -0.37 | 0.078 | 0.783 | -0.22 |
| Meta | 0.867 | 0.038 | 1.12 | 0.671 | 0.597 | 0.93 |

These differences are **not a clean SUI-only estimate**. The universe,
parameter re-selection, and the last few months of data all changed. A dedicated
SUI on/off ablation is a separate experiment.

## 5. Live-config gap

The validation grid is wider than the live configuration. This matters:

- The live Trend config uses a 200-day lookback and is long-only. The validation
  grid selects a 50-day lookback in every fold, and one fold selects
  `long_short: true`, which the live config does not allow.
- The live Breakout config uses a 55-day lookback. The validation grid selected
  20 or 100 days in all three folds.
- The live gate reads the validation artifact, not a fixed-config OOS replay.
  A DSR from a family search is not the same as evidence for the exact config
  that would trade.

This is a design gap to close before any live-capital discussion. The next
validation step should pre-register the exact live parameter set and run a
fixed-config OOS replay, then report both the family search and the fixed-config
result. Do not change live parameters just because a grid won in-sample.

## 6. Decision

- Spot live gate: **NO_GO**
- Options live gate: **NO_GO**
- Live trading: disabled
- Paper campaigns: continue unchanged
- Options evidence window: continue untouched
- No parameter promotion from this run

The 9-asset forward paper window restarts from the universe change. It does not
inherit 8-asset paper days.

## 7. Reproduction

```powershell
uv run python -m tradingbot walkforward --strategy trend
uv run python -m tradingbot walkforward --strategy xsmom
uv run python -m tradingbot walkforward --strategy breakout
uv run python -m tradingbot walkforward --strategy reversal
uv run python -m tradingbot walkforward --strategy meta
uv run python scripts/build_validation_report.py
```

For a sensitivity run that does not overwrite the gate artifact:

```powershell
uv run python -m tradingbot walkforward --strategy trend `
  --test-days 180 --step-days 180 --output-suffix _180d
```

Generated evidence: `artifacts/validation_report.json` and
`artifacts/validation_report.md` (ignored by git, regenerated from local data).
