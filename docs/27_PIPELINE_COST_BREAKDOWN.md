# 27 — Current Pipeline Cost Breakdown

**Calculated:** 24 Oct 2026  
**Basis:** actual token usage from the latest single-Jev and seven-agent squad reports, the repository's configured trading costs, and current free-tier infrastructure.  
**Currency:** USD unless stated otherwise.

This is an engineering cost estimate, not an accounting statement. Vendor prices and electricity tariffs can change.

---

## 1. Bottom line

### What the current paper pipeline actually costs in cash

| Item | Monthly | Annual | Notes |
|---|---:|---:|---|
| Jev API | **~$0.06** | **~$0.76** | One single-Jev call + one six-agent squad cycle per day |
| Binance data | **$0** | **$0** | Public klines / data API |
| FRED / Yahoo / Alpaca data | **$0** | **$0** | Free tiers |
| Vercel lite dashboard | **$0** | **$0** | Hobby deployment |
| Local Streamlit dashboard | **$0** | **$0** | Runs on the existing PC |
| Broker / exchange | **$0** | **$0** | Paper only |
| **Cash outlay, excluding electricity** | **~$0.06** | **~$0.76** | The only recurring paid API is Jev |

Electricity depends on whether the PC was already running. The bot itself uses
only minutes of compute per day; keeping a PC on 24/7 solely for this project
would cost more than the API.

### The 56-day paper evidence window

| Item | Cost |
|---|---:|
| Jev for 56 days | **~$0.12** |
| Data | $0 |
| Vercel | $0 |
| Paper trading | $0 cash |
| Electricity | depends on the PC |

The evidence window is not expensive in API terms. The expensive part is time
and, if it ever goes live, trading costs.

---

## 2. Jev token cost

### Actual latest usage

| Pipeline | Input tokens | Output tokens | Frequency | Calls |
|---|---:|---:|---|---:|
| Single-Jev AI | 5,186 | 284 | once/day | 1 |
| Seven-agent squad | 44,467 | 1,629 | once/day | 6 |
| **Total** | **49,653** | **1,913** | **once/day** | **7** |

The squad made six Jev calls because the sentiment feed is absent. If a
sentiment file exists, it makes seven calls. The intraday quant lane does not
call Jev at all.

### Price assumption

The repository records the vendor rate as:

- **$42 per billion input tokens**
- **$0.042 per million input tokens**
- **output currently free**

### Calculation

```text
input cost = input_tokens × 42 / 1,000,000,000
```

| Pipeline | Daily | Monthly (30d) | Annual (365d) |
|---|---:|---:|---:|
| Single-Jev AI | $0.000218 | $0.0065 | $0.0795 |
| Seven-agent squad | $0.001868 | $0.0560 | $0.6818 |
| **Total** | **$0.002085** | **$0.0626** | **$0.7612** |

The 56-day window costs:

```text
$0.002085 × 56 = $0.1168
```

If output tokens become billable at a similar rate, the cost would still be
fractions of a cent per day.

The squad is about **8.6×** the single-Jev token cost because six role-scoped
calls each carry the market context and the prior memos. It is still less than
**one cent per day**.

---

## 3. Data and AI feed costs

| Source | Current cost | Needed? | Notes |
|---|---:|---|---|
| Binance public klines | **$0** | Yes | Daily and 1h crypto bars |
| FRED | **$0** | Optional | Free API key; no current macro file |
| Yahoo Finance | **$0** | Optional | US equity research |
| Alpaca market data | **$0** | Optional | Free tier; live keys not configured |
| Sentiment file | **$0** | Optional | Currently absent; agent abstains |
| X / Twitter API | **$0 now** | No | Would be $75-300+/month if added |
| Tiingo / premium data | **$0 now** | No | Would be $30+/month |
| Alpaca Plus | **$0 now** | No | Would be $99/month |

There is **no paid sentiment feed, no X scraping service, and no paid signal
service** in the current pipeline.

---

## 4. Infrastructure and developer tooling

| Item | Current cost | Notes |
|---|---:|---|
| Existing Windows PC | **$0 incremental** | Already available; no new hardware purchased |
| Python / uv / open-source packages | **$0** | Open-source stack |
| Blender / MCP | **$0** | Optional asset creation |
| Vercel Hobby | **$0** | Lite FastAPI status page |
| Streamlit local | **$0** | Local dashboard |
| Streamlit Community Cloud | **$0** | Optional always-on hosting |
| Render Starter | **~$7/month** | Optional if a persistent Streamlit host is needed |
| Small VPS | **~$5-20/month** | Optional if the bot must run off-machine |
| Vercel Pro | **~$20/month** | Only if Hobby limits are insufficient |

The current deployment does not require a VPS because the scheduled tasks run on
the local Windows machine.

---

## 5. Electricity

At **100 W average**, 24/7:

```text
100 W × 730 h/month = 73 kWh/month
73 kWh × $0.15/kWh = $10.95/month
73 kWh × S$0.30/kWh = S$21.90/month
```

But the intraday task runs for roughly **20 seconds per hour**:

```text
24 × 20 seconds = 8 minutes/day
8 minutes/day × 30 = 4 hours/month
100 W × 4 h = 0.4 kWh/month
0.4 kWh × $0.15 = ~$0.06/month
```

