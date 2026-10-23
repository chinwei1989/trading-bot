# 06 — Strategy Catalog: Candidates, Evidence, and Test Plans

**Purpose:** a ranked list of strategies worth testing, with enough detail to implement and validate.  
**Rule:** every strategy must have an economic rationale, a PIT universe, realistic costs, and a pre-registered test plan.

**Priority order:**
1. Multi-asset trend (simplest, most robust)
2. Crypto cross-sectional momentum (strong evidence, crash-prone)
3. Crypto carry/basis (structural, operationally heavy)
4. US equity momentum + quality (requires PIT fundamentals/delistings)
5. News/sentiment event overlay (data-heavy, fast-decaying)
6. ML cross-sectional ranking (Phase 2, after baselines)
7. Pairs/stat arb (niche, execution-heavy)
8. Short-term reversal (research only; costs usually kill it)

---

## 1. Multi-Asset Time-Series Trend (TSMOM)

### Hypothesis
Assets that have performed well over the past 1–12 months tend to continue; assets that have fallen tend to continue falling. The premium compensates for bearing trend risk and is reinforced by slow-moving capital, herding, and risk-management flows.

### Evidence
- Moskowitz, Ooi & Pedersen (2012): 1–12 month persistence in 58 liquid futures; diversified TSMOM portfolio has abnormal returns with little standard factor exposure.
- Asness, Moskowitz & Pedersen (2013): momentum across 8 asset classes.
- Long live CTA records (AQR, Man AHL, Winton), though fees and capacity matter.

### Universe
- Crypto: BTC, ETH, SOL, BNB, XRP (liquid majors).
- ETFs: SPY, QQQ, IWM, TLT, GLD, DBC, UUP.
- Optional futures: ES, NQ, ZN, GC, CL (only if using IBKR).
- Exclude assets with <2 years history or insufficient liquidity.

### Signal
Ensemble of:
- 1/3/6/12-month total returns (sign).
- 50/200-day moving average (price above MA).
- 20/100-day Donchian breakout.
- Average the signals (e.g., −1, 0, +1) or use a continuous score.

Position:
- Long/flat for long-only accounts; long/short where shorting is available.
- Volatility target: 10–15% annualized per asset sleeve; portfolio target 10–12%.
- Cap per asset: 10–20% of gross exposure.
- Rebalance weekly; use bands (e.g., 20% deviation) to reduce turnover.

### Costs
- Stocks/ETFs: 2–10 bps per side.
- Crypto: 10–25 bps per side.
- Futures: commission + spread; roll costs.
- Funding for perps if used.

### Expected characteristics (planning estimate)
- Turnover: 2–6×/year.
- Capacity: high for majors.
- Sharpe: 0.4–0.8 net (varies by period).
- Max DD: 15–30%.

### Risks
- Whipsaw in range-bound markets.
- Trend reversals and gap risk.
- Correlation spikes in crises.
- Long flat periods (2–3 years).

### Data
- Daily OHLCV; adjusted for splits/dividends.
- Crypto 24/7 calendar; ETFs exchange calendar.
- Volatility estimates (EWMA or 20/60-day realized).

### Test plan
- 2000–2026 for ETFs; 2015–2026 for crypto.
- Walk-forward: 5-year train, 1-year test.
- Cost stress 2×/3×.
- Execution delay: fill next open.
- Subperiod: 2008, 2020, 2022, 2024–2026.
- Compare to 60/40 and buy-and-hold.

### Why first
- Simple, transparent, low turnover.
- Works across asset classes; good for learning the pipeline.
- Easy to paper trade.

---

## 2. Crypto Cross-Sectional Momentum (XSMOM)

### Hypothesis
Relative winners among cryptocurrencies outperform relative losers over 1–3 months, driven by attention, adoption, and slow-moving retail/institutional flows. Size and momentum are priced crypto factors.

