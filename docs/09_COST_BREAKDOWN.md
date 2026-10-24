# 09 - Running Cost Breakdown

**Date:** 22 October 2026  
**Current implemented pipeline:** see `docs/27_PIPELINE_COST_BREAKDOWN.md` for actual Jev usage and the current paper-stack cost.
**Assumption:** US resident, existing PC, paper first, then small live. Prices verified from provider pages where noted; estimates are labeled.

---

## 1. The short version

| Stage | What you need | Monthly data/infra | Annual data/infra | Annual trading costs | Annual all-in (ex-tax) |
|---|---|---:|---:|---:|---:|
| **Research / paper** (months 1–3) | Free Alpaca data, Binance Vision, FRED, SEC, GDELT | **$10–70** | **$120–840** | $0 | **$120–840** |
| **Small live, $10k, daily** | Tiingo, optional Alpaca Plus, VPS/backup, electricity | **$45–179** | **$540–2,150** | $100–500 | **$640–2,650** |
| **$25k + sentiment/AI** | Alpaca Plus, Tiingo, X API, LLM, infra | **$254–599** | **$3,050–7,190** | $500–1,500 | **$3,550–8,690** |
| **$100k multi-strategy** | Premium data, X, multiple venues, monitoring | **$529–989** | **$6,350–11,870** | $2,000–6,000 | **$8,350–17,870** |

**Excludes:** taxes, trading losses, and your time. Taxes can be larger than every other line item for a high-turnover strategy.

**Rule of thumb:** keep total annual data/infra spend below **2–5% of trading capital**. At $10k, that is **$200–500/year** — so stay on free/cheap data. At $100k, **$2k–5k/year** is reasonable.

---

## 2. One-time setup

| Item | Cost | Needed? | Notes |
|---|---:|---|---|
| Existing PC | $0 | Yes | Already sufficient |
| UPS | $100–200 | Strongly recommended | Prevents power-loss corruption/outages |
| External backup drive | $80–150 | Recommended | Encrypted backups of data/order journal |
| Fresh SSD (optional) | $80–150 | Optional | Keeps data separate from OS |
| Always-on mini PC (optional) | $300–600 | Optional | Lower power than the main PC |
| **Total** | **$180–350** | | Or **$0** if you already have UPS/backup |

No paid software is required. Python, DuckDB, Polars, MLflow, Optuna, and the research stack are free/open source.

---

## 3. Monthly data and API costs

### Tier 0 — Research / paper (recommended first 3 months)

| Item | Cost/month | Notes |
|---|---:|---|
| Alpaca Free | $0 | IEX, 15-min delayed REST, paper trading |
| Binance Vision | $0 | Historical crypto bars/trades/funding |
| FRED / ALFRED | $0 | Macro + vintages |
| SEC EDGAR | $0 | Fundamentals/filings |
| GDELT | $0 | News events |
| Reddit free tier | $0 | 100 QPM, non-commercial |
| Bluesky | $0 | Free API/firehose |
| CoinGecko / DefiLlama | $0 | Metadata/stablecoin/TVL |
| Tiingo Power (optional) | $30 | News + EOD + crypto + IEX |
| Backup/electricity | $10–40 | See §7 |
| **Total** | **$10–70** | **$120–840/year** |

### Tier 1 — Small live ($10k), daily strategies, no sentiment

| Item | Cost/month | Notes |
|---|---:|---|
| Alpaca Free | $0 | Enough for daily bars |
| Alpaca Algo Trader Plus (optional) | $99 | Only if you need full-market real-time/intraday |
| Tiingo Power | $30 | News + second price source |
| VPS or backup | $5–20 | Home PC is fine at first |
| Electricity | $10–30 | See §7 |
| **Total** | **$45–179** | **$540–2,150/year** |

**Recommendation:** skip Alpaca Plus initially. The free IEX feed plus Tiingo EOD is enough for daily/weekly strategies. Upgrade only when intraday/full-SIP is required.

### Tier 2 — $25k + sentiment/AI

| Item | Cost/month | Notes |
|---|---:|---|
| Alpaca Plus | $99 | Full US market, real-time |
| Tiingo Power | $30 | News/prices |
| X API credits | $75–300 | 500–2,000 posts/day at $0.005/post |
| News/alt data | $0–50 | GDELT/Reddit free; optional Marketaux/Finnhub |
| LLM API | $20–50 | Event extraction/research; FinBERT local free |
| VPS/backup/monitoring | $20–40 | Hybrid home + VPS is fine |
| Electricity | $10–30 | See §7 |
| **Total** | **$254–599** | **$3,050–7,200/year** |

