# 03 — Data Sources, APIs, Costs, and Point-in-Time Discipline

**Research date:** 22 October 2026  
**Principle:** data quality and timing matter more than model sophistication. A mediocre strategy on clean PIT data beats a brilliant strategy on leaked data.

---

## 1. Data requirements matrix

| Data | Assets | Frequency | Minimum history | Why |
|---|---|---|---|---|
| OHLCV bars | Stocks, ETFs, crypto | 1m/1h/1d | 5–10 years | Signals, execution simulation |
| Corporate actions | Stocks/ETFs | Event | 10+ years | Adjusted returns, splits/dividends |
| Universe membership | Stocks, crypto | Point-in-time | 10+ years | Avoid survivorship bias |
| Fundamentals | Stocks | Quarterly | 10+ years | Value/quality factors |
| Earnings/guidance | Stocks | Event | 5+ years | Event strategies |
| Short interest/borrow | Stocks | Bi-weekly/daily | 5+ years | Short strategies, costs |
| Funding/basis/OI | Crypto perps/futures | 8h/1h | 5+ years | Carry, crowding, liquidation |
| On-chain metrics | Crypto | Daily/hourly | 5+ years | Adoption/flow features |
| Macro series | Global | Daily/monthly | 30+ years | Regime/risk overlay |
| Economic calendar | Global | Event | 5+ years | Event risk, release timing |
| News | Stocks/crypto | Event | 5+ years | Event detection, sentiment |
| Social sentiment | Stocks/crypto | Event | 2+ years (or forward) | Attention/overlay |
| Order book/L2 | Crypto/stocks | Tick | 1–2 years | Microstructure (optional) |

---

## 2. US equities and ETFs

### 2.1 Alpaca (recommended for retail US stocks)

**Products:** Trading API, Market Data API, crypto, options, paper trading.

**Market data pricing (verified Oct 2026):**

| Plan | Price | Real-time | API limit | Coverage | History |
|---|---|---|---|---|---|
| Free | $0/mo | WebSocket real-time (IEX); REST 15-min delayed | 200 calls/min | IEX only | 7+ years |
| Algo Trader Plus | $99/mo | Real-time, all US exchanges | Unlimited | 100% market | 7+ years |

- Crypto data included on both plans (20+ assets, 56 pairs).
- Paper trading is free and uses the same API.
- Commission-free US stocks/ETFs; crypto fees 15/25 bps maker/taker at tier 1.
- Crypto cannot be bought on margin or sold short on Alpaca.
- Max crypto order notional: $200k per order (as documented).

**Pros:** easiest API, good docs, `alpaca-py`, paper trading, free tier sufficient for daily strategies.
**Cons:** free REST data is 15-min delayed and IEX-only; full SIP requires $99/mo; crypto product is limited.

**Use for:** US stock/ETF trading, paper trading, daily/hourly bars, corporate actions.

### 2.2 Interactive Brokers (IBKR)

**Market data (verified Oct 2026):**
- Free real-time **non-consolidated** streaming for US-listed stocks/ETFs from Cboe One and IEX.
- **US Securities Snapshot and Futures Value Bundle:** $10/mo base, waived if monthly commissions ≥ $30; $0.01/snapshot.
- **US Equity and Options Add-On Streaming Bundle:** $4.50/mo non-professional.
- Individual exchange feeds (NYSE, NASDAQ, ARCA, etc.) $1.50–$25/mo each.
- Free delayed data for many non-US products.

**Commissions (US stocks):**
- IBKR Pro Tiered: $0.0035/share (≤300k shares/mo), $0.0020 above; min $0.35/order.
- IBKR Pro Fixed: $0.005/share; min $1.00/order.
- IBKR Lite: $0.002/share, $0 minimum (US residents only).
- Regulatory/exchange fees pass through.

**Pros:** broadest product coverage; one account for stocks, ETFs, options, futures, FX, bonds; professional execution; paper account.
**Cons:** TWS/IB Gateway required; API complexity; market data subscriptions; minimum equity for some data; not ideal for beginners.

**Use for:** multi-asset futures/options, professional execution, if you outgrow Alpaca.