### Evidence
- Liu, Tsyvinski & Wu (2022): market, size, and momentum capture the cross-section; ten characteristics form significant long-short strategies.
- Liu & Tsyvinski (2021): time-series momentum and investor attention predict crypto returns.
- Daniel & Moskowitz (2016): momentum crashes are partly forecastable.
- Grobys et al. (2025): crypto momentum has severe crashes; volatility management helps.
- Barroso & Santa-Clara (2015): volatility-scaled momentum improves Sharpe.

### Universe
- Top 20–50 coins by 30-day dollar volume.
- Exclude stablecoins, wrapped tokens, leveraged tokens, and coins <6–12 months old.
- PIT membership; include delisted coins and exchange failures.
- Use regulated venues for volume/liquidity signals (wash-trading risk).

### Signal
- 1/3/6-month returns; skip the most recent week to avoid short-term reversal.
- Rank cross-sectionally; long top 20–30%, short bottom 20–30% (if perps available) or long-only.
- Residual momentum vs BTC (optional): regress coin returns on BTC, use residual.
- Volatility scaling: target 15–20% annualized per leg.
- Per-coin cap: 5–10%; cluster cap (L1s, DeFi, memes) 20–30%.

### Rebalance
- Weekly (e.g., Monday 00:00 UTC).
- Use buffer ranks (e.g., enter top 20%, exit below top 40%) to reduce turnover.

### Costs
- 15–25 bps per side + funding + borrow.
- Turnover 50–100%/week can easily consume the edge.
- Model 2×/3× costs.

### Expected characteristics
- Sharpe: highly regime-dependent; 0.3–0.8 net if costs are controlled.
- Max DD: 50–80% in crypto bear markets.
- Capacity: $1–10M depending on universe.

### Risks
- Momentum crashes (sharp rebounds).
- Survivorship/delisting bias.
- Wash trading/fake volume.
- Exchange/custody risk.
- Crowding.
- Regulatory shocks.

### Data
- Daily/hourly OHLCV from Binance Vision + ccxt.
- Funding rates, open interest.
- Market cap/volume from CoinGecko/Coin Metrics.
- Delisted coin list; exchange metadata.

### Test plan
- 2017–2026, PIT universe.
- Weekly rebalance; next-bar open fills.
- Include delisted coins; apply delisting returns.
- Walk-forward/CPCV; DSR/PBO.
- Stress 2021-05, 2022-05 (LUNA), 2022-11 (FTX).
- Compare long-only vs long/short; with/without beta neutralization.

---

## 3. Crypto Carry / Basis

### Hypothesis
Futures/perp prices embed a carry (funding/basis) paid by leveraged longs to shorts. When carry is high, a delta-neutral spot-long/perp-short position earns the funding/basis, compensated for providing leverage and bearing exchange/custody risk.

### Evidence
- Koijen, Moskowitz, Pedersen & Vrugt (2018): carry predicts returns across asset classes.
- Schmeling, Schrimpf & Todorov (2026): crypto carry can exceed 40% p.a., varies substantially, and reflects leveraged demand plus limits to arbitrage.

### Universe
- BTC and ETH primarily; maybe SOL.
- 2–3 regulated venues (e.g., Kraken, Coinbase, Binance if jurisdiction allows).
- Perps and/or dated futures.

### Signal
- Annualized funding/basis:
  ```text
  carry = (funding_rate_per_8h × 3 × 365) + basis_annualized
  ```
- Enter when carry > threshold (e.g., 8–12%) after fees and margin buffer.
- Exit when carry < threshold/2 or funding flips negative.
- Diversify across venues; cap per venue.

### Position
- Delta-neutral: long spot, short perp (or short future).
- Target 5–15% annualized yield; leverage ≤ 1× initially.
- Margin buffer 30–50% to survive volatility.
- Rebalance daily; monitor liquidation distance.

### Costs
- Spot/perp fees 10–25 bps per side.
- Funding (received or paid).
- Withdrawal/deposit fees.
- Borrow/margin costs.
- Counterparty risk is the dominant risk, not fees.