### Tier 3 — $100k multi-strategy

| Item | Cost/month | Notes |
|---|---:|---|
| Alpaca Plus | $99 | US equities |
| Tiingo Power | $30 | News/EOD |
| EODHD All-in-One (optional) | $99.99 | Global/fundamentals/macro; overlaps with Tiingo |
| X API credits | $150–300 | 1,000–2,000 posts/day |
| Premium data (Norgate/Sharadar/Glassnode) | $50–200 | Only if a validated strategy needs it |
| VPS + backup + monitoring | $40–80 | Production reliability |
| LLM API | $50–150 | Larger NLP/event workload |
| Electricity | $10–30 | See §7 |
| **Total** | **$529–989** | **$6,350–11,870/year** |

**Do not buy Tier 3 before you have a validated strategy that specifically requires it.** Most of that data will not improve a simple trend/momentum strategy.

---

## 4. Trading costs (the part that kills strategies)

### 4.1 Commissions and fees

| Venue / asset | Cost | Notes |
|---|---|---|
| Alpaca US stocks/ETFs | $0 commission | Regulatory fees ~cents |
| Alpaca crypto | **15 bps maker / 25 bps taker** (tier 1) | Round trip taker ≈ 50 bps |
| IBKR US stocks | **$0.0035–0.005/share** | Min $0.35–1.00/order |
| IBKR Lite | $0.002/share, $0 min | US residents |
| Kraken/Coinbase | ~10–40 bps per side | Tier/product dependent |
| Binance spot | ~10 bps per side | 7.5 bps with BNB; jurisdiction applies |
| Binance/Bybit perps | ~2–10 bps per side + funding | Funding can dominate |

### 4.2 Spread and slippage

| Asset | Typical per-side cost (planning) |
|---|---:|
| Liquid US large-cap | 2–10 bps |
| Small/mid-cap | 10–30 bps |
| BTC/ETH | 2–10 bps |
| Liquid alts | 10–30 bps |
| Thin alts | 30–100+ bps |
| Stress/crash | 2–5× normal |

### 4.3 Cost formula

```text
annual trading cost = annual traded notional / capital × cost_per_side_bps / 10,000 × capital
```

Simplify: **annual cost % = turnover_multiple × cost_per_side_bps / 100**.

Where `turnover_multiple` = total buys + sells over a year ÷ capital.

### 4.4 Examples

| Strategy | Annual traded notional / capital | Cost/side | Annual cost |
|---|---:|---:|---:|
| Monthly rebalance, 20% of portfolio | 4.8× | 10 bps | **0.48%** |
| Weekly rebalance, 50% of portfolio | 52× | 10 bps | **5.2%** |
| Weekly crypto, 50% of portfolio | 52× | 25 bps | **13.0%** |
| Weekly crypto, 20% of portfolio | 20.8× | 25 bps | **5.2%** |
| Daily crypto, 20% of portfolio | 146× | 25 bps | **36.5%** |

**This is why high-turnover crypto strategies fail.** A strategy that looks great at 0 bps can lose 13%+/year at realistic taker fees.

### 4.5 Per-trade examples

| Trade | Commission | Spread/slippage | Total |
|---|---:|---:|---:|
| $1,000 US stock (Alpaca) | $0 | ~$0.50 (5 bps) | **~$0.52** |
| $10,000 US stock (Alpaca) | $0 | ~$5 (5 bps) | **~$5.20** |
| $10,000 US stock (IBKR, 100 sh @ $100) | $0.35–0.50 | ~$5 | **~$5.35–5.50** |
| $10,000 crypto taker (Alpaca 25 bps) | $25 | ~$5–10 | **~$30–35** |
| $10,000 crypto maker (Alpaca 15 bps) | $15 | ~$5 | **~$20** (if filled) |
| $10,000 crypto (Binance 10 bps) | $10 | ~$5 | **~$15** |

### 4.6 Funding and borrow

- **Perp funding:** typically ~0.01% per 8h = **~10.95%/year**, but varies and can be negative.
- **Short borrow:** 0.3–50%+ annualized; hard-to-borrow names can be far worse.
- **Margin interest:** ~4.4%+ at IBKR; higher at retail brokers.
- **FX conversion:** 0.5–3% per conversion at retail.

Model these explicitly; they are not optional.

---

## 5. Taxes (US example)