### 2.3 Tiingo

**Pricing (verified Oct 2026):**

| Plan | Price | Requests | Coverage | Notes |
|---|---|---|---|---|
| Starter | $0/mo | 50/hr, 1,000/day, 500 symbols/mo | 110k global securities | EOD, crypto, IEX, news (3 months) |
| Power | $30/mo | 10,000/hr, 100,000/day, 110k symbols | Same | 15 years fundamentals, 40 GB/mo |

- EOD history 30+ years.
- News API includes 3 months of queryable history (longer for commercial).
- Crypto and IEX firehose included.
- Internal-use license only; no redistribution.

**Use for:** cheap EOD + news + crypto; good value for a solo researcher.

### 2.4 EODHD

**Pricing (verified Oct 2026):**
- Free: 20 API calls/day, 1 year history.
- Historian (EOD all-world): $19.99/mo.
- Active Trader (EOD + intraday): $29.99/mo.
- Fundamentals: $59.99/mo.
- All-in-One: $99.99/mo.
- 100,000 API calls/day; 1,000 req/min; 30+ years EOD; intraday US from 2004.
- Includes news, sentiment, macro, treasury, insider transactions, congressional trades on higher tiers.
- Tick data add-on from $9.99/mo; options add-on $29.99/mo.

**Pros:** excellent breadth/price; global; fundamentals + news + macro.
**Cons:** data quality varies by market; not exchange-grade for every field; verify against a primary source.

**Use for:** global equities, fundamentals, macro, news, a second opinion on prices.

### 2.5 Massive (formerly Polygon.io)

- Premium US stocks/options/indices/futures data.
- Pricing is plan-based and changes; budget roughly **$30–200+/mo** depending on asset class, history, and real-time access. Verify current plans before purchase.
- Partner datasets (Benzinga news, TMX, ETF Global) ~$99/mo each.
- High-quality aggregates and trades; good docs.

**Use for:** production-grade US market data if Alpaca/Tiingo is insufficient.

### 2.6 Norgate Data / Sharadar (survivorship-bias-free fundamentals)

- **Norgate**: survivorship-bias-free US stock data, delisted securities, index membership, fundamentals. Roughly **$30–70/mo** depending on plan; verify.
- **Sharadar** via Nasdaq Data Link: fundamentals, prices, insider/institutional data; roughly **$50–100/mo**; verify.
- These are the practical retail options for **point-in-time universe + delisted stocks**, which are essential for credible equity backtests.

**Use for:** serious US equity factor research. Without delisted stocks and PIT membership, your backtest is inflated.

### 2.7 SEC EDGAR (free)

- Company filings: 10-K, 10-Q, 8-K, Form 4, 13F, S-1, etc.
- XBRL company facts API: `https://data.sec.gov/api/xbrl/companyfacts/`.
- Full-text search: `https://efts.sec.gov/LATEST/search-index?q=...`.
- Rate limit: ~10 requests/sec; set a descriptive `User-Agent`.
- Point-in-time: use **filing date/time**, not period end. Restatements create new vintages.

**Use for:** fundamentals, insider transactions, filings, event detection.

### 2.8 FINRA (free)

- Short interest data (bi-monthly).
- Reg SHO daily short sale volume.
- TRACE bond data (some public).
- Use for short crowding/borrow risk.

### 2.9 Other useful free sources

| Source | Data |
|---|---|
| FRED/ALFRED | Macro, rates, credit spreads, liquidity |
| BLS API | CPI, PPI, employment, wages |
| BEA API | GDP, PCE, income |
| EIA API | Energy inventories, production |
| US Treasury FiscalData | Debt, TGA, auctions, yields |
| NY Fed Markets API | SOFR, repo, references |
| CBOE | VIX and options data (some free) |
| Nasdaq Data Link | Many free/paid datasets |
| Yahoo Finance (`yfinance`) | Prototyping only; unofficial, no SLA, survivorship issues |

---

## 3. Crypto

### 3.1 Binance public data (best free historical source)

