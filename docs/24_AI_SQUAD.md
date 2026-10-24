# 24 — AI Squad Memory

**Saved:** 24 Oct 2026  
**Status:** seven-agent squad built, tested, and scheduled daily at 07:25 local; paper-only; 1 paper day initialized.
**Model:** all seven agents currently use **Jev** typed calls. No other LLM is used.
**Architecture:** `docs/25_AI_SQUAD_ARCHITECTURE.md`.

This document is the persistent project memory for the AI squad decision. The
squad is a separate paper lane. It cannot touch the deterministic quant account
and has no live execution path.

---

## 1. The hierarchy

```text
DETERMINISTIC QUANT LANE — Python only, no LLM
data -> trend/XSMOM/breakout/reversal -> meta allocator
     -> deterministic risk -> paper broker

AI SQUAD LANE — separate paper account
data
  -> macro_analyst
  -> trend_analyst
  -> xsmom_analyst
  -> sentiment_analyst
  -> risk_critic
  -> execution_analyst
  -> chair
  -> deterministic squad guardrail
  -> deterministic policy/risk
  -> separate paper broker
```

### Is Jev the decision maker?

Jev is the **model behind every AI agent**. Each agent is a separate,
role-scoped Jev request with its own typed questions. The chair is the AI agent
that emits the final portfolio decision.

But the chair is **not** the final authority on capital:

- the deterministic squad guardrail enforces risk vetoes and execution blocks;
- the deterministic policy owns sizing, gross/net caps, cash, turnover, and
  confidence gating;
- the deterministic risk checks can still reject the targets;
- the paper broker is the only execution path.

The deterministic quant lane does not call Jev at all.

### Will we use other LLM providers?

Not in this build. All seven roles use `JevProvider.ask()`.

That is intentional: Jev returns typed choices, is cheap at this scale, and
avoids free-form agent chat. A future version could assign a different model to
one role (for example, a local model for sentiment), but that should be a
separate experiment with the same blackboard and policy controls. It is not
needed for the current squad.

---

## 2. Roster

| Stage | Agent | Job | Output |
|---|---|---|---|
| 1 | `macro_analyst` | Macro/regime backdrop | `risk_on / neutral / risk_off` |
| 2 | `trend_analyst` | Time-series trend | per-asset `long / flat` |
| 3 | `xsmom_analyst` | Cross-sectional relative strength | per-asset leader/follower choice |
| 4 | `sentiment_analyst` | Sentiment from a supplied feed | `supportive / neutral / negative / unavailable` |
| 5 | `risk_critic` | Attack the proposals | per-asset `approve / reduce / veto` |
| 6 | `execution_analyst` | Liquidity and feasibility | per-asset `allow / reduce / block` |
| 7 | `chair` | Synthesise every memo | final regime + per-asset `long / flat` |

The sentiment agent **abstains without an LLM call** when
`data/normalized/sentiment.parquet` is absent. The macro, trend, XSMOM, risk,
execution, and chair agents always run.

---

## 3. Shared blackboard

Each run writes:

```text
artifacts/ai_squad/squad/<run_id>/
  01_macro.json
  02_trend.json
  03_xsmom.json
  04_sentiment.json
  05_risk.json
  06_execution.json
  07_chair.json
  manifest.json
```

Each memo contains:

- agent and stage;
- model ID, usage, latency;
- regime or summary;
- typed choices and per-choice confidence;
- notes;
- raw typed answers.

Later agents receive the earlier memos in their Jev state under `squad.memos`.
There is no free-form group chat, no hidden chain-of-thought sharing, and no
tool access.

---

## 4. Guardrails

- Missing risk answer → **veto** (fail closed).
- Missing execution answer → **block** (fail closed).
- Missing chair answer → **flat**.
- Risk `veto` → final action is flat.
- Execution `block` → final action is flat.
- Risk or execution `reduce` → chair confidence is halved for each reduction;
  the policy layer may still reject the action.
- Macro, risk, or execution stress downgrades a chair `risk_on` regime to
  `neutral`.
- Shorts are flattened unless policy explicitly allows them.
- Risk vetoes and execution blocks set `force_rebalance`, so the generic
  “low confidence means hold current” rule cannot silently ignore them. The
  turnover cap may stage the exit rather than force an unlimited one-day
  liquidation.
- Sentiment is advisory only; it cannot size, veto, or execute.

---

## 5. Cost and latency

The squad makes **six to seven Jev calls per cycle**:

- six when sentiment data is unavailable;
- seven when a sentiment feed exists.

Everything else uses the same point-in-time context. Jev pricing is per input
token; a few thousand tokens per call is a fraction of a cent per day. The
blocker is evidence quality, not API cost.

---

## 6. Commands

```powershell
# Decision only; no orders
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

`TradingBotAISquad` is registered for 07:25 local, after the deterministic
campaign (07:00), single-provider Jev lane (07:15), and sleeve campaign (07:20),
and before the 07:30 health check. It has started its own paper-day clock and is
included in campaign health.

The first actual paper cycle initialized **$10,000** and made no orders because
the chair chose flat for all eight assets. The dashboard has a dedicated
**AI squad** view and the Vercel lite page has a separate squad status line.

**Stage 1 history:** the original three-agent version (`trend -> risk -> chair`)
completed one real three-call dry run on 24 Oct 2026. The full seven-agent
version replaced it after the user asked to build the rest.

**Full-roster smoke run:** 24 Oct 2026 completed with `jev-1.14.0`; sentiment
abstained because no feed exists, so six Jev calls were made and all seven memos
were written. The chair chose flat, risk issued several vetoes, and execution
blocked several assets. No orders were sent. This validates orchestration, not
trading skill.

---

## 7. What remains intentionally absent

- No live execution path.
- No broker credentials for any agent.
- No autonomous web browsing or shell access.
- No master LLM that can bypass policy.
- No real X/news feed; the sentiment agent reads only a prepared snapshot.
- No per-agent model routing yet; all agents use Jev.
- No automatic promotion from squad paper to live.

The deterministic strategy freeze and the 56-day evidence window are unchanged.
The live gate remains `NO_GO`.
