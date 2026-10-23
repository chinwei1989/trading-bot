# 01 — Deep Research Report: How Crypto & US Equity Trading Bots Actually Work

**Research date:** 22 October 2026  
**Scope:** systematic/algorithmic trading, retail-feasible, backtestable, crypto + US equities  
**Constraint:** no paid signal services, no copy trading, own implementation, AI-capable

---

## 1. Executive summary

### 1.1 The central finding

The retail trading world is saturated with bots that show beautiful equity curves and no audited live record. The academic and professional evidence is much less exciting but far more useful:

- **A small number of risk premia and behavioral effects are real and persistent on average:** time-series trend, cross-sectional momentum, carry, value/quality, and low-volatility.
- **Their net-of-cost edge is modest.** Public factors decay after publication; high-turnover anomalies usually die after realistic costs.
- **The best-documented crypto effects are market, size, and momentum** (Liu, Tsyvinski & Wu 2022), plus time-series momentum and investor attention (Liu & Tsyvinski 2021). Crypto carry/basis is a large structural premium but carries exchange and funding risk.
- **Sentiment and LLM-driven trading are weak standalone edges.** They are better as event filters, risk overlays, and feature inputs.
- **The only "proof" that matters is prospective, out-of-sample, net-of-cost performance with a full audit trail.** Everything else is a hypothesis.

### 1.2 What a realistic target looks like

For a solo builder with $10k–100k, daily/weekly strategies, and this PC:

| Metric | Realistic good outcome | Comment |
|---|---|---|
| Net Sharpe | 0.5–1.0 | 5+ is a red flag, not a goal |
| Annualized return | 8–15% at 10–15% vol | Crypto sleeves can be higher |
| Max drawdown | 20–30% stocks; 40–60% crypto | Plan for it, don't be surprised |
| Turnover | Low to moderate | High turnover is where retail edges die |
| Capacity | $100k–$5M depending on liquidity | You are small; use it |
| Edge horizon | Months to years | Not microseconds |

These are **planning assumptions**, not promises.

### 1.3 The recommended path

1. Build the **data + validation platform** first.
2. Start with **time-series trend** (simple, robust, multi-asset).
3. Add **crypto cross-sectional momentum** with crash controls.
4. Add **crypto carry/basis** only after execution/custody is mature.
5. Add **US equity momentum/quality** when point-in-time fundamentals are in place.
6. Add **sentiment/ML** as overlays/features, not as the core.
7. Paper trade 8–12 weeks; live small for 3–6 months; scale only after gates.

---

## 2. Method and evidence hierarchy

This report prioritizes:

1. **Peer-reviewed academic papers** with long samples and out-of-sample tests.
2. **Primary documentation** from exchanges, brokers, and data vendors (pricing, API limits, licensing).
3. **Open-source code** that is actively maintained and has real users.
4. **Practitioner books/blogs** only for implementation details, not for performance claims.
5. **Backtests and track records** are treated as marketing until independently replicated.

Evidence hierarchy for a trading idea:

```text
Economic hypothesis (why should this pay?)
    > Out-of-sample evidence on a broad universe
        > Net-of-cost evidence with realistic execution
            > Prospective paper/live evidence
                > A backtest screenshot
```

A strategy that fails the first question ("who is on the other side and why?") is usually a data artifact.

---

## 3. The market landscape: who does what

### 3.1 Participant map

| Participant | Edge | Horizon | Retail-feasible? |
|---|---|---|---|
| Market makers / HFT | Speed, rebates, queue position, inventory control | µs–seconds | No |
| Statistical arbitrage funds | Data, execution, risk models, capital | Minutes–days | Partially (small scale) |
| CTAs / trend followers | Diversification, discipline, vol targeting | Weeks–months | Yes |
| Macro funds | Information, macro models, sizing | Weeks–quarters | Partially |
| Equity factor funds | Breadth, low costs, patient capital | Months–years | Yes |
| Event-driven funds | Legal/industry expertise, deal flow | Days–months | Partially |
| Crypto funds | 24/7 coverage, custody, on-chain data | Hours–months | Yes, with risk |
| Retail discretionary | Flexibility, small size | Minutes–months | Yes, but behaviorally hard |
| Retail systematic | Niche ideas, low capacity, automation | Days–months | Yes — this is your lane |

### 3.2 What retail actually does (and what fails)