- `https://data.binance.vision/`
- Free daily/monthly ZIPs for spot and futures.
- Klines, aggTrades, trades, funding rates, open interest, liquidation snapshots (varies).
- All symbols; 1s to 1mo intervals.
- **Timestamp note:** spot timestamps are microseconds from 1 Jan 2025 onward; older data may be milliseconds. Normalize.
- Terms: check Binance's data terms; not for redistribution.

**Use for:** historical crypto bars/trades/funding; the backbone of free crypto research.

### 3.2 Exchange APIs via ccxt

- Unified API for 100+ exchanges.
- REST + WebSocket; rate limits and auth handled per exchange.
- Use for live data and execution: Binance, Bybit, OKX, Kraken, Coinbase, Hyperliquid, etc.
- **Jurisdiction matters:** Binance.com is not available to US persons; use Kraken/Coinbase/Alpaca or Binance.US.
- **Counterparty risk:** don't keep more capital on an exchange than necessary.

### 3.3 Market data / analytics

| Source | Free tier | Paid | Use |
|---|---|---|---|
| **CoinGecko** | Yes, ~30 calls/min, 10k/month | Yes | Market caps, metadata, dominance |
| **Coin Metrics Community** | Yes | Yes | On-chain/market metrics |
| **DefiLlama** | Yes | No (donations) | TVL, stablecoin supply, yields |
| **Glassnode** | Limited | Yes | On-chain metrics |
| **CryptoQuant** | Limited | Yes | Exchange flows, miner data |
| **Kaiko** | No | Yes (expensive) | Institutional market data |
| **Tardis.dev** | No | Yes | Historical L2/trades; Nautilus adapter |
| **Databento** | Usage-based | Yes | Institutional crypto/equities data |
| **CoinAPI** | Limited | Yes | Normalized multi-exchange data |

**Recommendation:** start with Binance Vision + ccxt + CoinGecko + DefiLlama. Add paid data only when a strategy specifically needs it.

### 3.4 Crypto data traps

- **Wash trading:** Cong et al. (2022) find >70% of reported volume on unregulated exchanges may be fake. Use regulated venues for volume/liquidity signals.
- **Survivorship:** dead coins, delisted pairs, exchange failures. Keep a PIT universe.
- **Stablecoin depegs:** USDC 2023, UST 2022. Treat stablecoins as risky.
- **Exchange outages:** APIs fail during volatility; have fallbacks.
- **Funding timestamp:** 8h intervals vary by venue; align to the exact funding time.
- **Chain reorgs:** on-chain data can change; use finalized blocks.
- **Symbol changes:** rebrands and migrations; maintain a mapping table.
- **Liquidation data:** incomplete and venue-specific.

---

## 4. Macro data

### 4.1 FRED / ALFRED (free, essential)

- FRED: latest revised data.
- ALFRED: **vintages** — data as it was known at each point in time.
- API key required; free.
- Use `fred/series/observations` with `realtime_start`/`realtime_end` for vintages.
- Release calendar: `fred/releases/dates`.

**Rule:** for backtests, always use ALFRED vintages for revised series (GDP, CPI, employment, etc.). Using the latest revision is look-ahead.

### 4.2 Other official sources

| Source | Data | API |
|---|---|---|
| BLS | CPI, PPI, employment, wages | `api.bls.gov` (v2, key, 500 queries/day) |
| BEA | GDP, PCE, income | `apps.bea.gov/api` |
| EIA | Energy | `api.eia.gov` |
| US Treasury | Debt, TGA, auctions, yields | `fiscaldata.treasury.gov` |
| NY Fed | SOFR, repo | `markets.newyorkfed.org/api` |
| Census | Retail sales, housing | `api.census.gov` |
| ECB / BoE / BoJ | Policy rates, balance sheets | Various |

### 4.3 Economic calendar

- FRED release dates are free and reliable for US series.
- Finnhub, FMP, Trading Economics, and EODHD offer calendars (free/paid).
- Store **release timestamp** and **actual/consensus/previous**.
- Do not trade on a release using data timestamped at period end; use the release time.

### 4.4 Macro feature checklist

