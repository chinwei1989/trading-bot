# 17 — Jev Evaluation for the AI Pipeline

**Explored:** 23 Oct 2026  
**Vendor:** TypeSafe AI  
**Decision:** optional typed-decision provider for the separate paper pipeline. Not an execution engine. Not enabled without an API key. Not validated for trading skill.

---

## 1. What Jev actually is

Jev is TypeSafe AI's first **System One model**. It is not a chat model and does not generate strings. You send:

- a `state` (text, JSON object, or array), and
- one or more typed questions (`choice`, `score`, `noul`),

and it returns typed answers with probabilities and, for some types, confidence.

```json
{
  "model": "jev-latest",
  "state": {"asset": "BTC", "trend": "above 200d", "vol": 0.55},
  "questions": {
    "exposure": {
      "type": "choice",
      "instructions": "Choose exposure for this asset.",
      "criteria": {
        "long": "Positive trend and acceptable risk",
        "flat": "No clear edge or unfavorable risk"
      }
    }
  }
}
```

```json
{
  "model": "jev-1.14.0",
  "answers": {
    "exposure": {
      "type": "choice",
      "choice": "long",
      "confidence": 0.82,
      "probabilities": {"long": 0.82, "flat": 0.18}
    }
  },
  "usage": {"input_tokens": 120, "output_tokens": 12}
}
```

This maps well to a constrained trading decision: choose a direction, score regime risk, or gate an action. It maps poorly to "write a thesis" or "use tools to research the market."

---

## 2. Facts relevant to this repo

| Item | Detail |
|---|---|
| Endpoint | `POST https://api.typesafe.ai/v1/systemone` |
| Auth | `Authorization: Bearer $TYPESAFE_API_KEY` |
| Model IDs | `jev-1.14.0`, `jev-1.13.0` |
| Alias | `jev-latest` (docs currently map it to the stable 1.13.0; responses return the versioned model) |
| Input | Text / JSON / array of text; no audio or video |
| Context | 64k per request, 32k per question; 262k with the long-context header |
| Output | Typed answers; no generated prose |
| Price | $42 per billion input tokens / $0.042 per million; output currently free |
| Speed | Vendor reports roughly 70–500 ms end-to-end |
| Hosting | Hosted API only; not a local model |
| Data | Vendor says customer requests/responses are not used for training; ZDR is an enterprise option |
| Rate limits | Per organization; 429 with `retry-after` |

**Cost for this pipeline:** a daily context of a few thousand tokens costs a fraction of a cent. Even several calls per day is under a few dollars per year. The cost is not the blocker. The blocker is whether the decisions add value after costs and out-of-sample testing.

---

## 3. Fit for an AI trading agent

| Use | Fit | Assessment |
|---|---|---|
| Per-asset `long` / `flat` / `short` | Strong | Exactly a typed `choice` question |
| Market regime (`risk_on` / `neutral` / `risk_off`) | Strong | A second `choice` question in the same request |
| Risk gate ("is this state internally inconsistent?") | Strong | `noul` / `score` is a natural fit |
| Confidence-based sizing | Strong | Confidence can gate or scale the deterministic policy |
| Sentiment classification of a post | Medium | Works, but needs a lawful, reliable X/news feed and point-in-time storage |
| Multi-step research with tools | Weak | Jev has no tool calls and no agent loop; that belongs to the surrounding code |
| Explaining a decision | Weak | Jev does not generate prose; use a separate writer or a template |
| Order execution | **No** | Execution stays deterministic and auditable |
| Risk veto | **No** | The policy layer owns this |
| Live promotion | **No** | Evidence gates own this |

Jev is therefore a **decision function inside an agent**, not the agent itself. The agent is the loop: context builder → provider → schema validation → policy → execution → audit.

---

## 4. How it is wired here

`src/tradingbot/ai/providers.py` implements `JevProvider`.

For each cycle it sends:

- the point-in-time market snapshot (price features, breadth, portfolio, constraints),
- a `regime` choice question,
- one choice question per asset,
- optional macro and sentiment blocks when the data files exist.

The typed answers become `AgentDecision` actions. The deterministic policy then:

1. drops low-confidence actions,
2. rejects shorts unless explicitly allowed,
3. sizes longs by inverse volatility,
4. applies regime gross caps,
5. enforces per-asset, cash, and turnover limits,
6. passes the result through the risk checks.

Jev never sees a broker key and never writes an order.

---

## 5. What the vendor claims vs. what is proven

TypeSafe claims large speed/cost advantages and "zero hallucinations" in the sense of type-safe outputs. Those are claims about **typed output validity**, not about trading profitability.

There is a wave of "Jev trading bot" content on YouTube, Reddit, and Medium. It is not evidence:

- no audited track record,
- no point-in-time data methodology,
- no out-of-sample/cost-adjusted statistics,
- no independent replication,
- often paper trading over short windows.

We treat Jev as an untested decision model. It must beat the deterministic baseline after costs, over multiple regimes, before it can influence capital.

---

## 6. Risks and limitations

1. **Hosted dependency.** Jev is not local. Market features and paper positions leave the machine. Do not send secrets.
2. **Paid API.** It conflicts with the original "no paid services" constraint. It is optional; the pipeline fails closed without a key.
3. **Alias drift.** `jev-latest` can move. Log the returned model ID and pin a version when thresholds are tuned.
4. **Calibration is not edge.** Good probabilities do not imply a profitable strategy.
5. **English-centric.** The vendor says English is strongest; test any non-English sentiment input.
6. **No tools.** It cannot fetch prices, browse X, or inspect a broker. The surrounding code must provide clean, point-in-time state.
7. **State quality dominates.** Bad features, lookahead, or stale data will produce confident bad decisions.
8. **No narrative.** Auditability comes from typed decisions and policy notes, not a persuasive rationale.
9. **Rate limits and outages.** The pipeline must hold/no-trade, not silently switch strategies.
10. **Regulatory/broker risk.** AI does not change market-risk, licensing, or tax obligations.

---

## 7. Decision

Use Jev as an **optional typed decision provider** in the separate AI paper pipeline:

- `provider: jev`
- `paper_only: true`
- `fallback: none` by default
- no live path
- full audit of request, response, model version, latency, usage, policy, and orders
- compare against deterministic trend/XSMOM over at least 8 weeks
- promote only after the same DSR/PBO, cost, drawdown, and operational gates used for the deterministic strategies

If Jev does not beat the baseline after costs, keep it as a research tool and do not give it capital.

---

## 8. Post-evaluation smoke test

On 23 Oct 2026, after configuring `TYPESAFE_API_KEY`, the adapter ran 10 historical point-in-time dry decisions through `jev-latest` (responded as `jev-1.14.0`):

- 10/10 returned valid typed answers.
- 3/10 produced a 20% target gross; 7/10 stayed in cash.
- Overall confidence ranged from 0.00 to 0.73.
- Mean latency was about 330 ms.
- No orders were sent.
- The clean paper account was reset to $10,000 afterward.

This proves the integration works. It says nothing about profitability.

## 9. Sources

- TypeSafe AI home: https://typesafe.ai/
- Introduction: https://docs.typesafe.ai/introduction
- System One API reference: https://docs.typesafe.ai/api/system-one
- Models, context, pricing, aliases: https://docs.typesafe.ai/models
- Introducing System One Models & Jev: https://typesafe.ai/blog/introducing-system-one-models-and-jev
- TypeSafe API console: https://console.typesafe.ai/
- LiteLLM pass-through docs: https://docs.litellm.ai/docs/pass_through/typesafe
- Awesome Jev list (ecosystem, not evidence): https://github.com/yibie/awesome-jev

Vendor claims are reported as claims, not independently verified here.
