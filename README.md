# Crypto + US Equities Trading Bot — Deep Research & Build Plan

**Status:** Paper system built; live capital not approved  
**Research date:** 22 October 2026  
**Machine:** Windows 11, Ryzen AI 9 HX 470 (12C/24T), 28 GB RAM, Radeon 890M iGPU, 646 GB free, no NVIDIA GPU, WSL2 Ubuntu available, Python 3.12 + `uv` installed

---

## 1. The short answer

You can absolutely build this yourself, on this PC, with free and low-cost data. But the most important finding is uncomfortable:

> **I could not find a public, free, audited, multi-year retail trading bot with a "proven good record" that you can copy.**
> Nearly every impressive GitHub/YouTube/Telegram track record I reviewed is a backtest, a survivorship-biased universe, a look-ahead signal, a paid signal service, or a short live sample that has not been through a bear market.

What *does* have real, peer-reviewed, long-sample evidence is a small set of **risk premia and behavioral effects**: time-series trend, cross-sectional momentum, carry, value/quality, and low-volatility. Those effects are real on average, but they:
- decay after publication (McLean & Pontiff found ~58% lower returns post-publication),
- get eaten by transaction costs at high turnover,
- have long drawdowns and crash risk,
- and require disciplined execution to capture.

So the correct goal is not "find the magic bot". It is:

> **Build a research and validation machine that can kill bad ideas cheaply, then run 2–3 simple, economically motivated strategies with strict risk control.**

My recommended first build:
1. **Multi-asset time-series trend** (BTC, ETH, SPY/QQQ, TLT, GLD) — simplest, most robust, low turnover.
2. **Crypto cross-sectional momentum** — strong academic support, but crash-prone and cost-sensitive.
3. **Crypto carry/basis** — structural edge, but only after execution and custody are solid.

Then add US equity momentum/quality, news/sentiment, and ML — in that order.

---

## 2. What to build (recommended stack)

| Layer | Choice | Why |
|---|---|---|
| Language | **Python 3.12 + uv** | Best ecosystem; `uv` is fast and reproducible; Nautilus/Freqtrade support it |
| Data storage | **Parquet + DuckDB + Polars** | Cheap, fast, versionable; no database server needed at first |
| Fast research | **Custom vectorized backtester** (Polars/NumPy) | Full control of cross-asset accounting, costs, PIT joins |
| Event-driven validation | **NautilusTrader v1.x** (or v2 when stable) | Backtest/live parity, Rust core, IBKR + crypto adapters |
| Crypto lab / first live | **Freqtrade** | Mature, dry-run, hyperopt, look-ahead analysis, FreqAI, Telegram/UI |
| US stocks execution | **Alpaca** + thin custom executor | Commission-free, paper API, easy; daily/weekly strategies don't need more |
| Multi-asset broker (optional) | **Interactive Brokers** | One account for stocks/ETFs/futures/options; more complex API |
| Portfolio/risk | **Custom + Riskfolio/skfolio** | Vol targeting, correlation caps, drawdown throttle |
| Experiment tracking | **MLflow + Optuna + DVC** | Reproducible trials; trial counting is essential for DSR/PBO |
| AI/NLP | **LightGBM + FinBERT + hosted LLM** | Tabular ML and event extraction work; LLM-only trading does not |
| Ops | **Prefect or Windows Task Scheduler + Telegram + Prometheus/Grafana** | Simple, observable, kill switch |
| Dashboard | **Streamlit** (or Plotly Dash) | Fast to build; not in the order path |

**Two execution paths, on purpose:**
- **Fast path (crypto):** Freqtrade dry-run → small live. It is mature and gets you trading sooner.
- **Long-term path (multi-asset):** the thin custom executor + Alpaca/ccxt/IBKR, with the same strategy functions. Migrate when the strategy and ops are stable.

Do not run two engines on the same capital without a clear allocation and reconciliation process.

### What I would *not* build on
- **Backtrader** — stale (last push 2024), GPL, large but aging.
- **vectorbt PRO** — paid; open-source vectorbt is Apache-2.0 **with Commons Clause** (cannot sell a product built on it).
- **mlfinlab** — no longer a usable open-source package; paid/closed.
- **FinRL / TradingAgents / "AI hedge fund" repos as production systems** — research demos; no credible live record; heavy overfitting and LLM look-ahead risk.
- **HFT, market making, latency arbitrage on a home PC** — you are competing with colocated firms; not realistic.
- **Copy trading, signal groups, paid bots** — excluded by your requirements and generally a bad risk-adjusted deal.