### Expected characteristics
- Return: 5–20% annualized in normal regimes; higher in bull markets.
- Volatility: low to moderate, but tail risk from exchange failure.
- Capacity: limited by venue liquidity and counterparty limits.

### Risks
- Exchange insolvency/withdrawal freeze (FTX).
- Funding flips; basis compresses.
- Liquidation from margin/vol spikes.
- Stablecoin depeg.
- Regulatory changes.
- Custody/operational errors.

### Data
- Funding rates, perp/spot prices, futures basis, open interest.
- Venue status/withdrawal history.
- Stablecoin prices.

### Test plan
- 2019–2026 funding history.
- Model exchange outages and funding flips.
- Stress FTX/LUNA/2024 yen carry.
- Counterparty cap: max 25–33% per venue.
- Paper trade with small size before live.

### Why not first
- Operationally heavy: multi-venue custody, margin, reconciliation.
- Tail risk is counterparty, not market.
- Requires mature execution infrastructure.

---

## 4. US Equity Momentum + Quality

### Hypothesis
Winners outperform losers over 3–12 months; profitable, low-accrual, low-leverage companies outperform. Combining momentum and quality improves robustness and reduces crash risk.

### Evidence
- Jegadeesh & Titman (1993): 3–12 month momentum.
- Asness, Moskowitz & Pedersen (2013): value and momentum everywhere; negatively correlated.
- Novy-Marx (2013): gross profitability premium.
- Daniel & Moskowitz (2016): momentum crashes.
- Novy-Marx & Velikov (2016): costs matter; lower turnover is better.

### Universe
- US large/mid caps (e.g., top 1000 by market cap), PIT membership.
- Exclude microcaps, illiquid names, recent IPOs (<12 months), financials if using leverage metrics.
- Include delisted stocks and delisting returns.

### Signal
- Momentum: 12-1 month return (skip most recent month), 6-1 month.
- Quality: gross profitability, low accruals, low leverage, stable earnings.
- Composite score: z-score momentum + z-score quality; sector-neutral.
- Rebalance monthly or quarterly; buffer ranks.

### Portfolio
- Long top decile/quintile; short bottom (if available) or long-only.
- Sector-neutral; beta-neutral optional.
- Volatility target 10–12%; per-stock cap 2–5%.
- Costs: 5–20 bps per side + borrow.

### Expected characteristics
- Turnover: 50–150%/year.
- Sharpe: 0.3–0.6 net (historically higher gross).
- Max DD: 20–40% (momentum crashes).

### Risks
- Momentum crashes.
- Short borrow costs/availability.
- Accounting quality/restatements.
- Crowding.
- Sector concentration.

### Data
- PIT prices, corporate actions, delistings (Norgate/Sharadar/CRSP).
- PIT fundamentals (SEC EDGAR/Sharadar).
- Sector classifications.
- Short interest/borrow.

### Test plan
- 2000–2026; PIT universe.
- Walk-forward; sector-neutral; cost stress.
- Include delisting returns.
- Stress 2009 momentum crash, 2020 COVID, 2022 rate shock.

### Why later
- Data plumbing (PIT fundamentals, delistings) is significant.
- Shorting adds borrow/crowding complexity.
- Better as a diversifier after crypto/trend is stable.

---

## 5. News / Sentiment Event Overlay

### Hypothesis
Markets underreact or overreact to material events (earnings, guidance, regulatory, hacks, listings, ETF flows). Sentiment extremes can signal reversals or risk.

### Evidence
- Tetlock (2007): media pessimism predicts downward pressure then reversion.
- Baker & Wurgler (2006): sentiment affects hard-to-arbitrage stocks.
- Da, Engelberg & Gao (2014): search sentiment predicts short-term reversals.
- Bollen, Mao & Zeng (2011): Twitter mood predicts DJIA — replication is fragile (Lachanski & Pav 2017).