The daily tasks add a few more minutes. So:

- **If the PC is already on 24/7:** incremental bot electricity is only cents per month.
- **If the PC must stay on only for the bot:** budget roughly $5-22/month,
  depending on average watts and the local tariff.
- **If the PC sleeps between tasks:** the hourly task cannot run while asleep.

---

## 6. Simulated paper trading costs

The paper broker charges:

- **10 bps commission**
- **5 bps slippage**

per side, for a modeled **15 bps per side** and **30 bps round trip**.

### Concrete examples

| Trade | Commission | Slippage | Total |
|---|---:|---:|---:|
| $1,000 crypto, one side | $1.00 | $0.50 | **$1.50** |
| $10,000 crypto, one side | $10.00 | $5.00 | **$15.00** |
| $10,000 crypto, round trip | $20.00 | $10.00 | **$30.00** |
| $2,000 BNB buy (actual paper order) | $2.00 | $1.00 | **$3.00** |

The intraday account bought about $2,000 of BNB; equity moved from $10,000.00
to $9,997.00. That $3.00 is a **simulated cost**, not a real cash payment.

### Daily strategy turnover costs

From the repository's backtests, at 15 bps per side:

| Strategy | Annual turnover | Estimated annual cost on $10k |
|---|---:|---:|
| Trend | 3.85× | **~$58** |
| XSMOM | 16.43× | **~$246** |
| Breakout | 4.23× | **~$63** |
| Reversal | 20.19× | **~$303** |
| Meta | 3.89× | **~$58** |
| Meta walk-forward | 4.83× | **~$72** |

These are separate paper accounts; do not add them as if they were one $10k
portfolio. The **meta** account is the consolidated portfolio and is the relevant
estimate for a single $10k account: roughly **0.6-0.7% per year** in modeled
trading costs, before taxes and market impact.

### Intraday turnover risk

The formula is:

```text
annual cost % = annual turnover multiple × 15 / 100
```

For the hourly lane, if an average percentage of the portfolio is traded every
hour:

| Average traded per hour | Annual turnover | Estimated annual cost |
|---:|---:|---:|
| 1% | 87.6× | **13.1%** |
| 2% | 175.2× | **26.3%** |
| 5% | 438× | **65.7%** |
| 10% | 876× | **131.4%** |
| 20% | 1,752× | **262.8%** |

This is why the hourly lane is paper-only. The 2% no-trade band reduces churn,
but the actual turnover is not yet known. It must be measured over at least
20-56 days. The intraday lane's first few cycles are not enough evidence.

---

## 7. What would make it more expensive

| Change | New cost |
|---|---:|
| X/Twitter API for sentiment | +$75-300/month |
| Alpaca Plus / full SIP | +$99/month |
| Tiingo or premium prices | +$30+/month |
| Dedicated VPS | +$5-20/month |
| Vercel Pro | +$20/month |
| Hourly AI squad instead of hourly quant | about 24× the current Jev token cost |
| 15-minute intraday instead of 1h | more data, more turnover, more API traffic |
| Live crypto at 25 bps taker + spread | round trip can exceed 50 bps |
| Higher live capital | trading costs scale with notional |

The largest potential cost is not the LLM or the data. It is **turnover**,
slippage, adverse selection, and taxes.

---

## 8. Projected $10k live budget

This is a planning range, not a recommendation to go live.

| Item | Monthly |
|---|---:|
| Jev single + squad | ~$0.06 |
| Data | $0 |
| Vercel Hobby | $0 |
| Electricity (PC already on) | ~$0-2 |
| Daily meta trading costs at 0.6-0.7%/yr | ~$5-6 |
| Optional persistent dashboard/VPS | $0-20 |
| **Estimated total** | **~$5-28/month** |

Excluded:

- taxes;
- capital losses;
- market impact in stress;
- exchange withdrawal/network fees;
- accounting/tax software;
- your time.

The intraday lane is not in this budget because its turnover and net-of-cost
performance are not yet validated. If it trades even 2% of the portfolio every
hour, the modeled annual cost is **26%+ of capital**, which would overwhelm most
crypto edges.

---

## 9. Cost as a percentage of capital

At **$10,000**:

| Cost | Annual | % of capital |
|---|---:|---:|
| Jev | ~$0.76 | 0.008% |
| Vercel | $0 | 0% |
| Electricity, PC already on | ~$0-24 | 0-0.24% |
| Daily meta trading costs | ~$58-72 | 0.58-0.72% |
| Intraday trading costs | unknown | potentially very high |

At this account size, **free data and low turnover matter far more than saving
fractions of a cent on Jev**.

---

## 10. Practical budget rule

1. Keep data at **$0** until a validated strategy specifically needs paid data.
2. Keep the AI API at **under $1/month** at the current daily cadence.
3. Do not add X, Tiingo, Alpaca Plus, or a VPS before the paper evidence passes.
4. Treat **turnover × cost per side** as the real budget line.
5. Do not enable intraday live trading until the paper turnover and net Sharpe
   are measured after costs.
6. Keep total data/infra spend below **2-5% of capital**; at $10k that is
   **$200-500/year**. The current paper stack is far below that.

The current paper pipeline costs roughly **$0.76/year in Jev API fees**, plus
electricity. The 56-day AI evidence window costs about **$0.12** in Jev tokens.