---

## 3. The honest evidence on "proven records"

| Strategy family | Evidence quality | Realistic net edge | Main risk |
|---|---|---|---|
| Time-series trend / CTA | Strong, 100+ years across asset classes; live CTA records | Sharpe ~0.4–0.8 net; can be higher with vol targeting | Whipsaw, long flat periods |
| Cross-sectional equity momentum | Strong since 1993; weak after 2000s | ~2–5% / yr net after costs, regime-dependent | Momentum crashes |
| Crypto cross-sectional momentum | Peer-reviewed but short sample (2014–2021) | High gross, much lower net; capacity-limited | 60–80% crashes, wash trading |
| Crypto carry / basis | Strong 2020–2026 evidence; carry up to 40% p.a. | Attractive, but crowded and counterparty-heavy | Exchange insolvency, funding flip |
| Value / quality | Strong long-sample | Modest, slow | Long underperformance |
| Short-term reversal | Real but tiny | Usually negative after costs for retail | Costs, adverse selection |
| News/social sentiment | Mixed; some effects replicate, many don't | Small, fast-decaying overlay | Data cost, manipulation, look-ahead |
| ML cross-section | Strong academic evidence of *predictability* | Economically modest; capacity-constrained | Overfitting, non-stationarity |
| LLM/agent trading | No credible long-term live record | Unknown / likely negative | Look-ahead, hallucination, cost |
| HFT / market making | Real but infrastructure-driven | Not accessible at home | Latency, fees, inventory risk |

**Key references** (full list in `docs/07_SOURCES.md`):
- Moskowitz, Ooi & Pedersen (2012), *Time Series Momentum* — 58 liquid futures, 1–12 month persistence.
- Jegadeesh & Titman (1993), *Returns to Buying Winners and Selling Losers* — 3–12 month equity momentum.
- Asness, Moskowitz & Pedersen (2013), *Value and Momentum Everywhere* — 8 markets; value and momentum negatively correlated.
- Liu, Tsyvinski & Wu (2022), *Common Risk Factors in Cryptocurrency* — market, size, momentum factors.
- Koijen et al. (2018), *Carry*; Schmeling, Schrimpf & Todorov (2026), *Crypto Carry* — carry predicts returns; crypto carry can exceed 40% p.a.
- Harvey, Liu & Zhu (2016) — new factors need **t > 3.0**; most claimed findings are likely false.
- Bailey & López de Prado (2014, 2016) — Deflated Sharpe Ratio and Probability of Backtest Overfitting.
- McLean & Pontiff (2016) — 26% lower out-of-sample, **58% lower post-publication** across 97 predictors.
- Novy-Marx & Velikov (2016) — most anomalies with >50% monthly turnover do not survive trading costs.
- Cong et al. (2022), *Crypto Wash Trading* — **>70% of reported volume** on unregulated exchanges may be fake.

**What this means for you:** target a net Sharpe of **0.5–1.0**, not 5. A 10–15% annualized return at 10–15% volatility with 20–30% drawdowns is a good outcome for a well-run retail system. Crypto trend/carry can produce more, but with 40–60% drawdowns and exchange counterparty risk.

---

## 4. Architecture

```text
┌─────────────────────────────────────────────────────────────────────┐
│                         DATA PLANE (daily/hourly)                    │
│  Binance Vision / ccxt / Alpaca / IBKR / FRED-ALFRED / SEC / X      │
│  → raw Parquet (immutable, checksummed)                             │
│  → normalized Parquet + DuckDB (event_time, knowledge_time)          │
│  → feature store (PIT joins only)                                    │
└─────────────────────────────────────────────────────────────────────┘
                                  │
┌─────────────────────────────────▼───────────────────────────────────┐
│                        RESEARCH PLANE                                │
│  signal functions → portfolio construction → backtester → costs      │
│  → walk-forward / CPCV / DSR / PBO → experiment registry (MLflow)   │
│  → tearsheets / research memo → GO / NO-GO gate                      │
└─────────────────────────────────────────────────────────────────────┘
                                  │
┌─────────────────────────────────▼───────────────────────────────────┐
│                        EXECUTION PLANE                               │
│  target weights → risk checks → order router → broker adapter        │
│  (Alpaca stocks / ccxt crypto / IBKR multi-asset)                    │
│  → reconciliation → order journal → alerts → kill switch             │
└─────────────────────────────────────────────────────────────────────┘
                                  │
┌─────────────────────────────────▼───────────────────────────────────┐
│                        CONTROL PLANE                                 │
│  scheduler · config · secrets · logs · metrics · dashboard · backup  │
└─────────────────────────────────────────────────────────────────────┘
```