Common retail approaches:
- **Technical analysis / indicator stacking** — easy to backtest, easy to overfit; no economic rationale.
- **Grid bots / DCA** — profits in ranges, catastrophic in trends; often marketed as "passive".
- **Mean reversion / pairs** — real but crowded; costs and structural breaks kill naive versions.
- **Momentum rotation** — one of the better retail-accessible families.
- **Copy trading / signal groups** — aligned incentives are rare; you inherit someone else's risk.
- **ML price prediction** — usually leakage or non-stationarity; backtests look great, live decays.
- **LLM/agent bots** — new, exciting, almost no long-term evidence; high look-ahead risk.

What tends to work for small systematic players:
- **Low-capacity niches** that institutions can't scale into.
- **Simple, economically motivated signals** with low turnover.
- **Better data hygiene and risk control** than the average retail competitor.
- **Diversification across uncorrelated strategies**, not one perfect model.
- **Patient capital** and the ability to survive drawdowns.

### 3.3 The "proven record" problem

Public track records suffer from:
- **Survivorship bias** — failed bots stop publishing; successful ones keep publishing.
- **Selection bias** — thousands of strategies were tried; only the winner is shown.
- **Backtest overfitting** — parameters tuned on the same data used to evaluate.
- **Unrealistic fills** — assuming you get the close, no slippage, no fees, no borrow.
- **Short samples** — 6–18 months, often a single regime.
- **No audit** — self-reported returns, no broker statements, no reconciliation.
- **Changing strategy** — the live version differs from the advertised one.

A credible track record needs:
- Broker/exchange statements or independent administrator.
- Full history including losses and drawdowns.
- Net-of-fee, net-of-slippage returns.
- Documented universe, position sizes, and risk limits.
- At least one full market cycle, ideally 3+ years.
- Reproducible code/data (rare).

**Conclusion:** do not look for a proven bot to copy. Look for a proven *process* to implement.

---

## 4. Strategy taxonomy and evidence

### 4.1 Time-series momentum / trend following

**Hypothesis:** assets that have risen over the past 1–12 months tend to continue; assets that have fallen tend to continue falling. Driven by under-reaction, herding, risk management flows, and slow-moving capital.

**Evidence:**
- Moskowitz, Ooi & Pedersen (2012): significant 1–12 month persistence in 58 liquid futures across equities, currencies, commodities, and bonds; a diversified portfolio delivers abnormal returns with little standard factor exposure and performs best in extreme markets.
- Asness, Moskowitz & Pedersen (2013): momentum premia across 8 markets; negatively correlated with value.
- Long live records from CTAs (AQR, Man AHL, Winton) — but fees, capacity, and long flat periods.

**Implementation:**
- Universe: BTC, ETH, major L1s; SPY, QQQ, TLT, GLD, DBC, FX futures/ETFs.
- Signal: ensemble of 1/3/6/12-month returns, 50/200-day moving averages, or breakout channels.
- Position: long/flat or long/short; volatility-scaled to a target (e.g., 10–15% annualized).
- Rebalance: daily or weekly; low turnover.
- Costs: 5–10 bps per stock trade; 10–25 bps crypto; funding for perps.

**Risks:**
- Whipsaw in range-bound markets.
- Trend crashes / sharp reversals.
- Correlation across assets in liquidity crises.
- Long drawdowns (years).

**Why start here:** simplest to validate, robust across assets, low turnover, teaches the full pipeline.

### 4.2 Cross-sectional momentum (equities and crypto)

**Hypothesis:** relative winners outperform relative losers over 3–12 months; losers underperform. In crypto, size and momentum are priced factors.

**Evidence:**
- Jegadeesh & Titman (1993): 3–12 month equity momentum generates significant positive returns; part dissipates after a year.
- Liu, Tsyvinski & Wu (2022): a three-factor crypto model (market, size, momentum) captures the cross-section; ten characteristics form significant long-short strategies.
- Liu & Tsyvinski (2021): strong time-series momentum and investor attention predict crypto returns.
- Daniel & Moskowitz (2016): momentum crashes are partly forecastable; they occur in panic states after market declines and high volatility.
- Grobys et al. (2025): crypto momentum is subject to severe crashes; even a single coin can make portfolio returns insignificant; volatility management helps.
- Barroso & Santa-Clara (2015): volatility-scaled momentum has a much better Sharpe than static momentum.

