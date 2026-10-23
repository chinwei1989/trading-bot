# 02 — Tech Stack: Libraries, Frameworks, and Verdicts

**Research date:** 22 October 2026  
**Rule:** choose boring, maintained tools; keep the strategy layer independent of the execution engine.

---

## 1. The decision in one page

### Recommended v1 stack

| Layer | Tool | Role |
|---|---|---|
| Runtime | **Python 3.12 + uv** | Reproducible environment |
| DataFrames | **Polars** (Pandas fallback) | Fast columnar research |
| Storage | **Parquet + DuckDB** | Local analytical store; no server |
| Backtest | **Custom vectorized portfolio backtester** | Cross-asset accounting, costs, PIT |
| Event-driven validation | **NautilusTrader v1.x** | Final realism check; later live |
| Crypto lab / first live | **Freqtrade** | Dry-run, hyperopt, look-ahead analysis, FreqAI |
| Stocks execution | **Alpaca + thin custom executor** | Paper API, commission-free, simple |
| Optional multi-asset broker | **Interactive Brokers** | One account, broad products |
| Optimization | **Optuna** | Parameter search with trial accounting |
| Tracking | **MLflow** | Experiments, artifacts, model registry |
| Data versioning | **DVC** (or git-lfs + checksums) | Reproducibility |
| Metrics/reports | **QuantStats + custom tearsheets** | Performance and risk |
| Portfolio | **Riskfolio-Lib / skfolio** | Optimization, risk models |
| ML | **scikit-learn + LightGBM + XGBoost** | Tabular alpha |
| NLP | **FinBERT + hosted LLM** | Sentiment/event extraction |
| Ops | **Prefect or Task Scheduler + Telegram + Prometheus/Grafana** | Scheduling, alerts, monitoring |
| Dashboard | **Streamlit** | Human oversight |

### The most important architectural decision

**Do not couple strategy logic to a broker or backtest engine.**

Write strategies as pure functions:

```python
def target_weights(features: pl.DataFrame, config: StrategyConfig) -> pl.DataFrame:
    """Return target weights indexed by (timestamp, asset). No I/O, no broker calls."""
```

Then:
- the research backtester consumes `target_weights`;
- the live executor consumes the same `target_weights`;
- Nautilus/Freqtrade/Alpaca are interchangeable adapters.

This makes migration possible and prevents "it worked in the backtest but the live code is different" failures.

---

## 2. Backtesting / trading frameworks compared