**Critical design rule:** the **risk engine is deterministic and has veto power**. AI/ML only produces *features or proposals*; it never sends orders directly.

**Second critical rule:** every dataset row carries two timestamps:
- `event_time` — when the price/news/fundamental event happened.
- `knowledge_time` — when you could first have known it.

All joins use `knowledge_time <= decision_time`. This single discipline prevents most look-ahead bugs.

---

## 5. Six-month roadmap

| Phase | Weeks | Outcome | Gate |
|---|---|---|---|
| 0. Setup & data audit | 1 | Repo, env, accounts, first datasets | Data checksums, no missing sessions |
| 1. Data + backtester | 2–4 | PIT store, cost model, metrics, tearsheets | Reproduce buy-and-hold + trend |
| 2. Strategy research | 4–8 | Trend, crypto XSMOM, carry tested | DSR > 0, PBO < 0.2, net of 2× costs |
| 3. Portfolio + paper | 8–12 | Risk engine, paper executor, dashboard | 8 weeks paper, slippage within model |
| 4. Small live | 12–20 | Real money, small size, TCA | 3 months within drawdown limits |
| 5. AI + second strategy | 20–26 | Sentiment/ML research, equity sleeve | Incremental OOS value, not just backtest |

Full task breakdown: `docs/04_IMPLEMENTATION_PLAN.md`.

---

## 6. What it will cost

**To start (paper trading):**
- Alpaca: $0 (IEX, 15-min delayed REST; real-time IEX websocket; paper trading)
- Binance Vision: $0 historical crypto
- FRED/ALFRED, SEC EDGAR, GDELT, Reddit free tier, Bluesky: $0
- Total: **$0–30/month** (optional Tiingo news at $30)

**Serious research/live:**
- Alpaca Algo Trader Plus: **$99/mo** (all US exchanges, real-time, unlimited)
- Tiingo Power: **$30/mo** (EOD, news, crypto, IEX)
- X API: **$0.005/post read**; 2,000 posts/day ≈ **$300/mo**; 1M historical posts ≈ **$5,000**
- VPS/backup: **$10–30/mo**
- Realistic: **$100–450/month** all-in.

**Trading costs to model:**
- US stocks: $0 commission (Alpaca) + spread/slippage; IBKR ~$0.0035–0.005/share.
- Crypto: Alpaca 15/25 bps maker/taker at low volume; Binance/Kraken lower but venue-dependent.
- Funding, borrow, taxes, and FX are additional.

Do **not** pay for signals, "proven" bots, or copy trading.

Full line-item breakdown, tax notes, and affordability rules: `docs/09_COST_BREAKDOWN.md`.

---

## 7. This PC: what it can and cannot do

**Can do well:**
- Daily/hourly backtests on 10–20 years of data for hundreds of symbols.
- LightGBM/XGBoost, linear models, FinBERT inference on CPU.
- 100–200 GB of Parquet data; 646 GB free is enough for years of minute bars.
- 24-thread parameter sweeps; 28 GB RAM is plenty for vectorized research.

**Cannot do:**
- Tick-level HFT, L3 order-book deep learning, colocation.
- Large LLM fine-tuning (no CUDA GPU).
- Low-latency market making.

**Practical notes:**
- Install Python 3.12 via `uv`, not the Microsoft Store stub.
- Run production in **WSL2 Ubuntu** for stability (systemd/cron/Docker), or native Windows for simplicity. Don't mix.
- Use a UPS and disable sleep; a trading bot that stops because Windows updated is a real risk.
- Keep data and order journals on a separate backup drive.

---

## 7b. What was verified on this machine

- Installed `uv 0.13.5` and CPython `3.12.15`.
- Created `.venv` and installed the core research stack (293 packages resolved).
- Downloaded **2,465 daily BTCUSDT bars (2020-01 → 2026-09)** from Binance Vision, with SHA-256 checksum verification and UTC normalization.
- Ran a toy 200-day trend backtest with **next-open fills** and 10 bps/side costs:

| Metric | 200d trend | Buy & hold |
|---|---|---|
| Total return | 7.79× | 8.14× |
| CAGR | 42.0% | 42.8% |
| Volatility | 42.9% | 57.2% |
| Sharpe | 1.03 | 0.91 |
| Max drawdown | −64.0% | −76.6% |
| Exposure | 58.3% | 100% |