**Implementation:**
- Universe: top 20–50 liquid coins by dollar volume; exclude stablecoins, wrapped/leveraged tokens, newly listed <6–12 months.
- Signal: 1–3 month return, skip most recent week; rank; long top quintile, short bottom quintile (if perps available) or long-only.
- Neutralize: beta to BTC, sector/cluster, size.
- Rebalance: weekly; vol-target each leg; cap per-coin weight.
- Costs: 15–25 bps per side + funding + borrow; turnover can be 50–100%/week.

**Risks:**
- Momentum crashes (sharp rebounds).
- Survivorship/delisting bias.
- Wash trading and fake volume.
- Exchange/custody risk.
- Crowding.

**Verdict:** good second strategy, but only with crash controls and realistic costs.

### 4.3 Carry / basis

**Hypothesis:** investors pay for leverage, hedging, or convenience; the carry of an asset (yield minus financing) predicts returns.

**Evidence:**
- Koijen, Moskowitz, Pedersen & Vrugt (2018): carry predicts returns across global equities, bonds, currencies, commodities, and options.
- Schmeling, Schrimpf & Todorov (2026): crypto carry — futures minus spot — can exceed 40% p.a., varies substantially, and reflects leveraged demand plus limits to arbitrage.
- Crypto perpetual funding is a direct, observable carry signal.

**Implementation:**
- Long spot BTC/ETH, short perp (delta-neutral) on 2–3 regulated venues.
- Enter when annualized funding/basis > threshold (e.g., 8–12%) after fees and margin.
- Diversify venues; cap exposure per exchange; monitor funding flips, liquidation, and stablecoin depeg.
- Rebalance daily; keep a cash/margin buffer.

**Risks:**
- Exchange insolvency (FTX), withdrawal freezes.
- Funding reverses; basis compresses.
- Liquidation from margin/vol spikes.
- Custody, regulatory, tax.
- Stablecoin depeg.

**Verdict:** attractive but operationally heavy. Only after you have reliable execution, reconciliation, and multi-venue custody.

### 4.4 Value / quality

**Hypothesis:** cheap, profitable, safe companies outperform expensive, unprofitable, risky ones over long horizons.

**Evidence:**
- Fama & French (1992, 2015); Asness et al. (2013); Novy-Marx (2013) gross profitability; Hou, Xue & Zhang (2015) investment-based factor model.
- Long-sample evidence, but slow and regime-dependent.

**Implementation:**
- US large/mid caps; PIT fundamentals; sector-neutral; monthly/quarterly rebalance.
- Combine with momentum (negatively correlated) and low volatility.
- Costs: low-to-moderate; short borrow for longs/shorts.

**Risks:**
- Value traps; accounting quality; restatements.
- Long underperformance (2010s growth era).
- Crowding.

**Verdict:** good diversifier later; requires PIT fundamentals and careful accounting.

### 4.5 Low volatility / betting against beta

**Hypothesis:** leverage-constrained investors bid up high-beta assets, so low-beta assets earn higher risk-adjusted returns; a leveraged low-beta / short high-beta portfolio earns a premium.

**Evidence:**
- Frazzini & Pedersen (2014): BAB factor produces significant risk-adjusted returns across 19 markets and asset classes; funding constraints matter.
- Novy-Marx & Velikov (2021) critique: implementation and cost sensitivity.

**Risks:** leverage, rate sensitivity, crowding, shorting costs.

**Verdict:** useful factor, but not a first build.

### 4.6 Short-term reversal

**Hypothesis:** short-term overreaction creates 1–5 day reversal.

**Evidence:**
- Jegadeesh (1990); Lehmann (1990); Da, Engelberg & Gao (2014) for sentiment-driven reversals.

**Reality:** extremely high turnover; spreads, fees, and adverse selection usually consume the edge for retail. A research curiosity, not a first live strategy.

### 4.7 Pairs / statistical arbitrage

**Hypothesis:** related assets diverge temporarily and converge; cointegration or Ornstein–Uhlenbeck spread.

**Evidence:**
- Gatev, Goetzmann & Rouwenhorst (2006): pairs trading in US equities; later work shows decay and crowding.

**Reality:** still exists in niches (crypto pairs, sector ETFs), but requires good execution, borrow, and structural-break detection. High operational complexity for modest capacity.

