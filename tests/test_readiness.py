from __future__ import annotations

import json
from pathlib import Path

from tradingbot.ops.readiness import build_readiness


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_readiness_keeps_live_blocked_without_adapter(tmp_path: Path) -> None:
    _write(
        tmp_path / "artifacts" / "SELF_EVAL.json",
        {"status": "PASS"},
    )
    _write(
        tmp_path / "artifacts" / "CAMPAIGN_HEALTH.json",
        {"status": "OK"},
    )
    _write(
        tmp_path / "artifacts" / "LIVE_GATE.json",
        {"status": "NO_GO", "failed": ["paper campaign"]},
    )
    _write(
        tmp_path / "artifacts" / "options_evidence" / "latest.json",
        {
            "status": "insufficient",
            "target_paper_days": 56,
            "paper": {"paper_days": 1},
        },
    )

    readiness = build_readiness(tmp_path)
    assert readiness["paper_ready"] is True
    assert readiness["paper_evidence_ready"] is False
    assert readiness["live_ready"] is False
    assert readiness["live_gate"] == "NO_GO"
    assert readiness["paper_days"] == 1
    assert any("no live options execution" in item for item in readiness["blockers"])