This is **not** a validated strategy — it has no walk-forward, DSR/PBO, funding, or survivorship handling. It only proves the data + backtest plumbing works. Chart: `artifacts/smoke_trend.png`. Tests: `uv run pytest` passes. Environment check: `uv run python scripts/check_env.py` passes (API keys not configured yet).

### Build status (v1)

The repo now contains a working research/backtest/paper + gated live-execution system:

- 8 crypto assets, 2020–2026, 19,673 daily bars (through 22 Oct 2026), clean data audit
- Trend + cross-sectional momentum strategies
- Next-open cost-aware backtester, risk limits, walk-forward, DSR, PBO
- Paper broker, order planning, SQLite journal
- **106 tests passing**, `ruff` pass, `mypy src` pass
- **Gated live command exists** — requires `--confirm-live`, `LIVE_TRADING=YES`, and a non-paper broker with `sandbox=false`; it is not validated for capital
- **Long-history paper replay:** 12.1-year BTC/LTC and 9.2-year 8-asset tests; see `docs/13_LONG_HISTORY.md`
- **Execution state machine:** persistent order intents, partial-fill handling, startup reconciliation; see `docs/15_EXECUTION_STATE.md`
- **Separate AI-agent paper pipeline:** own config, account, journal, performance, reports, and audit trail; deterministic policy retains veto power; see `docs/16_AI_AGENT_PIPELINE.md`
- **Jev evaluation:** optional TypeSafe typed-decision provider; hosted/paid, no key means fail closed; see `docs/17_JEV_EVALUATION.md`
- **AI scorecard:** paper days, fallback rate, TCA, benchmarks, confidence calibration; see `docs/18_AI_EVALUATION.md`
- **Breakout sleeve:** Donchian/ATR/volume, walk-forward DSR 0.354, PBO 0.190
- **Reversal sleeve:** research-only; walk-forward OOS Sharpe −0.367, PBO 0.792
- **Meta allocator:** trend + breakout + reversal + XSMOM, one risk budget; OOS Sharpe 1.120, DSR 0.867, PBO 0.038
- **Execution hardening:** terminal partial-fill completion and order chunking; true TWAP is not implemented
- **3D agent office:** two 51 x 36 m floors - a people-free quant workflow floor and a partitioned agent office floor - with glass-front trading bullpen, cubicle dividers, labs, meeting/director/risk/guest/WC rooms, reception, phone booths, pantry/fun spaces, daylight windows, Singapore time/weather, black-background toggle, collapsible Agent Office panel, camera tilt slider, managers, idle wander, and a Quant vs Agents paper competition scoreboard; see `docs/20_OFFICE3D.md`
- **Campaign health:** `TradingBotHealth` runs at 07:30 local and verifies fresh rows for trend, XSMOM, breakout, reversal, meta, and AI; writes `artifacts/CAMPAIGN_HEALTH.md`
- **PIT/listing universe:** `config/pit_universe_crypto.csv` prevents trading assets before their listing date; all crypto configs apply it
- **Carry research lane:** two-leg spot/perp funding/basis backtest + walk-forward; full-sample looks strong, OOS DSR 0.00 / PBO 0.57, so not added to meta
- **Extended PIT sample:** 8 current + 3 delisted assets with active spans; extended meta DSR 0.13 / PBO 0.05, still NO_GO
- **Full monthly PIT sample:** 87 delisted-inclusive assets, 763 monthly membership rows; meta OOS Sharpe 0.42, DSR 0.48, PBO 0.46, still NO_GO
- **Funding data:** public Binance funding-rate downloader + summary; 58,193 events through 23 Oct 2026
- **Hard live gate:** `live-gate` returns NO_GO until DSR/PBO, paper days, TCA, data, keys, and environment all pass

Engineering checks pass, but the strategies are **not validated for live capital** (trend DSR ≈ 0.26, XSMOM PBO ≈ 0.39). See `docs/10_SELF_EVAL.md` and `artifacts/SELF_EVAL.md`.

Jev is configured and returned real typed decisions (`jev-1.14.0`) in 10 historical dry runs. The AI paper account was reset to a clean **$10,000** on 23 Oct 2026, and the separate `TradingBotAIPaper` task is scheduled for 07:15 daily. The current scorecard is still `insufficient_data` (one day); the hard live gate is `NO_GO`. See `artifacts/LIVE_GATE.md`.