- Policy rate level and 3-month change.
- 2y/10y yields, curve slope, real yields.
- Inflation level, surprise, and trend.
- Unemployment, payrolls, claims.
- PMI/ISM (if licensed).
- HY/IG credit spreads.
- VIX level, percentile, term structure.
- DXY trend.
- Central bank balance sheet, reverse repo, TGA.
- Commodities (oil, gold, copper).
- Crypto: stablecoin supply, BTC dominance, ETF flows.

---

## 5. News and sentiment

### 5.1 X (Twitter) API — pay-per-use (verified Oct 2026)

| Item | Cost / limit |
|---|---|
| Post read | **$0.005 per post** |
| User read | $0.010 per user |
| DM event read | $0.010 |
| Post create | $0.015 (with URL $0.200) |
| Recent search | Last 7 days, all developers |
| Full-archive search | Back to 2006, pay-per-use/Enterprise |
| Monthly cap | **3 million post reads** on pay-per-use |
| Dedup | Same resource within 24h charged once |
| Free credits | $20 first purchase + auto-recharge match up to $50 |

**Budget examples:**
- 500 posts/day = 15k/month ≈ **$75/mo**.
- 2,000 posts/day = 60k/month ≈ **$300/mo**.
- 1M historical posts ≈ **$5,000**.

**Strategy:** don't ingest the firehose. Build a focused list of accounts, cashtags, and keywords; sample; cache; dedupe. Use full-archive only for backtesting a specific hypothesis.

### 5.2 Reddit

- Free tier: **100 queries/minute per OAuth client ID**, non-commercial.
- Commercial: reported **$0.24 per 1,000 calls**, with a ~$12k/month minimum (verify current terms).
- Good for retail sentiment, but noisy, bot-infested, and US-centric.
- Respect API terms; no redistribution.

### 5.3 Bluesky / AT Protocol

- Free public firehose and API.
- Smaller finance community than X, but growing.
- Open protocol; easier data access.
- Good for forward-collected sentiment; historical coverage is limited.

### 5.4 GDELT

- Free, 100% open.
- Global news events, 15-minute updates.
- 2.5 TB/year raw; BigQuery access.
- GKG includes themes, entities, sentiment, counts.
- Great for macro/geopolitical event detection; not a substitute for market-specific news.

### 5.5 News APIs

| Provider | Price | Coverage | Notes |
|---|---|---|---|
| Tiingo News | Included in $30/mo | 3 months history | Clean, timestamped |
| EODHD News | Included in $29.99+ | Global | Sentiment/word weights |
| Finnhub | Free tier + paid | Company news, earnings | Check current limits |
| Benzinga via Massive | $99/mo | Real-time news, ratings | Premium |
| GDELT | Free | Global events | Not company-specific |
| CryptoPanic | Free tier | Crypto news | Aggregator |
| Marketaux | Free/paid | News + sentiment | Good for prototyping |

### 5.6 Alternative attention data

- **Google Trends** via `pytrends` (unofficial; rate-limited).
- **Wikipedia pageviews** (free API).
- **App download rankings** (paid).
- **Fear & Greed Index** (`alternative.me`) — free, daily.
- **StockTwits** — historically free API; access has changed; verify before relying.
- **Telegram/Discord** — public channels; ToS and privacy constraints.

### 5.7 Sentiment licensing

- X: display/redistribution restrictions; check developer terms.
- Reddit: no redistribution without agreement.
- News: copyright; store derived features, not full text, where possible.
- If you publish results or sell a product, review every vendor's terms.

---

## 6. Point-in-time (PIT) data protocol

### 6.1 The schema

Every observation should have:

```text
asset_id          # stable internal ID, not ticker
field             # e.g., close, revenue, sentiment
value
event_time_utc    # when it happened
knowledge_time_utc# when you could first know it
source
vintage           # for revised data
ingested_at_utc
```

### 6.2 Rules by data type

| Data | event_time | knowledge_time |
|---|---|---|
| Daily bar | Session close | Close + vendor latency (e.g., 1 min) |
| Intraday bar | Bar close | Bar close + latency |
| Trade/quote | Timestamp | Timestamp + feed latency |
| Fundamental | Period end | **Filing date/time** (not period end) |
| Earnings | Fiscal period end | **Release date/time** |
| Macro | Observation date | **Release date/time** + vintage |
| News | Publication time | Ingest time (max of publication/ingest) |
| Social post | Created time | First observed time |
| Corporate action | Effective date | Announcement date |

