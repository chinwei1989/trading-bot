"""Read-only readiness summary for paper and live operations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.options.live_gate import build_options_live_gate


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def build_readiness(root: Path) -> dict[str, Any]:
    self_eval = _load_json(root / "artifacts" / "SELF_EVAL.json")
    health = _load_json(root / "artifacts" / "CAMPAIGN_HEALTH.json")
    live_gate = _load_json(root / "artifacts" / "LIVE_GATE.json")
    options = _load_json(root / "artifacts" / "options_evidence" / "latest.json")
    paper = options.get("paper", {}) if options else {}
    try:
        options_live_gate = build_options_live_gate(root)
    except Exception as exc:
        options_live_gate = {
            "status": "missing",
            "failed": [f"{type(exc).__name__}: {exc}"],
        }
    blockers: list[str] = []
    if not self_eval:
        blockers.append("self-evaluation has not been run")
    elif self_eval.get("status") != "PASS":
        blockers.append("code self-evaluation is not PASS")
    if not health or health.get("status") != "OK":
        blockers.append("campaign health is not OK")
    if not live_gate:
        blockers.append("live gate has not been run")
    elif live_gate.get("status") != "GO":
        blockers.append("live gate is NO_GO")
    if not options:
        blockers.append("options evidence has not been generated")
    else:
        blockers.append(
            f"forward options evidence has {paper.get('paper_days', 0)} of 56 paper days"
        )
    if options_live_gate.get("status") != "GO":
        blockers.append("options live gate is NO_GO")
    blockers.append("no live options execution adapter or venue is configured")
    return {
        "generated_from": {
            "self_eval": bool(self_eval),
            "campaign_health": bool(health),
            "live_gate": bool(live_gate),
            "options_evidence": bool(options),
        },
        "code_status": self_eval.get("status") if self_eval else "missing",
        "health_status": health.get("status") if health else "missing",
        "live_gate": live_gate.get("status") if live_gate else "missing",
        "options_live_gate": options_live_gate.get("status", "missing"),
        "options_status": options.get("status") if options else "missing",
        "paper_days": int(paper.get("paper_days") or 0),
        "target_paper_days": int(
            options.get("target_paper_days", 56) if options else 56
        ),
        "paper_ready": (
            (self_eval or {}).get("status") == "PASS"
            and (health or {}).get("status") == "OK"
        ),
        "paper_evidence_ready": int(
            (options or {}).get("paper", {}).get("paper_days", 0)
        )
        >= int((options or {}).get("target_paper_days", 56)),
        # No live options adapter or venue is configured, so a gate result alone
        # can never make this true.
        "live_ready": False,
        "blockers": blockers,
        "live_gate_failed": live_gate.get("failed", []) if live_gate else [],
        "options_live_gate_failed": options_live_gate.get("failed", []),
    }
