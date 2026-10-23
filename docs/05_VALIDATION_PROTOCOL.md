# 05 — Validation Protocol: How to Prove a Strategy (Before Risking Money)

**Purpose:** prevent the five ways backtests lie — look-ahead, survivorship, overfitting, unrealistic costs, and regime selection.  
**Rule:** a strategy is not "validated" because it has a good backtest. It is validated when it survives a pre-registered, out-of-sample, net-of-cost, multiple-testing-aware process.

---

## 1. Why standard backtests fail

| Failure | What it looks like | Why it happens |
|---|---|---|
| Look-ahead | Amazing Sharpe, tiny drawdowns | Using future data (bar close, revisions, full-sample stats) |
| Survivorship | Stable returns, no blowups | Only testing assets that still exist |
| Overfitting | Perfect parameter, fragile nearby params | Tuning on the test set |
| Cost blindness | High turnover, still profitable | Ignoring spreads, fees, funding, borrow |
| Regime selection | Great in 2020–2021, terrible in 2022 | Testing only a bull market |
| Data mining | Many "significant" strategies | Multiple testing without correction |
| Short sample | 6 months of live, "proven" | Not enough data to distinguish skill from luck |
| Execution fantasy | Fills at close, no slippage | No order-book/latency model |

The protocol below addresses each.

---

## 2. Pre-registration (before you run the backtest)

Write a one-page hypothesis:

```text
Strategy name:
Economic rationale (who is on the other side, why does the premium exist?):
Universe (PIT definition):
Signal (exact formula, lookbacks, rebalance):
Portfolio construction (weights, vol target, caps):
Cost assumptions (fees, spread, slippage, funding, borrow):
Data sources and versions:
Primary metric (e.g., net Sharpe):
Success criteria (pre-registered):
Kill criteria:
Number of trials planned:
```

**Why:** if you define success after seeing results, you will rationalize anything. Pre-registration makes the test falsifiable.

---

## 3. Data splits

### 3.1 Hold-out test set

Reserve the most recent 2–3 years as a **final test set**. Do not touch it until the strategy is frozen. If you peek, it becomes validation data.

Example for crypto (2017–2026):
- Development: 2017–2021
- Validation: 2022–2023
- Final test: 2024–2026

For US equities (2000–2026):
- Development: 2000–2015
- Validation: 2016–2020
- Final test: 2021–2026

### 3.2 Walk-forward analysis

Rolling:
```text
Train 3–5 years → test 6–12 months → roll forward 6–12 months → repeat
```
- Re-optimize only on the training window.
- Record every OOS period's performance.
- Report the distribution of OOS Sharpe, not just the average.
- Use a **purge** between train and test equal to the signal horizon (e.g., 1 month) to prevent leakage.

### 3.3 Purged K-fold cross-validation

For ML/parameter-heavy strategies:
- Split time into K folds.
- **Purge** training observations whose label window overlaps the test fold.
- **Embargo** a small period after the test fold (e.g., 1–5 days) to prevent serial correlation leakage.
- Never shuffle time series randomly.

### 3.4 Combinatorial purged cross-validation (CPCV)

- Split T observations into S blocks.
- Use combinations of S−k blocks for training and k for testing.
- Produce many OOS paths (e.g., 15–45), not one.
- Compute the distribution of Sharpe/DSR/PBO across paths.
- This is the best defense against a single lucky path.

**Implementation:** start with a simple purged K-fold; add CPCV when the strategy is parameter-heavy.

---

## 4. Multiple testing: count every trial

If you test 1,000 parameter combinations and report the best, your Sharpe is inflated. The Deflated Sharpe Ratio (DSR) corrects for:
- number of trials,
- non-normal returns (skew/kurtosis),
- selection bias.

### 4.1 DSR formula

