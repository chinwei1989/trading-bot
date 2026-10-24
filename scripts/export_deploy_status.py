"""Export a small read-only status snapshot for the Vercel lite dashboard."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deploy" / "status.json"

CAMPAIGNS = {
    "trend": Path("artifacts/performance_trend.jsonl"),
    "xsmom": Path("artifacts/performance_xsmom.jsonl"),
    "breakout": Path("artifacts/performance_breakout.jsonl"),
    "reversal": Path("artifacts/performance_reversal.jsonl"),
    "meta": Path("artifacts/performance_meta.jsonl"),
    "ai": Path("artifacts/ai/performance.jsonl"),
    "intraday": Path("artifacts/intraday/performance.jsonl"),
    "ai_options_30m": Path("artifacts/ai_options_30m/performance.jsonl"),
}


def _json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _performance(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not rows:
        return None
    rows.sort(key=lambda row: str(row.get("timestamp", "")))
    last = rows[-1]
    days = len({str(row.get("timestamp", ""))[:10] for row in rows})
    return {
        "equity": last.get("equity"),
        "timestamp": last.get("timestamp"),
        "days": days,
        "mode": last.get("mode"),
    }


def main() -> int:
    campaigns = {
        name: _performance(ROOT / path)
        for name, path in CAMPAIGNS.items()
    }
    health = _json(ROOT / "artifacts" / "CAMPAIGN_HEALTH.json")
    gate = _json(ROOT / "artifacts" / "LIVE_GATE.json")
    ai_scorecard = _json(ROOT / "artifacts" / "ai" / "reports" / "scorecard.json")
    ai_squad = _performance(ROOT / "artifacts/ai_squad/performance.jsonl")
    ai_squad_scorecard = _json(
        ROOT / "artifacts" / "ai_squad" / "reports" / "scorecard.json"
    )
    options_evidence = _json(
        ROOT / "artifacts" / "options_evidence" / "latest.json"
    )
    options_live_gate = _json(ROOT / "artifacts" / "OPTIONS_LIVE_GATE.json")
    readiness = _json(ROOT / "artifacts" / "READINESS.json")
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "local snapshot",
        "gate": gate,
        "health": health,
        "campaigns": campaigns,
        "ai_scorecard": ai_scorecard,
        "ai_squad": ai_squad,
        "ai_squad_scorecard": ai_squad_scorecard,
        "options_evidence": options_evidence,
        "options_live_gate": options_live_gate,
        "readiness": readiness,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