### 4.8 Event-driven / news / sentiment

**Hypothesis:** markets underreact or overreact to news, earnings, guidance, regulatory events, listings, hacks, and flows.

**Evidence:**
- Tetlock (2007): media pessimism predicts downward pressure followed by reversion.
- Baker & Wurgler (2006): sentiment affects hard-to-arbitrage stocks.
- Da, Engelberg & Gao (2014): FEARS search sentiment predicts short-term reversals.
- Bollen, Mao & Zeng (2011): Twitter mood predicts DJIA — but later replication (Lachanski & Pav 2017) found serious issues.
- Crypto: attention and social sentiment have some predictive power, but bots, manipulation, and short half-life.

**Reality:** best used for **event detection** and **risk avoidance**, not as a standalone daily alpha. Data costs, latency, and look-ahead are major.

### 4.9 Machine learning cross-section

**Hypothesis:** nonlinear interactions among many weak predictors improve cross-sectional return forecasts.

**Evidence:**
- Gu, Kelly & Xiu (2020): trees and neural networks roughly double the performance of leading regression-based strategies; predictive gains come from nonlinear interactions; momentum, liquidity, and volatility dominate.
- Fischer & Krauss (2018): LSTM on S&P 500; but transaction costs and capacity are serious.
- Practical caveat: published ML results often use large caps, ignore costs, and are not reproducible.

**Reality:** LightGBM on 50–200 carefully constructed features is a reasonable Phase 2 research direction. Deep learning is usually not worth it on daily bars with <20 years of data.

### 4.10 Reinforcement learning / LLM agents

**RL:** FinRL and similar frameworks show impressive backtests, but the sim-to-real gap, reward hacking, and non-stationarity are severe. No credible long-term live record. Use only for execution/portfolio allocation research, after supervised baselines.

**LLM agents:** TradingAgents (Apache-2.0, 112k+ GitHub stars), FinRobot, AI hedge fund repos — active research, but no audited live record. Key risks:
- **Training-data look-ahead:** the model has seen future outcomes in its training data.
- **Hallucination:** confident but wrong event interpretation.
- **Cost/latency:** not suitable for fast markets.
- **Evaluation:** backtesting an LLM on history requires the exact model version and timestamped prompts; otherwise it's fiction.

**Verdict:** use LLMs as research copilots and event extractors, not autonomous traders.

---

## 5. What the evidence says about "edge decay"

| Source | Finding | Implication |
|---|---|---|
| McLean & Pontiff (2016) | 26% lower out-of-sample, 58% lower post-publication across 97 predictors | Assume public signals are partly arbitraged |
| Harvey, Liu & Zhu (2016) | New factor needs t > 3.0; most claimed findings likely false | Use a high bar; count trials |
| Novy-Marx & Velikov (2016) | Most anomalies with >50% monthly turnover fail after costs | Prefer lower turnover |
| Bailey & López de Prado (2014) | Deflated Sharpe corrects for selection and non-normality | Report DSR, not raw Sharpe |
| Bailey et al. (2016) | PBO estimates overfitting via CSCV | Require PBO < 0.2 |
| Cong et al. (2022) | >70% of reported volume on unregulated crypto exchanges may be wash trading | Don't trust volume/price from weak venues |

**Practical rule:** if a strategy only works with the best parameter, the cheapest fees, and the most liquid period, it is not a strategy — it is a curve fit.

---

## 6. Market microstructure: what actually matters at retail scale

### 6.1 You are a price taker

At $10k–100k, your orders are small relative to market volume. Your costs are:
- **Spread** (half-spread per side).
- **Slippage** (market impact + adverse selection).
- **Fees** (commissions, exchange fees, funding).
- **Borrow** (for shorts).
- **Taxes** (short-term gains, wash sales).

You do **not** need a colocated HFT stack. You **do** need:
- Realistic fill assumptions.
- Limit orders where possible.
- Participation limits (e.g., <1–5% of ADV for stocks, <0.5–1% of volume for crypto).
- Order slicing for larger sizes.
- Monitoring of realized vs modeled slippage.

### 6.2 Micro features that are usable

**Crypto:**
- Perp funding rate, basis, open interest.
- Liquidations, long/short ratio.
- Order-book imbalance (if you have L2 data).
- Trade flow / taker buy ratio.
- Stablecoin supply and exchange netflows.
- On-chain activity (active addresses, fees, realized cap, MVRV, SOPR).
- Exchange reserves and whale flows.