Let:
- `SR` = Sharpe ratio per period (not annualized) of the selected strategy.
- `T` = number of return observations.
- `γ3` = skewness of returns.
- `γ4` = kurtosis of returns.
- `N` = number of independent trials.
- `Var(SR)` = variance of Sharpe ratios across trials.
- `γ` = Euler–Mascheroni constant ≈ 0.5772156649.

Expected maximum Sharpe under the null:

```text
SR0 = sqrt(Var(SR)) * [ (1 - γ) * Φ^-1(1 - 1/N) + γ * Φ^-1(1 - 1/(N*e)) ]
```

Deflated Sharpe Ratio:

```text
DSR = Φ( (SR - SR0) * sqrt(T - 1) / sqrt(1 - γ3*SR + ((γ4 - 1)/4)*SR^2) )
```

Interpretation: `DSR` is the probability that the true Sharpe exceeds the selection-adjusted benchmark. Require **DSR > 0.95** for a new strategy, or at minimum report it and treat < 0.90 as weak.

**Important:** use per-period SR in the formula, not annualized. If you annualize, adjust `T` and the variance consistently.

### 4.2 Trial registry

Log every trial, including failures:

```text
trial_id, strategy, params, universe, train_start, train_end,
test_start, test_end, sharpe, max_dd, turnover, costs,
data_version, code_commit, timestamp
```

If you don't log failures, `N` is wrong and DSR is meaningless.

### 4.3 Minimum track record length (MinTRL)

How much OOS data do you need to be confident?

```text
MinTRL = 1 + (1 - γ3*SR + ((γ4 - 1)/4)*SR^2) * (Z_α / (SR - SR*))^2
```

Where `SR*` is the benchmark Sharpe (often 0) and `Z_α` is the normal quantile (e.g., 1.645 for 95%). Use this to decide whether 6 months of live trading can possibly prove anything.

---

## 5. Probability of Backtest Overfitting (PBO)

Use **CSCV** (combinatorially symmetric cross-validation):

1. Split the return series into `S` disjoint blocks (e.g., 16).
2. For each combination of `S/2` blocks as in-sample, use the rest as out-of-sample.
3. Select the best strategy in-sample.
4. Compute its OOS rank among all strategies.
5. Convert rank to logit: `λ = log(ω/(1-ω))`.
6. `PBO = P(λ <= 0)` — the probability the selected strategy underperforms the OOS median.

Interpretation:
- PBO < 0.1: good.
- PBO 0.1–0.2: acceptable with caution.
- PBO > 0.3: likely overfit; do not deploy.

**Implementation notes:**
- Use net-of-cost returns.
- Include all trials, not just the winner.
- If the number of strategies is small, PBO is less informative; still report it.

---

## 6. Reality Check / SPA

For multiple strategies, use:
- **White's Reality Check**: bootstrap the maximum performance statistic across strategies; test whether the best is significant after data snooping.
- **Hansen's SPA**: studentized version, more powerful and robust.

These answer: "Is the best strategy better than the benchmark, after searching over many strategies?" Use them when comparing a family of strategies.

---

## 7. Cost model

### 7.1 Components

```text
total_cost = commission
           + half_spread
           + slippage/market_impact
           + funding (perps)
           + borrow (shorts)
           + taxes
           + FX conversion
```

### 7.2 Stocks

- Commission: $0 (Alpaca) or $0.0035–0.005/share (IBKR).
- Half-spread: 1–10 bps depending on liquidity.
- Slippage: 2–20 bps; higher for small caps, volatility, and size.
- Borrow: 0.3–50%+ annualized for shorts; check availability.
- SEC/FINRA fees: small but nonzero.
- Taxes: short-term gains; country-specific.

### 7.3 Crypto

- Exchange fee: 10–25 bps taker; 0–15 bps maker (venue-dependent).
- Half-spread: 1–10 bps for majors; wider for alts.
- Slippage: 5–50 bps for alts; higher in stress.
- Funding: every 8h (venue-dependent); can be positive or negative.
- Withdrawal/deposit fees; stablecoin conversion.
- Counterparty risk is not a cost line but must be capped.