### Quick start on this repo

```powershell
# Environment is already synced; from a fresh clone:
uv sync --extra dev

# Rebuild the BTC sample (uses cached ZIPs if present)
uv run python scripts/download_binance_klines.py --symbol BTCUSDT --start 2020-01 --end 2026-09

# Toy trend backtest + chart
uv run python scripts/smoke_trend.py

# Full backtest + historical paper-broker replay
uv run python -m tradingbot backtest --strategy trend
uv run python -m tradingbot paper-replay --strategy trend

# One paper rebalance (persists state between runs)
powershell -ExecutionPolicy Bypass -File scripts/run_paper.ps1 -Strategy trend

# Checks
uv run pytest
uv run python scripts/check_env.py

# US stocks/ETFs (requires Alpaca paper keys)
uv run python -m tradingbot.cli --config config/alpaca.yaml download
uv run python -m tradingbot.cli --config config/alpaca.yaml backtest --strategy trend

# Operational runner (paper; persists state/heartbeat/risk state)
uv run python -m tradingbot run --mode paper --once
uv run python -m tradingbot run --mode paper --interval 3600

# Evaluation + dashboard (Both / Deterministic / AI agent views)
uv run python -m tradingbot evaluate --strategy trend
powershell -ExecutionPolicy Bypass -File scripts/run_dashboard.ps1

# Daily paper campaign (trend + XSMOM + reports); scheduled at 07:00 local
powershell -ExecutionPolicy Bypass -File scripts/run_campaign.ps1

# Campaign health check; scheduled at 07:30 local
uv run python -m tradingbot health
powershell -ExecutionPolicy Bypass -File scripts/register_health.ps1

# PIT listing spans + extended delisted sample
uv run python -m tradingbot universe-audit
uv run python -m tradingbot universe-build --output config/pit_universe_crypto.csv
uv run python scripts/build_pit_extended.py
uv run python -m tradingbot --config config/pit_extended.yaml backtest

# Full monthly delisted-inclusive PIT research universe
uv run python scripts/build_pit_full.py --top-n 10 --workers 8
uv run python -m tradingbot --config config/pit_full.yaml backtest
uv run python -m tradingbot --config config/pit_full.yaml walkforward --strategy meta

# Two-leg funding/basis carry research
uv run python -m tradingbot --config config/futures.yaml download
uv run python -m tradingbot download-funding --symbols BTCUSDT,ETHUSDT --start 2020-01-01
uv run python -m tradingbot funding-summary --path data/normalized/funding.parquet
uv run python -m tradingbot carry-backtest
uv run python -m tradingbot carry-walkforward

# Separate AI-agent paper pipeline (paper only; no live path)
# TYPESAFE_API_KEY is configured in .env; or point agent.endpoint at a local model.
uv run python -m tradingbot --config config/ai_agent.yaml ai-run --dry-run
uv run python -m tradingbot --config config/ai_agent.yaml ai-run
uv run python -m tradingbot --config config/ai_agent.yaml ai-status
powershell -ExecutionPolicy Bypass -File scripts/run_ai_pipeline.ps1
# Optional separate daily task (07:15), after configuring a provider:
powershell -ExecutionPolicy Bypass -File scripts/register_ai_campaign.ps1

# Ten point-in-time dry decisions (no orders)
uv run python scripts/jev_smoke.py

# Breakout / reversal / meta sleeves
uv run python -m tradingbot --config config/breakout.yaml backtest
uv run python -m tradingbot --config config/reversal.yaml backtest
uv run python -m tradingbot --config config/meta.yaml backtest
powershell -ExecutionPolicy Bypass -File scripts/run_sleeves.ps1

# 3D office (standalone HTML; dashboard has a "3D Office" view)
uv run python scripts/build_office3d.py

# AI scorecard + hard live gate
uv run python -m tradingbot --config config/ai_agent.yaml ai-evaluate
uv run python -m tradingbot --config config/live.alpaca.yaml live-gate --include-ai

# Kill / resume / flatten / status
uv run python -m tradingbot kill
uv run python -m tradingbot resume
uv run python -m tradingbot flatten
uv run python -m tradingbot status
```

Live is gated separately: see `docs/11_RUNBOOK.md` §7b.

---

## 8. The 10 things that most often kill retail bots

