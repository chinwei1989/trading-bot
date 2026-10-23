# 24 — AI Squad Memory (Stage 1)

**Saved:** 24 Oct 2026  
**Status:** built, tested, paper-only. The squad is not scheduled and is not approved for live capital.  
**Stage 1 roster:** **trend analyst → risk critic → chair** (three typed Jev calls).

This document is the persistent project memory for the AI squad decision. Do not add the remaining agents until the user has reviewed stage 1 and explicitly asked for the expansion.

---

## 1. Durable decisions

- The deterministic quant lane stays separate and unchanged:
  `strategies → meta allocator → deterministic risk → paper broker`.
- The AI squad is a **separate paper account** under `artifacts/ai_squad/`.
- The squad does **not** control the deterministic account and has **no live execution path**.
- Every agent has one narrow job. Agents share structured memos through a blackboard; they do not chat freely.
- The risk critic can **veto** or **reduce** a proposal. Code enforces the veto before the existing policy layer.
- The existing deterministic policy still owns sizing, gross/net caps, cash, turnover, and confidence gating.
- No agent receives broker credentials.
- Stage 1 uses Jev only. Hosted API cost is three calls per cycle; no local model is required.
- Fallback is `none`: an AI outage fails closed and holds existing positions.

---

## 2. Stage 1 architecture

```text
point-in-time market context
        │
        ▼
┌──────────────────┐
│ trend_analyst    │  typed choices per asset: long / flat
└────────┬─────────┘
         │ memo: trend
         ▼
┌──────────────────┐
│ risk_critic      │  typed choices: approve / reduce / veto
└────────┬─────────┘
         │ memo: risk
         ▼
┌──────────────────┐
│ chair            │  final regime + long / flat per asset
└────────┬─────────┘
         │
         ▼
deterministic squad guardrail (veto/reduction enforcement)
         │
         ▼
AgentDecision → deterministic policy → risk → paper broker
```

### Shared blackboard

Each run writes:

```text
artifacts/ai_squad/squad/<run_id>/
  01_trend.json
  02_risk.json
  03_chair.json
  manifest.json
```

Each memo contains the agent name, model, typed choices, per-choice confidence, usage, latency, and raw typed answers. The risk memo receives the trend memo; the chair receives both. The model never gets a free-form group chat.

### Guardrails

- Missing risk answer → **veto** (fail closed).
- Missing chair answer → **flat**.
- Risk `veto` → final action is flat.
- Risk `reduce` → chair confidence is halved; the policy layer may still reject it.
- Risk `risk_off` + chair `risk_on` → regime is downgraded to `neutral`.
- Shorts are flattened unless policy explicitly allows them.
- When the squad is deliberately flat or a risk veto exists, the decision sets
  `force_rebalance`; this stops the generic “low confidence means hold current”
  rule from silently ignoring a veto. The existing turnover cap can still stage
  the exit rather than forcing an unlimited one-day liquidation.

---

## 3. Files

| File | Purpose |
|---|---|
| `src/tradingbot/ai/squad.py` | Three agents, blackboard, typed-question prompts, guardrail |
| `src/tradingbot/ai/providers.py` | `JevProvider.ask()` generic typed-question adapter; `squad` provider registration |
| `config/ai_squad.yaml` | Separate $10,000 paper account and `artifacts/ai_squad/` paths |
| `tests/test_ai_squad.py` | Veto, reduction, memos, fail-closed, provider registration |
| `docs/24_AI_SQUAD.md` | This memory note |

The artifact directory is configurable with `agent.artifacts_dir`. The default remains `artifacts/ai`, so the existing single-provider Jev pipeline and dashboard are unchanged.

---

## 4. Commands

```powershell
# Decision only; three Jev calls; no orders
uv run python -m tradingbot --config config/ai_squad.yaml ai-run --dry-run

# A real squad paper cycle
uv run python -m tradingbot --config config/ai_squad.yaml ai-run

# Scorecard for the separate squad account
uv run python -m tradingbot --config config/ai_squad.yaml ai-evaluate

# Inspect the latest squad report
uv run python -m tradingbot --config config/ai_squad.yaml ai-status

# Wrapper with logs
powershell -ExecutionPolicy Bypass -File scripts/run_ai_squad.ps1 -DryRun
```

No scheduled task has been registered. The existing `TradingBotAIPaper` task still runs the single-provider Jev lane at 07:15. The squad account starts empty and must accumulate its own paper days.

**Smoke run:** one real three-call dry run completed on 24 Oct 2026 (`jev-1.14.0`, no orders). The trend analyst and chair chose flat for all eight assets; the risk critic approved. The run produced `01_trend.json`, `02_risk.json`, `03_chair.json`, and `manifest.json`. This confirms the typed three-stage wiring, not trading skill.

---

## 5. What is deliberately not built yet

The user asked to start with three agents and be asked before building the rest. Do not add these without explicit approval:

- Macro/regime analyst
- Sentiment/news analyst
- Cross-sectional momentum analyst
- Execution/TCA agent
- Any master agent with broker access
- Any live execution path

The next expansion should be evaluated against the three-agent squad, not just against the deterministic baseline. Suggested comparison:

| Variant | Purpose |
|---|---|
| Single Jev (`config/ai_agent.yaml`) | Existing baseline |
| Three-agent squad (`config/ai_squad.yaml`) | Stage 1 |
| Future five-agent squad | Only after stage 1 has enough paper evidence |

Metrics to compare: paper days, return, Sharpe, max drawdown, turnover, TCA, risk-veto rate, fallback rate, latency, token cost, calibration, and agreement across agents.

---

## 6. Promotion boundary

The squad is **research/paper only**. It cannot influence live capital. The live gate remains `NO_GO`, and AI live execution is not implemented. No result from the squad should change the deterministic strategy freeze or the 56-day evidence window.