**Equities:**
- Volume, turnover, spread, volatility.
- Short interest, borrow cost, days-to-cover.
- Options implied volatility, skew, open interest.
- Earnings surprise, guidance, analyst revisions.
- Insider transactions, 13F changes, SEC filings.
- Dark pool / off-exchange volume (if licensed).

### 6.3 What not to bother with at first

- L3 order book reconstruction for HFT.
- Nanosecond timestamps.
- Colocation.
- Latency arbitrage.
- Market making on dozens of venues.

These require infrastructure and capital that don't fit a home PC.

### 6.4 Execution algorithms you might actually use

At retail size, you do not need a full execution algo suite, but you should avoid dumping market orders into thin books.

| Algorithm | How it works | When to use |
|---|---|---|
| **Market order** | Immediate fill at best available price | Liquid majors, small size, signal urgency |
| **Limit order** | Post at a price; may not fill | Liquid markets, non-urgent rebalance |
| **TWAP** | Slice over a fixed time window | Moderate size, reduce timing risk |
| **VWAP** | Slice in proportion to historical volume | Larger size, liquid session |
| **POV** | Participate at a % of live volume | Adaptive to volume; needs live data |
| **Iceberg** | Show small size, hide the rest | Avoid signaling; venue support required |

**Retail rules of thumb:**
- Keep participation <1–5% of ADV for stocks, <0.5–1% of volume for crypto.
- Use limit orders for rebalances when the signal is not time-critical.
- Use market orders only for risk exits or very liquid instruments.
- Measure realized slippage vs arrival price; feed it back into the cost model.
- For daily strategies, trading at the next open with a limit band is usually enough.

---

## 7. Macro: how to use it without pretending to forecast

### 7.1 Macro is a regime/risk input, not a short-term direction signal

Use macro to answer:
- Is liquidity expanding or contracting?
- Is the market in a risk-on or risk-off regime?
- Is volatility/credit stress rising?
- Should gross exposure be reduced?

Do **not** use macro to predict tomorrow's BTC close.

### 7.2 Core macro series (free from FRED/ALFRED)

| Category | Series |
|---|---|
| Policy rates | DFF, EFFR, SOFR |
| Yield curve | DGS2, DGS10, T10Y2Y, T10Y3M |
| Inflation | CPIAUCSL, CPILFESL, PCEPI, PCEPILFE |
| Labor | UNRATE, PAYEMS, ICSA |
| Growth | INDPRO, GDPC1, UMCSENT |
| Credit | BAMLH0A0HYM2, BAMLC0A0CM |
| Volatility | VIXCLS |
| Dollar | DTWEXBGS |
| Liquidity | WALCL, RRPONTSYD, TGA, reserves |
| Commodities | DCOILWTICO, GOLDPMGBD228NLBM |

**Critical:** use **ALFRED vintages** (real-time data as it was published), not the latest revised series. Otherwise your backtest uses numbers nobody knew at the time.

### 7.3 Macro feature examples

- 10y real yield (DFII10) change over 1/3/6 months.
- Yield curve slope (10y–2y) and its change.
- HY OAS level and change (credit stress).
- VIX level, percentile, and term structure (VIX/VIX3M).
- DXY trend.
- Fed funds futures implied path (if available).
- Global liquidity proxy: central bank balance sheets + reverse repo + TGA.
- Crypto-specific: stablecoin supply growth, BTC dominance, ETF flows.

### 7.4 Regime overlay design

A simple, robust approach:
- Compute a risk-on/off score from 4–6 macro features (trend, credit, vol, liquidity).
- Scale gross exposure between 0.3× and 1.0×.
- Never let macro override risk limits; it only reduces risk.
- Validate as an overlay on a baseline strategy, not as a standalone alpha.

**Avoid:** complex macro models with dozens of parameters, regime-switching models fit to 20 years, and narrative-driven discretionary overrides.

---

## 8. Sentiment and X (Twitter): a realistic design

### 8.1 What the evidence says

