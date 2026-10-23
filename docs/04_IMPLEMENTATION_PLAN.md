# 04 — Implementation Plan (26 Weeks, Solo Builder)

**Assumption:** 10–15 hours/week, US resident, $10k–25k risk capital, crypto-first then US equities.  
**Full-time equivalent:** 10–12 weeks.  
**Start:** after Phase 0 decisions in `README.md` §10.

---

## 1. Principles

1. **Research before execution.** 70% of effort goes into data, validation, and risk; 20% execution; 10% UI/AI.
2. **One source of truth for positions.** The broker is authoritative for live positions; your journal is authoritative for intent. Reconcile continuously.
3. **Pure strategy functions.** Signals produce target weights; execution adapters are replaceable.
4. **Point-in-time or it didn't happen.** Every dataset row has `event_time` and `knowledge_time`.
5. **Count every trial.** If you test 500 variants, the DSR must know about all 500.
6. **Paper before live; small before large.** No exceptions.
7. **Kill fast.** A strategy that fails a gate is retired, not "given more time".
8. **Boring infrastructure.** Prefer simple, observable components over clever ones.

---

## 2. Target architecture

```text
┌──────────────────────────────────────────────────────────────────────┐
│ INGESTION (scheduled)                                                │
│  binance_vision · ccxt · alpaca · fred/alfred · sec · news · x       │
│  → raw/ (immutable, checksummed)                                     │
│  → normalized/ (Parquet, UTC, typed)                                 │
│  → quality report (fail loudly)                                      │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────────┐
│ FEATURE STORE (PIT)                                                  │
│  bars · returns · vol · momentum · funding · macro · sentiment       │
│  joins only on knowledge_time <= decision_time                       │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────────┐
│ STRATEGY LAYER (pure functions)                                      │
│  trend · xsmom · carry · equity_momentum · sentiment_overlay         │
│  → target weights + confidence + metadata                            │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────────┐
│ PORTFOLIO + RISK                                                     │
│  vol targeting · correlation caps · per-asset caps · drawdown throttle│
│  → constrained target weights                                        │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────────┐
│ BACKTEST / EXECUTION                                                 │
│  research backtester (vectorized)                                    │
│  Nautilus (event-driven validation)                                  │
│  executor: Alpaca (stocks) · ccxt (crypto) · IBKR (optional)         │
│  → orders · fills · reconciliation · journal                         │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────────┐
│ OPS                                                                  │
│  scheduler · Telegram · Prometheus/Grafana · Streamlit · backups     │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Repository layout

```text
tradingbot/
├── pyproject.toml
├── uv.lock
├── README.md
├── .gitignore
├── .env.example
├── config/
│   ├── base.yaml
│   ├── venues.yaml
│   ├── risk.yaml
│   └── strategies/
│       ├── trend.yaml
│       ├── xsmom.yaml
│       └── carry.yaml
├── src/tradingbot/
│   ├── __init__.py
│   ├── config.py
│   ├── logging.py
│   ├── data/
│   │   ├── sources/
│   │   │   ├── binance_vision.py
│   │   │   ├── ccxt_source.py
│   │   │   ├── alpaca_source.py
│   │   │   ├── fred.py
│   │   │   ├── sec.py
│   │   │   ├── news.py
│   │   │   └── social.py
│   │   ├── store.py
│   │   ├── normalize.py
│   │   ├── quality.py
│   │   ├── calendar.py
│   │   └── universe.py
│   ├── features/
│   │   ├── returns.py
│   │   ├── volatility.py
│   │   ├── momentum.py
│   │   ├── carry.py
│   │   ├── macro.py
│   │   ├── sentiment.py
│   │   └── registry.py
│   ├── research/
│   │   ├── backtest.py
│   │   ├── costs.py
│   │   ├── metrics.py
│   │   ├── validation.py
│   │   ├── trials.py
│   │   └── report.py
│   ├── strategies/
│   │   ├── base.py
│   │   ├── trend.py
│   │   ├── xsmom.py
│   │   ├── carry.py
│   │   ├── equity_momentum.py
│   │   └── sentiment_overlay.py
│   ├── portfolio/
│   │   ├── construction.py
│   │   ├── risk.py
│   │   ├── sizing.py
│   │   └── constraints.py
│   ├── execution/
│   │   ├── broker.py
│   │   ├── alpaca_broker.py
│   │   ├── ccxt_broker.py
│   │   ├── ibkr_broker.py
│   │   ├── order_manager.py
│   │   ├── reconciler.py
│   │   └── killswitch.py
│   ├── ops/
│   │   ├── scheduler.py
│   │   ├── monitor.py
│   │   ├── alerts.py
│   │   └── dashboard.py
│   └── ai/
│       ├── sentiment.py
│       ├── events.py
│       ├── embeddings.py
│       └── guardrails.py
├── notebooks/
│   ├── 01_data_audit.ipynb
│   ├── 02_trend_research.ipynb
│   ├── 03_xsmom_research.ipynb
│   └── 04_carry_research.ipynb
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── property/
│   └── fixtures/
├── scripts/
│   ├── bootstrap.ps1
│   ├── download_data.py
│   ├── run_backtest.py
│   ├── run_paper.py
│   └── run_live.py
├── data/                  # gitignored
│   ├── raw/
│   ├── normalized/
│   ├── features/
│   └── reference/
├── artifacts/             # gitignored: backtests, models, reports
├── docs/
└── .github/workflows/ci.yml
```

---

## 4. Phase 0 — Setup and data audit (Week 1)

### Tasks

- [ ] Install `uv`, Python 3.12, Git (already installed).
- [ ] Create repo, `pyproject.toml`, `.gitignore`, `.env.example`.
- [ ] Set up secrets: Alpaca keys (paper), exchange testnet keys, FRED API key.
- [ ] Create Alpaca paper account; verify market data + paper order.
- [ ] Download BTC/ETH 1d + 1h from Binance Vision for 2017–2026.
- [ ] Download SPY/QQQ 1d from Alpaca for 2010–2026.
- [ ] Download 10 core FRED series (DFF, DGS10, DGS2, VIXCLS, BAMLH0A0HYM2, DTWEXBGS, CPIAUCSL, UNRATE, PAYEMS, WALCL).
- [ ] Write `docs/data_dictionary.md` (schema, units, time zones).
- [ ] Run a data audit: missing bars, duplicates, OHLC violations, extreme returns.
- [ ] Write a one-page "data risk register".

### Deliverables
- Reproducible environment (`uv sync` works).
- `data/raw` with checksums (`sha256` manifest).
- Data audit report.
- A notebook that loads and plots BTC, SPY, and the 10y yield.

### Exit criteria
- `uv run pytest` passes (even if only smoke tests).
- Data audit shows <0.1% missing bars for the chosen universe, or documented reasons.
- No look-ahead in the basic loaders (timestamps verified).

---

## 5. Phase 1 — Data platform + backtester (Weeks 2–4)

### 5.1 Data platform

- [ ] Implement `data/sources/*` with retries, rate limits, and caching.
- [ ] Implement `data/store.py`: write raw → normalized Parquet, partition by asset class/frequency/year.
- [ ] Implement `data/quality.py`: row counts, OHLC checks, duplicates, gaps, outliers.
- [ ] Implement `data/calendar.py`: exchange sessions, crypto 24/7, UTC.
- [ ] Implement `data/universe.py`: PIT membership, liquidity filters, delisting handling.
- [ ] Add a `data_manifest.json` with source, date, checksum, row count.

### 5.2 Backtester

- [ ] `research/backtest.py`: vectorized portfolio simulation.
  - Inputs: target weights, prices, costs, calendar.
  - Outputs: equity curve, positions, trades, turnover, exposures.
  - Support: long/short, cash, leverage, per-asset caps, rebalance bands.
- [ ] `research/costs.py`: commissions, half-spread, slippage, funding, borrow.
- [ ] `research/metrics.py`: CAGR, vol, Sharpe, Sortino, Calmar, max DD, DD duration, hit rate, profit factor, turnover, exposure, VaR/CVaR.
- [ ] `research/report.py`: HTML/PDF tearsheet + CSV of trades.
- [ ] `research/trials.py`: log every trial (params, metrics, data version) to MLflow/SQLite.
- [ ] Unit tests for accounting invariants:
  - cash + market value = equity;
  - positions reconcile to fills;
  - no negative cash unless margin enabled;
  - weights sum to intended gross/net.

### 5.3 Baseline validation

- [ ] Reproduce buy-and-hold BTC, SPY, and 60/40.
- [ ] Reproduce a simple 12-month trend strategy on BTC and SPY.
- [ ] Compare to a known benchmark (e.g., SPY total return).
- [ ] Verify costs reduce returns in the expected direction.

### Deliverables
- Working data pipeline for BTC/ETH + SPY/QQQ + macro.
- Backtester with cost model and tearsheets.
- Baseline report showing buy-and-hold and trend.

### Exit criteria
- Same inputs → identical outputs (deterministic hash).
- Accounting invariants pass property-based tests.
- Costs and turnover are reported for every backtest.
- No look-ahead in the baseline trend strategy (verified by manual timestamp audit).

---

## 6. Phase 2 — Strategy research sprint (Weeks 4–8)

### 6.1 Trend (priority 1)

- [ ] Universe: BTC, ETH, SOL, SPY, QQQ, TLT, GLD, DBC.
- [ ] Signals: 1/3/6/12-month returns; 50/200-day MA; Donchian breakout.
- [ ] Position: long/flat and long/short; vol target 10–15%.
- [ ] Rebalance: daily vs weekly; rebalance bands.
- [ ] Costs: 5–10 bps stocks, 10–25 bps crypto, funding for perps.
- [ ] Walk-forward: train 3–5 years, test 6–12 months, roll.
- [ ] Stress: 2020 COVID, 2022 rate shock, 2024 yen carry unwind.

### 6.2 Crypto cross-sectional momentum (priority 2)

- [ ] Universe: top 20–50 liquid coins, PIT, exclude stablecoins/wrapped/leveraged.
- [ ] Signals: 1/3/6-month returns; skip last week; residual momentum vs BTC.
- [ ] Portfolio: long top quintile / short bottom (if perps), beta-neutral, vol-target.
- [ ] Rebalance: weekly; per-coin cap 5–10%; cluster cap.
- [ ] Costs: 15–25 bps/side + funding + borrow.
- [ ] Crash controls: vol scaling, trend filter, drawdown throttle.
- [ ] Delisted coins and exchange failures included.

### 6.3 Crypto carry/basis (priority 3, research only at first)

- [ ] Data: funding rates, perp/spot prices, futures basis, open interest.
- [ ] Signal: annualized funding/basis > threshold after fees.
- [ ] Portfolio: delta-neutral spot long + perp short; 2–3 venues; per-venue cap.
- [ ] Stress: funding flip, liquidation spike, exchange outage, stablecoin depeg.
- [ ] Counterparty limits: max 25–33% of capital per venue.

### 6.4 Validation for every candidate

- [ ] Walk-forward OOS.
- [ ] Purged K-fold / CPCV.
- [ ] Deflated Sharpe Ratio (trial count).
- [ ] PBO (CSCV).
- [ ] Cost stress at 2× and 3×.
- [ ] Parameter sensitivity (plateau, not spike).
- [ ] Subperiod stability (yearly Sharpe).
- [ ] Universe robustness (top 20 vs top 50; with/without small caps).
- [ ] Placebo/randomization test.

### Deliverables
- Research memo per strategy: hypothesis, data, results, risks, go/no-go.
- Validation report with DSR, PBO, cost stress.
- Frozen strategy spec (no more parameter changes without a new trial ID).

### Exit criteria (per strategy)
- OOS Sharpe > 0.5 net of 2× costs.
- PBO < 0.2.
- DSR > 0 (preferably > 0.95 confidence).
- Max DD within tolerance.
- At least 100 OOS trades (or 3+ years for slow strategies).
- Economic rationale documented.

---

## 7. Phase 3 — Portfolio + paper trading (Weeks 8–12)

### 7.1 Portfolio construction

- [ ] Combine strategies with risk parity / inverse-vol weights.
- [ ] Vol target at portfolio level (e.g., 10–12%).
- [ ] Correlation caps: max 0.7 between sleeves; cluster exposure limits.
- [ ] Per-asset cap: 5–10%; per-venue cap for crypto.
- [ ] Drawdown throttle: reduce gross exposure at −10%, −15%, −20%.
- [ ] Cash buffer: 5–10%.
- [ ] Rebalance bands to reduce turnover.

### 7.2 Execution

- [ ] `execution/broker.py`: abstract interface.
- [ ] `alpaca_broker.py`: account, positions, orders, fills, cancel, reconcile.
- [ ] `ccxt_broker.py`: Kraken/Coinbase/Binance testnet; order types; rate limits.
- [ ] `order_manager.py`: idempotent IDs, state machine, retries, partial fills.
- [ ] `reconciler.py`: compare broker positions to journal; alert on mismatch.
- [ ] `killswitch.py`: cancel all, flatten all, disable.
- [ ] Paper mode: same code path, `dry_run=True`.

### 7.3 Ops

- [ ] Scheduler: daily signal at a fixed UTC time; execution at market open or next bar.
- [ ] Telegram alerts: heartbeat, orders, fills, errors, drawdown.
- [ ] Streamlit dashboard: equity, positions, exposure, PnL, drawdown, recent orders.
- [ ] Logs: JSON, daily rotation, structured fields.
- [ ] Backups: nightly data + journal.

### Deliverables
- Paper trading system running daily.
- Dashboard and alerts.
- Runbook: start, stop, restart, kill, recover.

### Exit criteria
- 8 weeks paper trading (or 4 weeks if stable and low turnover).
- Paper performance within tolerance of backtest (e.g., slippage ≤ 1.5× model, tracking error < 3%).
- No operational incidents (duplicate orders, missed signals, reconciliation breaks).
- Kill switch tested.

---

## 8. Phase 4 — Small live (Weeks 12–20)

### Tasks

- [ ] Fund a separate account with **$5k–10k** (money you can lose).
- [ ] Trade-only API keys; withdrawals disabled; IP allowlist; 2FA.
- [ ] Start at **25–50% of intended risk** (e.g., 0.25–0.5% per trade).
- [ ] Daily reconciliation; weekly TCA (realized vs modeled slippage).
- [ ] Weekly performance review vs backtest; monthly risk review.
- [ ] Incident drills: API down, partial fill, duplicate order, stale data, exchange outage.
- [ ] Only scale after 3 months within limits.

### Exit criteria
- 3 months live, drawdown within 1.5× backtest max DD.
- Realized slippage ≤ 2× model.
- No unhandled operational incidents.
- Positive net PnL or acceptable risk-adjusted performance (Sharpe > 0.3 over the sample; don't over-interpret 3 months).

---

## 9. Phase 5 — AI, sentiment, second strategy (Weeks 20–26)

### Tasks

- [ ] News/GDELT pipeline with entity linking.
- [ ] FinBERT baseline sentiment; LLM event extraction.
- [ ] Sentiment features as overlay (risk reduction at extremes, event filters).
- [ ] LightGBM cross-sectional model on 50–100 features.
- [ ] Purged CV + CPCV + SHAP stability.
- [ ] Compare to simple baseline; require incremental OOS value.
- [ ] Add US equity momentum/quality sleeve if data (PIT fundamentals/delisted) is ready.
- [ ] Shadow mode for AI signals for 3–6 months before capital.

### Exit criteria
- AI/sentiment adds **incremental** OOS value after costs, not just a prettier backtest.
- No look-ahead in prompts/data.
- Model registry and rollback in place.

---

## 10. First 30 / 60 / 90 days (concrete)

### Days 1–7
1. Install `uv` + Python 3.12.
2. Create repo and env.
3. Alpaca paper account + keys.
4. Download BTC/ETH daily + hourly.
5. Download SPY/QQQ daily.
6. Build data audit notebook.
7. Write data dictionary.

### Days 8–30
1. Build normalized Parquet store + DuckDB.
2. Implement backtester + costs + metrics.
3. Reproduce buy-and-hold and 12-month trend.
4. Run data quality checks.
5. Write first research memo (trend).
6. Set up MLflow + Optuna.
7. Set up Telegram alerts (heartbeat).

### Days 31–60
1. Trend walk-forward + DSR/PBO.
2. Crypto XSMOM data/universe.
3. XSMOM walk-forward + cost stress.
4. Paper executor for Alpaca + ccxt.
5. Dashboard v1.
6. Decide first paper strategy.

### Days 61–90
1. Paper trade 4–8 weeks.
2. TCA and slippage analysis.
3. Add second strategy (carry research or equity momentum data).
4. Runbook + incident drills.
5. Go/no-go for small live.

---

## 11. Testing strategy

### Unit tests
- Indicators (known values, warm-up periods).
- Cost model (commissions, spread, funding).
- Position sizing (vol target, caps).
- Order state machine (submit, partial, cancel, reject).
- PnL/accounting.

### Property-based tests (Hypothesis)
- `cash + Σ(position × price) = equity` at all times.
- `Σ fills = position` for each asset.
- No negative cash unless margin enabled.
- Weights sum to target gross/net.
- Rebalancing is idempotent when weights are within bands.

### Integration tests
- Recorded API fixtures (Alpaca, ccxt, FRED).
- End-to-end backtest on a small dataset.
- Paper order lifecycle with a mock broker.
- Reconciliation after a simulated restart.

### Replay tests
- Same data + config → same hash.
- Live signals match backtest signals for the same timestamp.
- After a crash, restart reconciles without duplicate orders.

### Chaos tests
- Network timeout during order submission.
- Partial fill.
- Duplicate fill event.
- Stale price/data.
- Broker returns 500.
- Exchange maintenance.
- Clock skew.

### CI
- `ruff`, `mypy`, `pytest`.
- Backtest smoke test on a tiny dataset (< 60s).
- No secrets in repo (gitleaks).

---

## 12. Deployment and runbook

### Recommended deployment

**Option A: Native Windows (simplest)**
- Python 3.12 via `uv`.
- Task Scheduler for daily jobs.
- NSSM for long-running services (optional).
- Alpaca/IB Gateway native.
- Pros: easy; cons: Windows updates, sleeps, less robust.

**Option B: WSL2 Ubuntu (recommended for production)**
- Ubuntu 24.04 (already installed).
- Python 3.12, systemd services, cron.
- Docker Compose optional for Prometheus/Grafana/MLflow.
- Access Windows files via `/mnt/c` (slow) — keep data in WSL filesystem.
- Pros: stable, Linux tooling; cons: extra setup.

**Do not** run production from a Jupyter notebook or an IDE debugger.

### Daily runbook

```text
06:00 UTC  ingest data → quality report → feature build
06:15 UTC  compute signals → target weights → risk checks
06:30 UTC  reconcile broker positions → generate orders
06:35 UTC  execute (stocks at open; crypto per schedule)
07:00 UTC  confirm fills → update journal → alert summary
Every 5m   heartbeat, data freshness, order errors
Weekly     TCA, performance review, backup verify
Monthly    risk review, strategy decay check
```

### Start/stop

```bash
# start
uv run python -m tradingbot.ops.scheduler --config config/base.yaml

# paper
uv run python -m tradingbot.scripts.run_paper --strategy trend

# live (after gates)
uv run python -m tradingbot.scripts.run_live --strategy trend --confirm
```

### Incident playbook

| Incident | Action |
|---|---|
| Data stale/missing | Stop new orders; alert; use last known good; investigate |
| Broker API down | Retry with backoff; do not duplicate; alert; flatten if prolonged |
| Position mismatch | Stop trading; reconcile manually; do not "fix" with market orders |
| Runaway order loop | Kill switch: cancel all, flatten, disable API key |
| Drawdown > limit | Reduce gross exposure; review; possibly stop |
| Exchange insolvency rumor | Withdraw excess; reduce exposure; diversify |
| Model/strategy decay | Freeze; review; retire or revalidate |

---

## 13. Monitoring and alerting

### Metrics
- Heartbeat (last successful run).
- Data freshness (last bar timestamp per asset).
- Signal count and target gross/net.
- Order count, reject rate, latency.
- Realized slippage vs model.
- PnL, drawdown, exposure, turnover.
- API error rate and rate-limit hits.
- Reconciliation breaks.

### Alerts (Telegram/email)
- Critical: no heartbeat > 5 min; position mismatch; order rejected; drawdown > limit; API auth failure.
- Warning: stale data; slippage > 2× model; turnover spike; correlation spike; funding flip.
- Info: daily summary; weekly report.

### Dashboard
- Equity curve vs backtest.
- Current positions and weights.
- Exposure by asset/class/venue.
- Drawdown and risk limits.
- Recent orders/fills.
- Data freshness.

---

## 14. Security

- API keys: trade-only, no withdrawals, IP allowlist, 2FA.
- Separate accounts/keys per strategy or sleeve.
- Secrets in environment/Windows Credential Manager; never in git.
- Encrypt backups; test restore.
- Keep the trading PC patched but schedule updates outside market hours.
- Use a dedicated user account for trading.
- Monitor for unauthorized API activity.
- Don't share account credentials or 2FA codes.
- Beware of phishing and fake "support" accounts.

---

## 15. Time and cost estimate

### Part-time (10–15 h/week)

| Phase | Weeks | Hours |
|---|---|---|
| 0 | 1 | 10–15 |
| 1 | 3 | 40–50 |
| 2 | 4 | 50–60 |
| 3 | 4 | 40–50 |
| 4 | 8 | 40–60 (monitoring) |
| 5 | 6 | 50–70 |
| **Total** | **26** | **230–305** |

### Full-time

- 10–12 weeks to paper + small live, assuming no major blockers.

### Cash costs

- Starter: **$0–30/mo**.
- Serious: **$150–450/mo**.
- Hardware: **$180–550** one-time (UPS/backup).
- Trading capital: **$5k–25k** at risk.

---

## 16. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Overfitting | High | High | DSR/PBO, walk-forward, trial counting, simple models |
| Look-ahead | High | High | PIT store, timestamp audits, code review |
| Survivorship | High | High | Delisted assets, PIT universe |
| Execution bug | Medium | High | Tests, paper, reconciliation, kill switch |
| Broker/exchange failure | Medium | High | Multi-venue, cash buffer, alerts, manual fallback |
| Counterparty insolvency | Low–Medium | High | Limit exchange balances, regulated venues, diversify |
| Strategy decay | High | Medium | Monitor rolling Sharpe, retire early |
| Data cost creep | Medium | Medium | Start free, buy only for validated hypotheses |
| Regulatory/tax | Medium | Medium | Professional advice, trade log, jurisdiction check |
| Psychological | Medium | High | Rules, small size, automation, no overriding |
| Cybersecurity | Low–Medium | High | Trade-only keys, 2FA, IP allowlist, separate account |

---

## 17. Decision gates (summary)

| Gate | Requirement | If fail |
|---|---|---|
| G0 Data | Complete, PIT, delisted included, quality report | Fix data; do not proceed |
| G1 Reproducibility | Same hash; tests pass; no look-ahead | Fix code; re-run |
| G2 Strategy | OOS Sharpe > 0.5 net 2× costs; PBO < 0.2; DSR > 0 | Retire or revise hypothesis |
| G3 Paper | 8 weeks; slippage ≤ 1.5× model; no incidents | Extend paper; fix ops |
| G4 Live small | 3 months; DD ≤ 1.5× backtest; no incidents | Reduce size; review |
| G5 Scale | 6–12 months consistent; capacity OK | Keep small or retire |

---

## 18. Definition of done (v1)

- [ ] Data pipeline runs daily, unattended, with quality checks.
- [ ] Backtester reproduces results exactly from a clean checkout.
- [ ] Two strategies pass G2; one passes G3.
- [ ] Paper trading runs 8+ weeks with alerts and dashboard.
- [ ] Live small runs 3+ months with reconciliation and TCA.
- [ ] Runbook and incident playbook are written and tested.
- [ ] Backups and secrets are secured.
- [ ] You can explain the edge, the risks, and the kill criteria in one page.

---

## 19. What to defer

- Multi-asset netting across brokers.
- Options/futures overlays.
- Intraday/tick strategies.
- RL/LLM autonomous agents.
- Multi-user/UI/productization.
- Tax optimization beyond a clean trade log.

Build the boring core first. The fancy stuff is worthless without it.