### Universe
- US stocks: liquid large/mid caps with news coverage.
- Crypto: BTC/ETH/major alts with high social volume.
- Event types: earnings, guidance, analyst revisions, M&A, regulatory, hacks, listings, ETF flows, macro surprises.

### Signal
- Event detection: LLM/FinBERT classifies news into structured events.
- Sentiment: polarity, confidence, novelty, source credibility.
- Aggregation: mention volume z-score, sentiment mean/dispersion, engagement-weighted.
- Trade horizon: 1–5 days; event window.
- Use as overlay: reduce risk at extreme negative sentiment/uncertainty; add exposure at positive surprises with confirmation.

### Costs
- Data: X API, news API, GDELT, Reddit.
- Trading: same as underlying asset; high turnover.
- Model: LLM inference cost.

### Expected characteristics
- Alpha: small, fast-decaying; capacity limited.
- Best use: risk overlay/event filter, not standalone.
- Sharpe: uncertain; require strong OOS evidence.

### Risks
- Bots/spam/manipulation.
- Look-ahead (post timing, LLM training cutoff).
- Data cost.
- Fast decay/crowding.
- Regulatory/ToS.

### Test plan
- Build a timestamped news/social archive.
- Backtest with exact model version/prompts.
- Compare to FinBERT/lexicon baseline and placebo.
- Forward paper trade 3–6 months before capital.
- Require incremental OOS value over the base strategy.

---

## 6. ML Cross-Sectional Ranking

### Hypothesis
Nonlinear interactions among many weak predictors (momentum, volatility, liquidity, funding, macro, sentiment) improve cross-sectional return forecasts.

### Evidence
- Gu, Kelly & Xiu (2020): trees/NNs roughly double leading regression strategies; momentum, liquidity, volatility dominate.
- Fischer & Krauss (2018): LSTM on S&P 500; costs/capacity matter.
- Practical caveat: published results often ignore costs and are not reproducible.

### Universe
- Crypto: top 50–100 liquid coins.
- US equities: top 1000 liquid stocks (later).
- Features: 50–200, all PIT.

### Features
- Momentum (1/3/6/12m), reversal (1w/1m).
- Volatility (20/60/120d), beta, skew, kurtosis.
- Liquidity (ADV, turnover, spread).
- Funding/basis/OI (crypto).
- Size, age, exchange/venue.
- Macro regime (rates, VIX, credit, DXY).
- Sentiment/attention (if available).
- Quality/value (equities).

### Model
- LightGBM/XGBoost baseline; linear ridge as sanity check.
- Target: forward 1-week/1-month cross-sectional return rank (or excess vs sector).
- Purged K-fold + embargo; CPCV.
- Feature importance/SHAP stability.
- Meta-labeling: predict whether the primary signal will succeed; size accordingly.

### Portfolio
- Rank to weights; sector-neutral; vol-target; turnover penalty.
- Costs 2×/3×; capacity analysis.

### Risks
- Overfitting/non-stationarity.
- Feature leakage.
- Regime shifts.
- Capacity/costs.
- Black-box risk.

### Test plan
- Strict PIT; walk-forward/CPCV; DSR/PBO.
- Compare to simple momentum baseline; require incremental OOS.
- Paper trade 3–6 months.

### Why Phase 2
- Needs a solid data/feature pipeline and validation discipline.
- Easy to overfit; not a first strategy.

---

## 7. Pairs / Statistical Arbitrage

### Hypothesis
Related assets diverge temporarily and converge; the spread is mean-reverting.

### Evidence
- Gatev, Goetzmann & Rouwenhorst (2006): pairs trading in US equities; later decay/crowding.
- Crypto pairs (ETH/BTC, L1 pairs) can be more retail-accessible.

### Universe
- Crypto: ETH/BTC, SOL/ETH, L1 baskets; high liquidity.
- Equities: sector ETFs, twin shares, supplier/customer pairs.