### 7.4 Market impact (optional)

For larger sizes, use a square-root model:

```text
impact_bps ≈ k * sqrt(participation_rate) * daily_vol_bps
```

with `k` calibrated from your own fills (start 0.1–0.5). For retail sizes, a flat bps assumption plus participation caps is usually enough.

### 7.5 Fill assumptions

- **Daily bars:** signal at close, fill at next open + costs. Never fill at the same close unless you can prove it.
- **Intraday bars:** signal at bar close, fill at next bar open; add latency.
- **Limit orders:** fill only if price trades through; model queue conservatively.
- **Market orders:** pay taker fee + half-spread + slippage.
- **Partial fills:** model with volume participation cap.

### 7.6 Cost stress

Run every strategy at:
- 1× base costs,
- 2× costs,
- 3× costs.

If it only survives at 1×, it is fragile. If it survives at 3×, it has margin of safety.

---

## 8. Metrics to report

### Return/risk
- CAGR, annualized volatility.
- Sharpe, Sortino, Calmar.
- Max drawdown, drawdown duration, Ulcer index.
- Best/worst month, best/worst year.
- Skewness, kurtosis, VaR/CVaR (95%, 99%).

### Trading
- Number of trades, hit rate, payoff ratio, profit factor, expectancy.
- Turnover (annualized), average holding period.
- Exposure (gross/net), leverage.
- Capacity estimate (participation rate, ADV).

### Robustness
- OOS Sharpe distribution (walk-forward/CPCV).
- DSR, PBO, MinTRL.
- Subperiod Sharpe (yearly).
- Parameter sensitivity (heatmap; plateau vs spike).
- Universe sensitivity (top 20 vs top 50).
- Cost sensitivity (1×/2×/3×).
- Execution delay sensitivity (1 bar).
- Correlation to benchmarks (SPY, BTC).

### Attribution
- Alpha/beta vs benchmark.
- Factor exposure (market, size, momentum, value, carry).
- Sector/asset contribution.
- Cost attribution (fees, spread, slippage, funding).

**Report gross and net.** Net is the only number that matters.

---

## 9. Stress tests

### 9.1 Historical episodes

| Episode | What to test |
|---|---|
| 2020-03 COVID crash | Liquidity, correlation spike, gap risk |
| 2021-05 crypto crash | Leverage, liquidation, funding flip |
| 2022-05 LUNA/UST | Stablecoin depeg, contagion |
| 2022-11 FTX | Exchange insolvency, withdrawal freeze |
| 2023-03 banking crisis | Credit stress, rate volatility |
| 2024-08 yen carry unwind | Cross-asset correlation, gap risk |
| 2025-04 tariff shock | Policy event, volatility spike |
| 2026+ | Add new episodes as they happen |

### 9.2 Synthetic stress
- 2× historical volatility.
- 3× spreads/slippage.
- 1-day execution delay.
- 20% of universe missing.
- Funding flips sign.
- Correlation → 1.
- Exchange outage for 24h.

### 9.3 Operational stress
- API timeout during order.
- Partial fill.
- Duplicate fill event.
- Broker restart.
- Clock skew.
- Data corruption.

---

## 10. Paper trading protocol

### Duration
- Minimum **8 weeks** for daily strategies; 12 weeks preferred.
- For weekly strategies, 12–16 weeks.

### What to compare
- Signal match: live signal == backtest signal for the same timestamp.
- Tracking error: live vs simulated equity curve.
- Slippage: realized vs modeled.
- Turnover: realized vs expected.
- Hit rate and trade count.
- Operational incidents.

### Pass criteria
- Slippage ≤ 1.5× model (or ≤ 2× with explanation).
- Tracking error < 3% annualized.
- No duplicate/missed orders.
- Reconciliation clean every day.
- Kill switch tested.