| Framework | Version (Oct 2026) | Asset classes | Live trading | License | Strengths | Weaknesses | Verdict |
|---|---|---|---|---|---|---|---|
| **NautilusTrader** | 1.231.0 stable; 2.0 RC | Multi-asset: crypto, equities, futures, FX, options, prediction markets | Yes: Binance, Bybit, Coinbase, Kraken, OKX, IBKR, Hyperliquid, dYdX, Polymarket; data providers Databento/Tardis | **LGPL-3.0** | Rust core, deterministic event-driven, backtest/live parity, order-book data, nanosecond timestamps, professional architecture | Steep learning curve; v2 API in flux; **no Alpaca adapter**; Windows v2 wheels for Python 3.13–3.14 | **Best long-term production spine**; start with v1 stable or wait for v2 |
| **Freqtrade** | 2026.9 | Crypto spot/futures | Yes, many exchanges via ccxt | **GPL-3.0** | Mature, dry-run, hyperopt, **look-ahead analysis**, FreqAI, Telegram/WebUI, active community | Crypto only; GPL copyleft; not a cross-asset portfolio engine | **Best crypto lab and fastest first live bot** |
| **QuantConnect LEAN** | Active | Multi-asset: equities, options, futures, FX, crypto | Yes: Alpaca, IBKR, Coinbase, Binance, Kraken, etc. | **Apache-2.0** | True multi-asset, mature broker integrations, data library, C#/Python, cloud/local | C#/.NET build; data plumbing; cloud data costs; heavier local setup | **Best alternative if you want one engine for both stocks and crypto** |
| **Zipline-reloaded** | 3.2.0 | US equities | No | **Apache-2.0** | Pipeline API, PIT data, well-understood equity factor research | No live trading; equities only; data bundle setup | **Good equity research tool** |
| **Qlib** | Active (Microsoft) | Mostly China/US equities; extensible | No direct brokerage (research/serving) | **MIT** | Alpha158/Alpha360, ML pipeline, nested backtesting, RL, strong research ecosystem | Data wrangling; China-centric examples; not an execution platform | **Good ML research lab** |
| **vectorbt** | 1.2.0 | Multi-asset | No | **Apache-2.0 + Commons Clause** | Extremely fast vectorized sweeps, huge parameter grids, nice analytics | **Commons Clause prohibits selling**; easy to overfit; no live execution | **Research only, if license acceptable** |
| **backtesting.py** | 0.6.6 | Single-asset | No | **AGPL-3.0** | Simple, small, good for learning | Single-asset; limited realism; AGPL | **Teaching/prototyping only** |
| **Backtrader** | 1.9.x (last push 2024) | Multi-asset | Yes (IBKR etc.) | **GPL-3.0** | Large community, many examples | Stale, slow, aging API, GPL | **Do not start new projects on it** |
| **pysystemtrade** | Active | Futures | Yes (IBKR) | **GPL-3.0** | Rob Carver's production system: forecasting, vol targeting, risk overlay | Complex, futures-centric, not turnkey for stocks/crypto | **Reference architecture, not a base** |
| **Hummingbot** | Active | Crypto | Yes | **Apache-2.0** | Market making, liquidity provision, many venues | Not a directional strategy/backtest-first framework | **Only if market making** |
| **Jesse** | Active | Crypto | Yes | **MIT** | Clean API, live trading, smaller learning curve | Smaller ecosystem than Freqtrade; fewer features | **Niche alternative** |
| **OpenBB** | 5.0.0 | Data/research | No | **Apache-2.0** (some data terms) | Data aggregation, research UI, AI agents | Not an execution engine | **Optional research UI** |
| **MLfinlab** | Closed/paid | — | — | Proprietary | López de Prado methods | No longer a usable open-source dependency | **Avoid; implement methods yourself** |
| **FinRL** | 0.3.7 | Research | No | **MIT** | RL environments/agents | Backtests are unrealistic; no live record | **Experiment only** |
| **TradingAgents** | Active | Research | No | **Apache-2.0** | Multi-agent LLM research framework | No audited live record; LLM look-ahead | **Experiment only** |

### Framework verdict details

#### NautilusTrader — the production spine, with caveats

**Why it's good:**
- Rust-native core with Python control plane.
- Same strategy code for backtest and live.
- Deterministic event-driven simulation; supports bar, trade, quote, and order-book data.
- Realistic fill models, accounts, margin, and reconciliation.
- Stable adapters for Binance, Bybit, Coinbase, Kraken, OKX, IBKR, Databento, Tardis.
- LGPL-3.0: you can use it in a proprietary application; modifications to the library itself must be shared if distributed.

**Caveats:**
- **No Alpaca adapter.** For US stocks, either use IBKR or write a custom adapter.
- **v2 is a release candidate.** The README explicitly says v2 RC wheels are not recommended for production. Pin **v1.231.0** for live, or wait.
- v2 Windows wheels target Python 3.13–3.14; v1 may differ. Check the install matrix before committing.
- Steep learning curve; budget 2–4 weeks to become productive.

**Use it for:** final backtest realism, IBKR live execution, multi-venue crypto execution, future scaling.

#### Freqtrade — the crypto laboratory and fastest first live bot