### 6.3 Joins

```sql
-- Correct: only use data known by decision time
SELECT ...
FROM features f
JOIN prices p
  ON p.asset_id = f.asset_id
 AND p.knowledge_time_utc <= f.decision_time_utc
```

Never join on `event_time <= decision_time` alone for revised data.

### 6.4 Universe construction

- **Stocks:** PIT index membership, listing/delisting dates, liquidity filters at each rebalance.
- **Crypto:** PIT top-N by volume/market cap, exclude stablecoins/wrapped/leveraged tokens, include delisted assets, require minimum history.
- **Survivorship:** keep a `delisted_at` field and delisting returns.
- **Symbol changes:** map old → new; don't lose history.

### 6.5 Corporate actions

- Use **adjusted prices** for return calculations.
- Use **unadjusted prices** for order simulation and share counts.
- Handle splits, dividends, mergers, spinoffs, delistings.
- Verify against a second source for large moves.

### 6.6 Time zones and calendars

- Store everything in UTC.
- Use `exchange-calendars` / `pandas-market-calendars` for sessions and holidays.
- Crypto trades 24/7; define your "daily bar" boundary (UTC midnight is standard, but some venues use different).
- Handle DST transitions in macro release times and market hours.

---

## 7. Data quality checklist

Before any backtest:

- [ ] No duplicate `(asset_id, event_time)` rows.
- [ ] OHLC consistency: `low <= min(open, close) <= max(open, close) <= high`.
- [ ] No zero/negative prices; no absurd returns (>50% daily for large caps).
- [ ] Missing sessions accounted for (holidays, outages).
- [ ] Corporate actions reconciled with a second source.
- [ ] Delisted assets included; delisting returns applied.
- [ ] PIT universe membership verified against an independent source.
- [ ] Fundamentals use filing dates, not period ends.
- [ ] Macro uses ALFRED vintages.
- [ ] News/social timestamps are UTC and available before decision time.
- [ ] Crypto volume filtered for wash trading/weak venues.
- [ ] Funding timestamps aligned to venue schedule.
- [ ] Stablecoin depegs and exchange failures flagged.
- [ ] Data checksums recorded and versioned.

---

## 8. Cost budget

### 8.1 Starter (paper trading, first 3 months)

| Item | Cost |
|---|---|
| Alpaca Free | $0 |
| Binance Vision / ccxt | $0 |
| FRED/ALFRED, SEC, GDELT, Reddit free, Bluesky | $0 |
| CoinGecko/DefiLlama | $0 |
| Tiingo Power (optional) | $30/mo |
| **Total** | **$0–30/mo** |

### 8.2 Serious research/live

| Item | Cost |
|---|---|
| Alpaca Algo Trader Plus | $99/mo |
| Tiingo Power | $30/mo |
| EODHD All-in-One (optional) | $99.99/mo |
| X API credits (focused) | $50–300/mo |
| VPS/backup | $10–30/mo |
| Surge/News add-ons (optional) | $50–100/mo |
| **Total** | **$150–450/mo** |

### 8.3 One-time / hardware

| Item | Cost |
|---|---|
| UPS (recommended) | $100–200 |
| External backup drive | $80–150 |
| Books/courses | $0–200 (optional; not required) |
| **Total** | **$180–550** |

### 8.4 Trading costs to model

| Asset | Cost |
|---|---|
| US stocks (Alpaca) | $0 commission + spread + slippage |
| US stocks (IBKR) | $0.0035–0.005/share; min $0.35–1.00 |
| Crypto (Alpaca) | 15/25 bps maker/taker tier 1 |
| Crypto (Kraken/Coinbase) | ~10–40 bps depending on tier/product |
| Crypto perps | 2–10 bps + funding |
| Short borrow | 0.3–50%+ annualized depending on name |
| Taxes | Short-term gains; country-specific |

