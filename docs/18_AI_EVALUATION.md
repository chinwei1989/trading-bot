# 18 — AI Agent Evaluation Scorecard

**Purpose:** measure the AI paper sleeve separately from the deterministic campaign. It is not a backtest and cannot promote a strategy to live.

---

## 1. Command

```powershell
uv run python -m tradingbot --config config/ai_agent.yaml ai-evaluate
```

Outputs:

```text
artifacts/ai/reports/scorecard.json
artifacts/ai/reports/scorecard.md
```

The Streamlit `AI agent` view also shows the scorecard.

---

## 2. What is measured

| Area | Metrics |
|---|---|
| Paper account | equity, total return, CAGR, vol, Sharpe, Sortino, max drawdown, average gross, cash |
| Benchmarks | deterministic trend and XSMOM paper accounts |
| Provider | decisions, fallback rate, dry runs, errors, mean latency, provider mix |
| TCA | fills, weighted/median/p95 slippage, notional |
| Confidence calibration | next-session return and hit rate by confidence bucket |

The confidence calibration is intentionally simple: it takes each recorded target-weight decision, applies it to the next close-to-close bar, and groups outcomes by the model’s stated confidence. It is before execution costs and is not a PnL claim.

---

## 3. Status rules

| Status | Meaning |
|---|---|
| `insufficient_data` | fewer than 20 unique paper days |
| `fallback_only` | enough data, but essentially every decision is the labelled fallback |
| `ok` | at least 20 paper days and at least one non-fallback decision |

A `fallback_only` scorecard is **not AI evidence**, even if the equity curve is positive.

---

## 4. Current state (23 Oct 2026)

```text
status=insufficient_data
paper days=1
fallback rate=0%
provider decisions=1
equity=$10,000.00
```

The 10 historical Jev dry runs completed successfully (`jev-1.14.0`); 3 of 10 produced a 20% target gross, the rest stayed in cash. The paper account was then reset to a clean $10,000 and the daily `TradingBotAIPaper` task was scheduled for 07:15. The scorecard correctly refuses to call one day of data evidence.

---

## 5. Minimum evidence before promotion

- 56+ unique paper days.
- < 5% fallback/error decisions for an AI claim.
- Positive net return after costs, or a clearly measured risk reduction.
- Confidence calibration reported with sample counts.
- TCA within the model assumption.
- No unexplained reconciliation breaks.
- Provider/model version, prompt/schema, and cost are frozen and logged.
- Deflated Sharpe / PBO evaluated on the actual decision history, not just the initial backtest.

Until then the AI sleeve remains paper-only. The live gate also hard-fails before these thresholds; see `artifacts/LIVE_GATE.md`.