### Fail criteria
- Any unexplained position mismatch.
- Repeated order errors.
- Slippage > 3× model.
- Signal drift (live != backtest).
- Drawdown > 1.5× backtest max DD.

---

## 11. Small live protocol

### Sizing
- Start at **25–50%** of intended risk.
- Risk per trade: 0.25–0.5% of equity.
- Max gross exposure: 1× (no leverage) initially.
- Crypto sleeve ≤ 30–50% of capital.
- Per-venue cap: 25–33% of crypto capital.

### Duration
- 3 months minimum; 6 months preferred.
- One full earnings cycle for equities; one funding cycle for crypto.

### Gates to scale
- Drawdown ≤ 1.5× backtest max DD.
- Realized slippage ≤ 2× model.
- No operational incidents.
- Rolling 3-month Sharpe > 0 (weak evidence, but a sanity check).
- Capacity still adequate.

### Kill criteria
- Drawdown > 2× backtest max DD.
- 3 consecutive months of unexplained underperformance.
- Data quality failure.
- Broker/exchange counterparty event.
- Strategy decay (rolling Sharpe < 0 for 6 months).
- Operational risk (repeated incidents).

---

## 12. Reporting template

Every strategy memo should include:

```text
1. Hypothesis and economic rationale
2. Universe (PIT definition, exclusions, delistings)
3. Signal (exact formula, lookbacks, rebalance, warm-up)
4. Portfolio construction (weights, vol target, caps, leverage)
5. Data sources and versions (checksums)
6. Cost assumptions (fees, spread, slippage, funding, borrow)
7. Results:
   - Full period, development, validation, test
   - Gross and net
   - Sharpe, Sortino, Calmar, max DD, turnover
   - Yearly table
8. Robustness:
   - Walk-forward/CPCV distribution
   - DSR, PBO, MinTRL
   - Parameter/universe/cost sensitivity
   - Stress tests
9. Risks and failure modes
10. Decision: GO / NO-GO / RESEARCH MORE
11. If GO: paper trading plan, kill criteria, review dates
```

---

## 13. Common mistakes (checklist)

- [ ] Using the close of the signal bar for the fill.
- [ ] Normalizing features over the full sample.
- [ ] Using the latest fundamentals instead of PIT.
- [ ] Using the latest macro revisions.
- [ ] Excluding delisted coins/stocks.
- [ ] Ignoring funding/borrow.
- [ ] Using maker fees for market orders.
- [ ] Testing only 2020–2021.
- [ ] Reporting the best of many trials without correction.
- [ ] Changing the strategy after seeing the test set.
- [ ] Confusing a high Sharpe with a good strategy.
- [ ] Ignoring capacity and liquidity.
- [ ] No kill switch.
- [ ] No reconciliation.
- [ ] No paper trading.

---

## 14. Minimal code interfaces

```python
@dataclass
class BacktestResult:
    equity: pl.Series
    returns: pl.Series
    positions: pl.DataFrame
    trades: pl.DataFrame
    turnover: pl.Series
    exposures: pl.DataFrame
    metrics: dict[str, float]

def run_backtest(
    target_weights: pl.DataFrame,   # index: (timestamp, asset)
    prices: pl.DataFrame,           # columns: timestamp, asset, open, high, low, close, volume
    costs: CostModel,
    calendar: TradingCalendar,
    config: BacktestConfig,
) -> BacktestResult:
    ...

def deflated_sharpe(
    sr: float, t: int, skew: float, kurt: float,
    n_trials: int, sr_variance: float,
) -> float:
    ...

def pbo(
    returns: pl.DataFrame,  # columns: strategies
    n_blocks: int = 16,
) -> float:
    ...
```

**Determinism:** set seeds, sort by timestamp, avoid floating-point non-determinism where possible, hash inputs/outputs.

---

## 15. Final rule

> If you cannot explain why the strategy should work, and show that it survives out-of-sample after realistic costs and multiple-testing correction, it is not a strategy. It is a backtest.