**Rule:** if a strategy's edge disappears at 2× your assumed costs, don't trade it.

---

## 9. Recommended data plan by phase

### Phase 0–1 (weeks 1–4)
- Binance Vision: BTC/ETH + top 30 coins, 1d + 1h.
- Alpaca free: SPY/QQQ + 100 liquid stocks, 1d.
- FRED/ALFRED: core macro series.
- CoinGecko/DefiLlama: metadata, stablecoin supply.
- Total: **$0**.

### Phase 2 (weeks 4–8)
- Add Tiingo ($30) for news and a second price source.
- Add delisted crypto pairs and funding history.
- Add SEC EDGAR fundamentals for a small equity universe.
- Total: **$30/mo**.

### Phase 3–4 (weeks 8–20)
- Alpaca Plus ($99) if intraday or full-market coverage is needed.
- X API credits if the sentiment hypothesis is worth testing.
- Norgate/Sharadar if doing serious equity factors.
- Total: **$100–300/mo**.

### Phase 5 (weeks 20–26)
- Add only the data a validated strategy requires.
- Avoid building a data lake for its own sake.

---

## 10. Licensing and legal notes

- **Personal use vs redistribution:** most vendors (Alpaca, Tiingo, EODHD, X, Reddit) allow personal/internal use but restrict redistribution or commercial display. Read the terms.
- **Professional market data:** if you are registered as an investment adviser or use data for business, exchanges may classify you as professional and charge more.
- **Crypto exchange terms:** API use, market data, and order execution are subject to venue terms; some prohibit certain automated strategies.
- **Tax:** trading is taxable; short-term gains, wash sales (US stocks), crypto property rules, foreign account reporting. Keep a full trade log.
- **Privacy:** social data may contain personal information; GDPR/CCPA may apply if you store it at scale.
- **No redistribution:** don't publish raw vendor data or derived datasets that substitute for the vendor's product.

### 10.1 US-specific checklist (2026)

- **Intraday margin:** FINRA's new intraday margin standards replaced the old pattern-day-trader rule and $25,000 minimum, effective 4 June 2026 (phase-in through 20 October 2027). Brokers may still impose house requirements. Confirm with your broker before any intraday strategy.
- **Wash sales:** apply to US securities; frequent rebalancing can create disallowed losses. Crypto tax treatment differs and is evolving.
- **Short-term gains:** held <1 year are taxed as ordinary income in the US; this can materially reduce net returns.
- **Crypto:** treated as property for US federal tax; report disposals; track basis and fees.
- **Broker reports:** 1099-B, 1099-DA (digital assets, as applicable), consolidated statements.
- **Foreign accounts:** FBAR/Form 8938 thresholds may apply if using offshore exchanges.
- **State tax:** may apply in addition to federal.
- **Recordkeeping:** keep an append-only trade log with timestamps, fees, and transfer history.

**This is not legal or tax advice. Verify with a professional in your jurisdiction.**

---

## 11. Data source summary table

| Need | Best free | Best value paid | Premium |
|---|---|---|---|
| US stock bars | Alpaca free (IEX, delayed) | Tiingo $30 / EODHD $29.99 | Massive, Databento |
| US fundamentals | SEC EDGAR | EODHD $59.99 | Sharadar, Norgate |
| US universe/delisted | — | Norgate/Sharadar | CRSP/Compustat |
| Crypto bars | Binance Vision | — | Kaiko, Tardis, Databento |
| Crypto funding/OI | Binance/Bybit APIs | — | Glassnode, CryptoQuant |
| Crypto on-chain | DefiLlama, Coin Metrics | Glassnode/CryptoQuant | Kaiko |
| Macro | FRED/ALFRED, BLS, BEA | EODHD | Bloomberg/Refinitiv |
| News | GDELT | Tiingo/EODHD | Benzinga |
| Social | Reddit free, Bluesky, GDELT | X API credits | X Enterprise |
| Order book | Exchange APIs | Tardis | Databento/Kaiko |

**Final advice:** start free. Upgrade only when a specific, validated strategy requires a specific dataset. Data costs are a tax on research; don't pay them before you have a hypothesis.