**Why it's good:**
- Mature and actively maintained (2026.9).
- `download-data`, `backtesting`, `hyperopt`, `lookahead-analysis`, `recursive-analysis`, `dry-run`, `trade`, Telegram, WebUI.
- FreqAI for ML-based strategies.
- Works with many exchanges via ccxt.
- The look-ahead analysis command is genuinely useful: it re-runs the strategy on sliced data and compares indicator/signal values to detect future leakage.

**Caveats:**
- Crypto only.
- GPL-3.0: if you distribute a modified version, you must release source under GPL. Personal use is fine.
- Its portfolio model is trade-centric, not a cross-asset allocator.
- Community strategies are often overfit; do not trust them.

**Use it for:** crypto research, dry-run, first live crypto sleeve, independent validation of your own crypto signals.

#### LEAN — the best single-engine alternative

**Why consider it:**
- True multi-asset (equities, options, futures, FX, crypto).
- Apache-2.0.
- Live integrations include Alpaca, IBKR, Coinbase, Binance, Kraken.
- Local CLI and cloud; large data library.
- Mature order/fill modeling.

**Why not default:**
- C#/.NET build and data plumbing add friction.
- The best data experience is tied to QuantConnect cloud (paid).
- Python algorithms run inside LEAN's engine; debugging is less direct than a pure-Python stack.
- For a solo builder, the learning curve is comparable to Nautilus but with a different ecosystem.

**Use it if:** you want one engine with Alpaca + crypto and are willing to invest in the platform.

#### vectorbt — fast research, license caveat

- Apache-2.0 **with Commons Clause**: you may not "sell" a product or service whose value derives substantially from the software. Personal research is fine; a commercial trading product built on it is not.
- Excellent for sweeping thousands of parameter combinations.
- Easy to overfit; always confirm with walk-forward/CPCV and an event-driven engine.
- No live execution.

#### Qlib — ML research, not execution

- MIT license.
- Alpha158/Alpha360 feature sets, model zoo, nested backtesting, RL.
- Strong for learning cross-sectional ML.
- Data setup is China-centric; US/crypto data requires custom loaders.
- Not a broker execution platform.

#### Zipline-reloaded — equity factor research

- Apache-2.0, actively maintained.
- Pipeline API is excellent for cross-sectional factors.
- No live trading.
- Data bundle setup is the main friction.
- Good complement to a custom backtester for US equities.

#### Backtrader — legacy

- Last push August 2024; large community but effectively stale.
- GPL-3.0.
- Slow event loop; limited modern data support.
- Fine for reading examples, not for a new build.

#### pysystemtrade — reference, not base

- Rob Carver's systematic futures system.
- Excellent forecasting, volatility targeting, risk overlay, and portfolio construction ideas.
- GPL-3.0; futures/IBKR-centric; complex.
- Read it for architecture; don't fork it for a crypto/equity bot.

---

## 3. Data stack

### 3.1 Storage layout

```text
data/
  raw/                     # immutable vendor files, checksummed
    binance/...
    alpaca/...
    fred/...
  normalized/              # clean Parquet, UTC, typed
    bars/
      asset_class=...
      frequency=1d/
        year=2026/
          part-0.parquet
  features/                # PIT feature store
    momentum/
    macro/
    sentiment/
  reference/               # instruments, calendars, corporate actions
  quality/                 # data quality reports
```

### 3.2 Why Parquet + DuckDB

- **Parquet**: columnar, compressed, schema-evolution friendly, works with Polars/Pandas/DuckDB/Spark.
- **DuckDB**: in-process SQL, no server, excellent for joins/aggregations over Parquet.
- **Polars**: fast, lazy, multi-threaded; good for feature engineering.
- **SQLite**: order journal/state only; not for analytics.
- **Postgres/TimescaleDB**: only if you later need concurrent services; not required for v1.

### 3.3 Data quality checks

Every ingestion run should produce a report:

- Row count vs expected (trading days × symbols).
- Missing bars/sessions.
- Duplicate timestamps.
- OHLC consistency (`low <= open/close <= high`).
- Non-positive prices/volumes.
- Extreme returns (flag, don't silently drop).
- Timezone alignment.
- Corporate action coverage.
- Delisted/universe changes.
- Checksum and source version.

Use **Great Expectations** or a small custom validator. Fail the pipeline loudly; don't train on corrupt data.

---

## 4. Research stack

| Tool | Use |
|---|---|
| **Optuna** | Hyperparameter search; log every trial for DSR |
| **MLflow** | Experiment tracking, metrics, artifacts, model registry |
| **DVC** | Data versioning and pipeline reproducibility |
| **QuantStats** | Quick tearsheets; supplement with custom metrics |
| **scikit-learn** | Pipelines, CV splitters, calibration, preprocessing |
| **LightGBM / XGBoost** | Tabular alpha |
| **SHAP** | Feature attribution and stability checks |
| **statsmodels / arch** | Time series, cointegration, GARCH |
| **Riskfolio-Lib / skfolio** | Portfolio optimization and risk models |
| **Hypothesis** | Property-based tests for accounting invariants |
| **pytest** | Unit/integration tests |

### Experiment registry

For every strategy run, log:
- Git commit hash.
- Data version (DVC hash or checksums).
- Universe definition.
- Feature list and transformations.
- Hyperparameters.
- Train/validation/test dates.
- Number of trials.
- Costs/slippage assumptions.
- Metrics (Sharpe, Sortino, Calmar, max DD, turnover, exposure).
- DSR, PBO, MinTRL.
- Artifacts: equity curve, trades, tearsheet.

If you can't reproduce it from the registry, it didn't happen.

---

## 5. Execution stack

### 5.1 Broker adapters

| Broker | Asset classes | API | Paper | Commissions | Notes |
|---|---|---|---|---|---|
| **Alpaca** | US stocks/ETFs/options/crypto | REST + WebSocket, `alpaca-py` | Yes | $0 stocks; crypto 15/25 bps tier 1 | Easiest US retail API; crypto no margin/short; 20+ coins |
| **Interactive Brokers** | Global stocks, options, futures, FX, bonds, crypto (via Paxos) | TWS/IB Gateway, `ibapi`/Nautilus adapter | Yes | $0.0035–0.005/share; futures/options separate | Broadest; complex; market data subscriptions |
| **Kraken** | Crypto spot/futures | REST + WebSocket, ccxt | Yes (some) | ~0.16–0.40% depending on tier | Regulated, good for US; fewer coins than Binance |
| **Coinbase** | Crypto spot | REST + WebSocket, ccxt | Yes | Advanced Trade fees | Regulated US; higher fees |
| **Binance** | Crypto spot/futures | REST + WebSocket, ccxt | Testnet | 0.1% spot; lower with BNB | Not available to US persons; check jurisdiction |
| **Bybit/OKX** | Crypto derivatives | REST + WebSocket, ccxt | Testnet | Tiered | Offshore; counterparty/regulatory risk |

### 5.2 Order management requirements

- Idempotent client order IDs.
- Order state machine: `NEW → SUBMITTED → ACCEPTED → PARTIAL → FILLED/CANCELED/REJECTED`.
- Persistent order journal (append-only).
- Reconciliation with broker positions on startup and periodically.
- Retry with backoff; never blindly resubmit on timeout.
- Rate-limit handling.
- Kill switch: cancel all, flatten all, disable trading.
- Separate API keys per strategy/sleeve where possible.
- Trade-only keys; **withdrawals disabled**; IP allowlist; 2FA.

### 5.3 Slippage/fill model

For daily/hourly strategies:
- Stocks: fill at next bar open + half-spread + slippage (5–20 bps depending on liquidity).
- Crypto: fill at next bar open + half-spread + 10–30 bps; use taker fees for market orders, maker fees for limit orders with fill probability.
- Perps: include funding at the correct timestamp; include liquidation checks.
- For limit orders: model queue position or use a conservative "fill only if price trades through" rule.
- Stress with 2× and 3× costs.

---

## 6. AI/NLP stack

### 6.1 Models

| Model | Use | Cost | Notes |
|---|---|---|---|
| **FinBERT** (`ProsusAI/finbert`) | Baseline sentiment | Free, CPU | Fast; trained on financial text; not great on slang/crypto |
| **RoBERTa/DeBERTa finance variants** | Better sentiment | Free, CPU/GPU | Heavier; evaluate |
| **Hosted LLM** (OpenAI/Anthropic/Google/xAI) | Event extraction, summarization, classification | Per token | Best quality; log prompts/versions; data privacy |
| **Local small LLM** (7B–8B quantized) | Offline/private extraction | Free, slow on CPU | 28 GB RAM can run small quantized models; no CUDA |
| **Embeddings** | Narrative clustering, dedupe | Cheap | Use for research and feature discovery |
| **LightGBM** | Cross-sectional prediction | Free, CPU | Strong baseline; interpretable |
| **Temporal CNN/Transformer** | Sequence modeling | Free, GPU preferred | Only with large datasets and strict validation |

### 6.2 AI architecture

```text
News/X/Reddit → ingestion → dedupe → entity linking → sentiment/event model
    → structured JSON (asset, event_type, polarity, confidence, timestamp)
    → feature store → strategy overlay
```

**Never** let the LLM output a raw order. It outputs a structured feature or a research note. The deterministic risk engine decides.

### 6.3 LLM look-ahead checklist

- Use the exact model version and prompt in backtests.
- Timestamp every prompt and response.
- Ensure the prompt contains only information available at `decision_time`.
- Be aware that the model's training data may include future outcomes.
- Validate against a simple baseline (FinBERT/lexicon) and a placebo (random sentiment).
- If the LLM signal only works on historical data but not forward paper, assume look-ahead.

---

## 7. Ops stack

| Concern | Tool |
|---|---|
| Scheduling | Prefect (Python-native) or Windows Task Scheduler |
| Process supervision | systemd (WSL2) or NSSM (Windows) |
| Logging | `structlog` + JSON logs; rotate daily |
| Metrics | Prometheus + Grafana (or simple SQLite + Streamlit) |
| Alerting | Telegram bot, email, PagerDuty (optional) |
| Secrets | Environment variables + Windows Credential Manager / 1Password CLI |
| Backups | Nightly to external drive + encrypted cloud |
| CI | GitHub Actions: ruff, mypy, pytest, backtest smoke test |
| Deployment | Native Windows or WSL2; Docker Compose optional |
| Monitoring | Heartbeat, data freshness, order latency, slippage, PnL, drawdown |

### Minimum viable ops

1. A daily job that ingests data and writes a freshness report.
2. A signal job that writes target weights.
3. An execution job that reconciles and places orders.
4. A monitor that alerts on:
   - no heartbeat > 5 min,
   - stale data,
   - order rejected,
   - position mismatch,
   - drawdown > limit,
   - API error rate spike.
5. A kill switch file/endpoint that flattens and stops.

---

## 8. Dependency list (starting point)

```toml
[project]
requires-python = ">=3.12,<3.13"
dependencies = [
  "polars>=2.0",
  "pandas>=2.2",
  "pyarrow>=17",
  "duckdb>=2.0",
  "numpy>=2.0",
  "scipy>=1.14",
  "statsmodels>=0.14",
  "arch>=8.0",
  "scikit-learn>=1.5",
  "lightgbm>=4.5",
  "xgboost>=2.1",
  "optuna>=4.0",
  "mlflow>=2.17",
  "quantstats>=0.0.86",
  "matplotlib>=3.9",
  "plotly>=5.24",
  "pydantic>=2.9",
  "pydantic-settings>=2.6",
  "pyyaml>=6.0",
  "httpx>=0.27",
  "tenacity>=9.0",
  "structlog>=24.4",
  "exchange-calendars>=4.13",
  "pandas-market-calendars>=4.10",
  "ccxt>=4.4",
  "alpaca-py>=0.44",
  "riskfolio-lib>=7.4",
  "skfolio>=1.9",
  "transformers>=4.46",
  "torch>=2.5",
  "shap>=0.46",
  "pytest>=8.3",
  "hypothesis>=6.112",
  "ruff>=0.7",
  "mypy>=1.13",
]

[project.optional-dependencies]
nautilus = ["nautilus_trader==1.231.0"]
freqtrade = ["freqtrade==2026.9"]
notebooks = ["jupyterlab>=4.3", "ipykernel>=6.29"]
```

**Notes:**
- Pin exact versions in `uv.lock` after testing.
- Nautilus v2 RC is optional; do not put it in the main dependency group until you're ready.
- Freqtrade has its own environment/installer; keep it separate to avoid dependency conflicts.
- On Windows, TA-Lib can be painful; use Polars-based indicators or Nautilus indicators instead.
- **License trap:** `riskfolio-lib` 7.4.0 depends on `vectorbt` 1.0.0, which is Apache-2.0 **with Commons Clause**. Personal use is fine; for a commercial product, use `skfolio` instead and remove the transitive vectorbt dependency (or get legal advice).

---

## 9. License compliance summary

| Tool | License | Personal use | Commercial product | Obligations |
|---|---|---|---|---|
| NautilusTrader | LGPL-3.0 | Yes | Yes | Share modifications to the library if distributed; dynamic linking OK |
| Freqtrade | GPL-3.0 | Yes | Caution | Distributing a derivative requires GPL source |
| LEAN | Apache-2.0 | Yes | Yes | Attribution/notice |
| Zipline-reloaded | Apache-2.0 | Yes | Yes | Attribution/notice |
| Qlib | MIT | Yes | Yes | Attribution |
| vectorbt | Apache-2.0 + Commons Clause | Yes | **No selling** | Cannot sell a product substantially based on it |
| backtesting.py | AGPL-3.0 | Yes | Caution | Network use may trigger source disclosure |
| Backtrader | GPL-3.0 | Yes | Caution | GPL |
| pysystemtrade | GPL-3.0 | Yes | Caution | GPL |
| ccxt | MIT | Yes | Yes | Attribution |
| alpaca-py | Apache-2.0 | Yes | Yes | Attribution |
| QuantStats | Apache-2.0 | Yes | Yes | Attribution |
| Riskfolio-Lib | BSD-3 | Yes | Yes | Attribution |
| skfolio | BSD-3 | Yes | Yes | Attribution |
| MLfinlab | Proprietary | Paid | Paid | Not open source |

**If you might commercialize:** avoid vectorbt, Freqtrade (or open-source your fork), and AGPL tools in the product path; prefer Nautilus (LGPL), LEAN (Apache), Zipline (Apache), Qlib (MIT), and your own code.

---

## 10. Final recommendation

**Build v1 with:**
- Python 3.12 + uv
- Polars + Parquet + DuckDB
- Custom vectorized backtester + Nautilus v1 for final validation
- Freqtrade for crypto lab/dry-run
- Alpaca for US stocks paper/live
- ccxt/Kraken or Coinbase for crypto live (jurisdiction-dependent)
- Optuna + MLflow + DVC
- LightGBM + FinBERT + hosted LLM
- Prefect/Task Scheduler + Telegram + Streamlit

**Do not build v1 with:**
- A single monolithic framework that owns data, research, execution, and UI.
- vectorbt PRO, mlfinlab, or copy-trading platforms.
- LLM agents in the order path.
- HFT/market-making infrastructure.

**Migration path:**
- Keep strategies as pure functions.
- If you outgrow the custom executor, move execution to Nautilus v2 (when stable) or LEAN.
- If you stay crypto-only, Freqtrade may be all you need.
