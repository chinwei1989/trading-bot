# Trade decisions and operations logs

## Purpose

The dashboard now has two read-only evidence surfaces:

1. **Trade decisions & reasoning** on `/holdings`: one card per open spot
   position showing the current target weight, held weight, drift, stance, and
   the facts used to classify it.
2. **Logs** on `/logs`: bounded tails of allowlisted operational log files,
   with conservative secret redaction.

Neither surface can place, cancel, or modify an order. They are generated from
paper artifacts only.

## Decision snapshot

`scripts/build_decisions.py` writes:

```text
artifacts/decisions/latest.json
```

For each dashboard lane it combines:

- the latest deterministic strategy target, or the latest AI decision record;
- the current paper position and mark price;
- the latest order-journal rows;
- small strategy facts such as price versus the 200-day SMA, 60-day momentum,
  Donchian distance, or reversal z-score.

The stance is classified with a 0.50% minimum rebalance band (or the broker's
minimum notional as a weight, if larger):

| Stance | Meaning |
|---|---|
| `HOLD` | Target and held weight are inside the rebalance band. |
| `ADD` | The next rebalance would increase exposure. |
| `TRIM` | The next rebalance would reduce exposure. |
| `EXIT` | The target is zero but the position is still open. |
| `ENTER` | A non-zero target exists with no current position. |
| `FLAT` | Neither a target nor a position exists. |

The current snapshot is displayed only for open positions. Recent orders are
listed separately with their current decision context.

### Historical limitation

Older paper orders predate this snapshot builder. Their displayed rationale is
a **reconstructed current stance**, not a recovered original rationale. The UI
labels the snapshot generation time and the page copy says the decisions are
read-only. New runs should be understood the same way: the snapshot is an
explanation of the latest target and position, not an immutable audit record of
the moment the order was submitted.

## Logs

`src/tradingbot/ops/logs.py` has a fixed allowlist and never reads arbitrary
paths from the browser. Each file contributes at most 200 lines and is read
from at most the final 2 MB. Redaction covers:

- key/value or JSON fields named `api_key`, `secret`, `token`, `password`,
  `authorization`, `bearer`, `private_key`, `client_secret`, and `access_key`;
- Telegram bot tokens embedded in URLs;
- common provider token prefixes such as `sk-`, `ghp_`, and `xoxb-`.

The log payload is part of the same dashboard JSON as the positions and
performance data. On localhost the FastAPI adapter re-reads the bounded tails;
the Vercel snapshot contains the tails captured when the snapshot was built.
Absolute repository and home paths are replaced with `<repo>` and `~` before
the payload leaves the Python process.

## Refresh

The daily health task runs the decision builder after readiness/evidence
generation:

```powershell
uv run python scripts/build_decisions.py
```

The Vercel snapshot export also refreshes the decision artifact automatically:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/export_frontend_snapshot.ps1
```

## Safety boundaries

- No external signal service is ingested.
- No broker authority is added.
- No live-capital gate changes are implied by a decision card or log line.
- Raw `.env` values and API keys are never included in the dashboard payload.