- Tetlock (2007): media pessimism predicts downward pressure then reversion.
- Baker & Wurgler (2006): sentiment affects stocks that are hard to arbitrage (small, young, volatile, unprofitable).
- Da, Engelberg & Gao (2014): search-based sentiment predicts short-term reversals.
- Bollen, Mao & Zeng (2011): Twitter mood predicted DJIA direction with high accuracy — but Lachanski & Pav (2017) found the result fragile and sensitive to methodology.
- Crypto social sentiment is noisy, bot-infested, and fast-decaying.

**Conclusion:** sentiment is a **weak, noisy, fast-decaying overlay**. It is not a core edge. Use it for:
- Event detection (hacks, listings, regulatory news, earnings).
- Risk aversion (extreme euphoria/panic).
- Feature input to a broader model.
- Research prioritization.

### 8.2 X API economics (as of Oct 2026)

X API v2 now uses **pay-per-usage credits**:
- **$0.005 per post read**, $0.010 per user read.
- **3 million post reads per monthly billing cycle** cap on pay-per-use.
- **Recent search:** last 7 days, all developers.
- **Full-archive search:** back to 2006, pay-per-use and Enterprise.
- Deduplication within a 24-hour UTC window.
- Spending limits and auto-recharge available.

**Cost examples:**
- 2,000 posts/day × 30 days = 60,000 posts/month ≈ **$300/month**.
- 1 million historical posts ≈ **$5,000** (one-time).
- A focused list of 200 accounts + cashtag searches is much cheaper than firehose-scale ingestion.

**Implication:** you can backtest X sentiment historically, but it is a paid dataset. Budget for it or start with news/GDELT/Reddit/Bluesky and add X only when the strategy justifies it.

### 8.3 Alternatives and their trade-offs

| Source | Cost | History | Notes |
|---|---|---|---|
| X API | $0.005/post | Full archive (paid) | Best for crypto/finance chatter; ToS restrictions |
| Reddit API | Free 100 QPM non-commercial; commercial ~$0.24/1k calls | Recent + search | Good for retail sentiment; commercial license needed |
| Bluesky/AT Protocol | Free firehose | Growing | Smaller finance community; open protocol |
| GDELT | Free | 2013–present, 15-min updates | News events, not social; huge |
| StockTwits | Free API historically | Limited | Verify current access; API has changed |
| CryptoPanic | Free tier | Recent | Crypto news aggregation |
| Fear & Greed Index | Free | 2018–present | Simple regime proxy |
| Google Trends | Unofficial | Long | Search attention; rate-limited |
| News APIs (Tiingo/EODHD/Finnhub) | $0–100/mo | Years | Cleaner, licensed, timestamped |

### 8.4 Sentiment pipeline design

```text
Ingest (X/Reddit/Bluesky/news)
  → dedupe (text hash, near-duplicate)
  → language filter
  → bot/spam filter (account age, posting rate, follower graph)
  → entity linking (cashtag $BTC, ticker, coin name, company alias)
  → timestamp normalization (UTC, event time vs knowledge time)
  → sentiment model (FinBERT baseline, LLM for nuanced events)
  → aggregate per asset per horizon:
       mention volume, sentiment mean, dispersion, engagement-weighted,
       novelty (first mention), source credibility
  → features (z-scored, lagged, PIT)
  → backtest with exact timestamps
```

### 8.5 Sentiment pitfalls

- **Bots and spam** — a few accounts can dominate a cashtag.
- **Pump-and-dump** — sentiment spikes are often exit liquidity.
- **Survivorship in posts** — deleted posts and banned accounts.
- **Look-ahead** — a post at 16:05 cannot be used at 16:00.
- **Engagement weighting** — likes/reposts can be bought.
- **Model drift** — slang and memes change.
- **LLM training cutoff** — the model may "know" future outcomes.
- **Regulatory/ToS** — redistribution restrictions, privacy.

**Recommendation:** build the sentiment pipeline as a **separate service** with a clean interface. Start with **news + GDELT + Reddit** (cheap, licensed), add X only when a focused hypothesis justifies the cost. Use sentiment first as a **risk overlay** (reduce exposure at extreme euphoria) and as an **event detector**, not as a standalone long/short signal.

---

## 9. AI: where it actually adds value

### 9.1 Three layers

