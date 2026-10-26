from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tradingbot.ops.readiness import build_readiness
from tradingbot.options.live_gate import build_options_live_gate


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
    _write(
        tmp_path / "artifacts" / "HOST_READINESS.json",
        {"status": "READY", "recommendations": []},
    )

    readiness = build_readiness(tmp_path)
    assert readiness["paper_ready"] is True
    assert readiness["paper_evidence_ready"] is False
    assert readiness["host_ready"] is True
    assert readiness["live_ready"] is False
    assert readiness["live_gate"] == "NO_GO"
    assert readiness["paper_days"] == 1
    assert readiness["options_live_gate"] == "missing"
    assert any("no live options execution" in item for item in readiness["blockers"])


def test_options_live_gate_blocks_without_adapter(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    shutil.copy(
        Path("config/ai_options_30m.yaml"),
        tmp_path / "config" / "ai_options_30m.yaml",
    )
    gate = build_options_live_gate(tmp_path)
    assert gate["status"] == "NO_GO"
    assert "options live adapter" in gate["failed"]
    assert "options paper days" in gate["failed"]


def test_options_live_gate_does_not_accept_testnet_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "config").mkdir()
    shutil.copy(
        Path("config/ai_options_30m.yaml"),
        tmp_path / "config" / "ai_options_30m.yaml",
    )
    monkeypatch.setenv("DERIBIT_CLIENT_ID", "testnet-id")
    monkeypatch.setenv("DERIBIT_CLIENT_SECRET", "testnet-secret")
    monkeypatch.delenv("DERIBIT_LIVE_CLIENT_ID", raising=False)
    monkeypatch.delenv("DERIBIT_LIVE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("DERIBIT_LIVE_CONFIRM", raising=False)

    gate = build_options_live_gate(tmp_path)
    checks = {check["name"]: check for check in gate["checks"]}
    assert not checks["options credentials"]["passed"]
    assert "testnet" in checks["options credentials"]["detail"]
    assert not checks["options live confirmation"]["passed"]

    monkeypatch.setenv("DERIBIT_LIVE_CLIENT_ID", "live-id")
    monkeypatch.setenv("DERIBIT_LIVE_CLIENT_SECRET", "live-secret")
    monkeypatch.setenv("DERIBIT_LIVE_CONFIRM", "YES")
    gate = build_options_live_gate(tmp_path)
    checks = {check["name"]: check for check in gate["checks"]}
    assert checks["options credentials"]["passed"]
    assert checks["options live confirmation"]["passed"]