### Signal
- Cointegration (Engle-Granger/Johansen) or OU process.
- Half-life 1–20 days; z-score entry ±2, exit 0, stop ±3.5.
- Rolling window 60–252 days; re-estimate monthly.
- Structural break filter (e.g., CUSUM, correlation regime).

### Costs
- High turnover; 10–30 bps per side.
- Short borrow for equities.
- Funding for perps.

### Risks
- Structural breaks.
- Crowding.
- Borrow/liquidity.
- Execution timing.

### Test plan
- OOS pairs selection; walk-forward.
- Include costs and borrow.
- Stress correlation shocks.
- Paper trade.

### Verdict
- Niche; only if you have a specific edge or data advantage. Not a first build.

---

## 8. Short-Term Reversal (Research Only)

### Hypothesis
Short-term overreaction creates 1–5 day reversal.

### Evidence
- Jegadeesh (1990); Lehmann (1990); Da, Engelberg & Gao (2014).

### Reality
- Extremely high turnover; spreads, fees, and adverse selection usually consume the edge for retail.
- Requires intraday execution and smart order routing to have a chance.

### Verdict
- Research curiosity; do not deploy without proof of net edge after 3× costs.
- Better use: as a feature/overlay in ML, not a standalone strategy.

---

## 9. Portfolio combinations

### Recommended first portfolio

| Sleeve | Weight | Strategy | Vol target |
|---|---|---|---|
| Trend | 40% | Multi-asset TSMOM | 8–10% |
| Crypto XSMOM | 30% | Weekly long/short or long-only | 12–15% |
| Cash/defensive | 30% | T-bills / stablecoins | — |

### Later

| Sleeve | Weight | Strategy |
|---|---|---|
| Trend | 30% | TSMOM |
| Crypto XSMOM | 20% | XSMOM |
| Crypto carry | 20% | Delta-neutral basis |
| Equity momentum/quality | 20% | US equities |
| Sentiment/ML overlay | 10% | Risk overlay/alpha |

**Correlation caps:** max 0.7 between sleeves; max 30–40% in crypto; max 25–33% per venue.

**Rebalancing:** monthly across sleeves; weekly within strategies; bands to reduce turnover.

---

## 10. What not to trade (initially)

- **HFT/market making** — infrastructure and latency disadvantage.
- **1-minute scalping** — costs and noise dominate.
- **Leveraged tokens/options as a core** — path-dependent, expensive.
- **Newly listed coins** — manipulation, no history.
- **Illiquid microcaps** — capacity and slippage.
- **Copy trading/signal groups** — no control, aligned incentives unclear.
- **LLM autonomous trading** — no proven edge, high operational risk.
- **Strategies that only work on one coin/stock** — likely overfit.

---

## 11. Strategy scorecard (for ranking)

| Criterion | Weight | Notes |
|---|---|---|
| Economic rationale | 20% | Who pays and why? |
| Evidence quality | 20% | Peer-reviewed, OOS, long sample |
| Data availability/PIT | 15% | Can you get clean data? |
| Cost sensitivity | 15% | Survives 2×/3× costs? |
| Robustness | 10% | Parameter/universe stability |
| Capacity | 5% | Enough for your capital |
| Operational complexity | 10% | Can you run it reliably? |
| Diversification | 5% | Correlation to other sleeves |

Score each candidate 1–5; require ≥3.5 to proceed to paper.

---

## 12. Final recommendation

**Build in this order:**
1. Trend (4–6 weeks)
2. Crypto XSMOM (4–6 weeks)
3. Paper trade both (8–12 weeks)
4. Carry (research + paper, 6–8 weeks)
5. Equity momentum/quality (8–12 weeks)
6. Sentiment/ML (ongoing)

**Do not skip the boring parts.** The edge is in the data hygiene, cost model, risk control, and discipline — not in the complexity of the signal.