| Layer | Use | Maturity |
|---|---|---|
| Research copilot | Summarize papers, generate code, review backtests, extract events | High — use now |
| Feature extractor | NLP sentiment, entity linking, event classification, embeddings | Medium — useful |
| Predictive model | LightGBM/XGBoost on tabular features, regime classification | Medium — real but modest |
| Deep learning | LSTM/Transformer on returns/order book | Low–medium — data-hungry |
| RL | Execution, allocation | Low — research only |
| Autonomous LLM trader | End-to-end decisions | Very low — not recommended |

### 9.2 What works

- **LightGBM/XGBoost** on 50–200 cross-sectional features, with purged CV and strict feature timing.
- **FinBERT** for cheap sentiment; **LLM** for nuanced event extraction (earnings guidance, regulatory, hacks).
- **Embeddings + clustering** to discover narratives and group news.
- **Regime classification** (HMM, Markov switching, or simple rules) as a risk overlay.
- **Anomaly detection** for data quality and execution issues.
- **LLM as a research assistant** — code generation, literature review, test generation, incident summaries.

### 9.3 What doesn't (yet)

- LLM directly predicting next-day prices from news.
- RL agents trained on one market regime.
- Deep learning on 5 years of daily bars for 20 assets.
- "AI hedge fund" multi-agent frameworks used as black boxes.
- Fine-tuning a large LLM on a single GPU-less PC (impractical).

### 9.4 Guardrails

1. **Deterministic risk engine** with veto power.
2. **Model registry**: version, training window, features, hyperparameters, evaluation.
3. **Prompt/version logging** for any LLM used in research or features.
4. **Point-in-time inputs**; no future data in prompts.
5. **Shadow mode**: AI signals run alongside the baseline for 3–6 months before capital.
6. **Cost caps** and rate limits for API calls.
7. **Human approval** for new strategies and parameter changes.
8. **Kill switch** independent of the AI layer.

---

## 10. Feasibility on this PC

### 10.1 Hardware assessment

| Component | Spec | Verdict |
|---|---|---|
| CPU | Ryzen AI 9 HX 470, 12C/24T | Excellent for vectorized backtests and LightGBM |
| RAM | 28 GB | Enough for 10–20 years of minute bars for hundreds of symbols |
| GPU | Radeon 890M iGPU, no CUDA | Fine for inference; not for LLM fine-tuning |
| Disk | 646 GB free | Enough for ~100–200 GB of Parquet data + backups |
| OS | Windows 11 + WSL2 Ubuntu | Native Windows works; WSL2 better for production |
| Python | Not installed (Store stub only) | Install via `uv` |

### 10.2 Data storage estimate

- 1-minute bars, 500 US stocks × 10 years × 390 bars/day ≈ **491M rows** ≈ 25–40 GB compressed Parquet.
- 1-minute bars, 100 crypto pairs × 8 years × 1440 bars/day ≈ **420M rows** ≈ 20–35 GB.
- Daily bars: negligible (<1 GB).
- Tick data: 100 GB–several TB; avoid initially.
- Keep 30–40% disk free for temporary files, backups, and model artifacts.

### 10.3 Runtime expectations

- Vectorized backtest of 1,000 parameter sets on 10 years of daily data: seconds to a few minutes.
- Event-driven Nautilus backtest: minutes per run; fine for final validation.
- LightGBM training on 1M rows × 100 features: seconds to minutes on CPU.
- FinBERT inference on 100k headlines: minutes to hours on CPU; batch and cache.
- LLM API calls: network-bound; budget and cache aggressively.

### 10.4 What not to attempt

- Colocated HFT or market making.
- L3 order book deep learning.
- Training a 7B+ LLM locally.
- Real-time sentiment on the full X firehose.
- 1-second scalping on 50 venues.

---

## 11. Conclusions and go/no-go

### Go if:
- You can commit 10–15 hours/week for 6 months.
- You have risk capital you can afford to lose.
- You are willing to paper trade for 2–3 months before real money.
- You accept a net Sharpe of ~0.5–1.0 as a good outcome.
- You will follow a written validation protocol and kill bad strategies.

### No-go if:
- You need income next month.
- You want a "set and forget" bot with no monitoring.
- You are not willing to learn data hygiene and risk management.
- You plan to use leverage before proving an edge.
- You cannot tolerate 30–50% drawdowns.

### The one-sentence plan

> Build a boring, well-tested research platform; trade two or three simple, economically motivated strategies with tight risk control; use AI to improve research and features, not to replace judgment; and let prospective out-of-sample results — not backtests — decide what survives.