| Item | Cost |
|---|---|
| Short-term capital gains | Ordinary income: **10–37% federal** + state |
| Long-term capital gains | **0/15/20%** federal + state |
| Net investment income tax | **+3.8%** above thresholds |
| Crypto | Property; every disposal is taxable; track basis/fees |
| Wash sales | Apply to securities; crypto rules evolving |
| Tax software | **$50–200/year** (crypto tracking may cost more) |
| Accountant (optional) | **$300–1,500/year** |

**Example:** $5,000 short-term gain at 24% federal + 5% state = **$1,450 tax**. A high-turnover strategy can generate a large tax bill even if net PnL is modest.

**Taxes are not included in the monthly tables above.** They can easily exceed data/infra costs.

---

## 6. Hidden and often-forgotten costs

| Cost | Typical impact |
|---|---|
| Slippage in stress | 2–5× normal spreads |
| Failed orders/retries | Small direct cost, large opportunity cost |
| API overages | $10–100/month if limits exceeded |
| Exchange withdrawal fees | $1–20 per transfer |
| Stablecoin conversion | 1–10 bps, wider in stress |
| Data licensing/professional status | 2–10× retail market-data fees |
| Cloud egress/storage | $5–50/month if using cloud |
| Cybersecurity incident | Potentially catastrophic |
| Your time | 230–305 hours over 26 weeks |
| Opportunity cost of capital | Benchmarked against T-bills/SPY |
| Strategy failure | 20–50% drawdown is the real "cost" |

---

## 7. Electricity estimate

| Load | kWh/month | Cost at $0.15/kWh |
|---|---:|---:|
| 100 W average | 72 | **$10.80** |
| 150 W average | 108 | **$16.20** |
| 300 W average | 216 | **$32.40** |

A trading bot is mostly idle; 100–150 W average is realistic for this PC. Monitor off, no RGB, and sleep disabled only during market hours.

---

## 8. Cost as % of capital (important)

| Capital | $30/mo | $100/mo | $200/mo | $400/mo |
|---:|---:|---:|---:|---:|
| $5,000 | 7.2% | 24.0% | 48.0% | 96.0% |
| $10,000 | 3.6% | 12.0% | 24.0% | 48.0% |
| $25,000 | 1.4% | 4.8% | 9.6% | 19.2% |
| $50,000 | 0.7% | 2.4% | 4.8% | 9.6% |
| $100,000 | 0.4% | 1.2% | 2.4% | 4.8% |

**Implication:** at $5k–10k, you must keep data costs near zero. A $200/month data stack costs 24% of a $10k account per year — before trading costs and taxes. That is why the free tier matters.

---

## 9. Recommended budget path

### Months 1–3 — research/paper
- **$10–70/month all-in** (data $0–30 + electricity/backup).
- Buy nothing else.
- Use the time to build the data pipeline and validation.

### Months 4–6 — paper + first small live
- **$45–130/month**: Tiingo + backup/VPS + electricity.
- Skip Alpaca Plus unless intraday is essential.
- No X API yet unless a focused sentiment hypothesis is ready.

### Months 7–12 — if a strategy passes
- **$150–300/month**: Alpaca Plus + Tiingo + focused X API + LLM.
- Add premium data only if the strategy specifically needs it.
- Keep total spend <5% of capital.

### Year 2 — scale
- **$300–700/month** at $100k+ capital.
- Add multi-venue execution, monitoring, and accounting support.
- Re-evaluate every data subscription: does it improve a live strategy?

---

## 10. What not to buy

- Paid signal groups, "proven" bots, copy-trading subscriptions.
- vectorbt PRO (open-source vectorbt is enough for personal research).
- Bloomberg/Refinitiv/FactSet (institutional pricing).
- Kaiko/Tardis/Databento tick data before you have a tick-level strategy.
- Cloud GPU/fine-tuning before you have a validated NLP hypothesis.
- Multiple overlapping news APIs (Tiingo + EODHD + Finnhub + Benzinga).
- A VPS before paper trading works reliably.

---

## 11. Bottom line

**Minimum viable budget:** **$10–70/month all-in** including electricity. You can research, backtest, and paper trade for less than a streaming subscription.

**Realistic small-live budget:** **$60–150/month** all-in, excluding taxes and trading losses.

**With sentiment/AI at $25k:** **$250–500/month**.

**The biggest cost is not data — it is a strategy that shouldn't have been deployed.** Spend on validation, not on more subscriptions.