1. **Look-ahead bias** — using a bar's close before it closes; full-sample normalization; future fundamentals.
2. **Survivorship bias** — only testing coins/stocks that still exist.
3. **Ignoring costs** — 10 bps assumption on a strategy that trades 50×/year.
4. **Overfitting** — trying 10,000 parameter sets and reporting the best.
5. **Regime dependence** — a crypto bull-market strategy tested only in 2020–2021.
6. **Execution bugs** — duplicate orders, wrong side, stale prices, no reconciliation.
7. **Counterparty risk** — exchange insolvency (FTX), stablecoin depeg, broker outage.
8. **Risk concentration** — one coin, one factor, one venue.
9. **No kill switch** — a runaway loop or API bug drains the account.
10. **Psychological/process failure** — overriding the system, increasing size after wins.

The validation protocol in `docs/05_VALIDATION_PROTOCOL.md` is designed around these.

---

## 9. Documents

| File | Contents |
|---|---|
| `docs/01_RESEARCH_REPORT.md` | Deep research: how professionals/retail trade, evidence, market microstructure, macro, sentiment, AI |
| `docs/02_TECH_STACK.md` | Framework/library comparison with licenses and verdicts |
| `docs/03_DATA_AND_APIS.md` | Data sources, prices, licensing, PIT protocol, cost budget |
| `docs/04_IMPLEMENTATION_PLAN.md` | 26-week plan, repo layout, tasks, gates, ops runbook |
| `docs/05_VALIDATION_PROTOCOL.md` | Walk-forward, CPCV, DSR, PBO, cost stress, paper/live gates |
| `docs/06_STRATEGY_CATALOG.md` | 8 candidate strategies with hypotheses, data, risks, test plans |
| `docs/07_SOURCES.md` | Papers, docs, pricing pages, GitHub repos (accessed 22 Oct 2026) |
| `docs/08_BOOTSTRAP.md` | Exact Windows/WSL setup commands and first-week checklist |
| `docs/09_COST_BREAKDOWN.md` | Detailed setup, data, trading, tax, and infrastructure costs |
| `docs/10_SELF_EVAL.md` | v1 self-evaluation: checks, results, bugs found, limitations |
| `docs/11_RUNBOOK.md` | Daily paper run, Task Scheduler, kill switch, incident playbook |
| `docs/12_LIVE_CHECKLIST.md` | Broker/API/paper-evidence checklist before real money |
| `docs/ARCHITECTURE.md` | Architecture diagram (PNG/SVG) + Mermaid source + runtime sequence |
| `docs/13_LONG_HISTORY.md` | 12-year BTC/LTC + 9-year 8-asset paper replay and walk-forward |
| `docs/14_LIVE_EVALUATION.md` | TCA, live-vs-backtest, drift, dashboard, daily campaign |
| `docs/15_EXECUTION_STATE.md` | Order state machine, partial fills, startup reconciliation |
| `docs/16_AI_AGENT_PIPELINE.md` | Separate AI-agent paper pipeline, dashboard, decision contract, safety |
| `docs/17_JEV_EVALUATION.md` | Jev/TypeSafe typed-decision assessment, cost, risks, sources |
| `docs/18_AI_EVALUATION.md` | AI paper scorecard, calibration, promotion evidence rules |
| `docs/19_MULTI_SLEEVE.md` | Breakout, reversal, meta allocator, execution hardening and results |
| `docs/20_OFFICE3D.md` | Two-floor 3D office, quant/agent competition, daylight/weather, squads, Blender MCP status |
| `docs/21_PIT_AND_FUNDING.md` | Campaign health, listing-aware PIT spans, funding data and carry caveats |
| `docs/22_CARRY_AND_EXTENDED_PIT.md` | Two-leg carry research, walk-forward result, extended delisted sample |

---

## 10. Before we write code, confirm these 4 things

1. **Jurisdiction** — US? (affects brokers, 2026 intraday margin rules, taxes, crypto access)
2. **Capital** — paper only at first; then $5k / $25k / $100k?
3. **Time** — hours per week you can commit (10 vs 40 changes the plan)
4. **Priority** — crypto first, stocks first, or truly multi-asset from day one?

My default assumption if you don't specify: **US resident, $10k–25k risk capital, 10–15 hours/week, crypto-first then stocks**.

---

## 11. Disclaimer

This is research and engineering planning, **not financial, investment, tax, or legal advice**. Trading involves substantial risk of loss. Past performance and backtests do not guarantee future results. Verify every fee, API term, and regulation with the provider and a qualified professional in your jurisdiction.
