from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from fastapi.testclient import TestClient


def _app_module() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "app.py"
    spec = importlib.util.spec_from_file_location("vercel_status_app", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload() -> dict:
    return {
        "generated_at": "2026-10-26T15:00:00+00:00",
        "gate": {"status": "NO_GO", "failed": ["paper campaign"]},
        "health": {"status": "OK"},
        "readiness": {
            "paper_ready": True,
            "paper_days": 3,
            "target_paper_days": 56,
            "live_gate": "NO_GO",
            "options_live_gate": "NO_GO",
        },
        "host_readiness": {
            "status": "DEGRADED",
            "tasks": [
                {
                    "name": "TradingBotOptionsSwing",
                    "state": "Ready",
                    "last_result": 0,
                    "next_run": "2026-10-27T07:40:00+08:00",
                }
            ],
        },
        "campaigns": {
            "trend": {"equity": 9964.15, "days": 4, "mode": "paper"},
            "swing": {"equity": 10000.0, "days": 1, "mode": "paper"},
        },
        "ai_squad": {"equity": 10000.0, "days": 4},
        "ai_squad_scorecard": {"status": "insufficient_data"},
        "options_evidence": {
            "status": "insufficient",
            "paper": {"paper_days": 3, "fills": 0},
            "replay": {"final_equity": 9996.8, "snapshots": 47},
        },
        "options_live_gate": {"status": "NO_GO", "failed": ["options paper days"]},
        "options_swing_report": {
            "as_of": "2026-10-24T00:00:00+00:00",
            "account_after": {"equity": 10000.0, "cash": 10000.0, "legs": 0},
            "signals": {
                "BTC": {"direction": "flat"},
                "ETH": {"direction": "flat"},
            },
            "fills": [],
            "exits": [],
        },
        "testnet_canary": {
            "status": "ok",
            "ok": True,
            "mode": "cycle",
            "final_reconcile": {"open_orders": [], "local_positions": {}},
        },
    }


def test_vercel_lite_page_renders_swing_status(
    tmp_path: Path, monkeypatch
) -> None:
    status_path = tmp_path / "status.json"
    status_path.write_text(json.dumps(_payload()), encoding="utf-8")
    module = _app_module()
    monkeypatch.setattr(module, "STATUS_PATH", status_path)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)

    client = TestClient(module.app)
    health = client.get("/healthz")
    assert health.status_code == 200

    response = client.get("/")
    assert response.status_code == 200
    text = response.text
    assert "Trading Operations" in text
    assert "Swing options" in text
    assert "BTC: flat" in text
    assert "Testnet canary" in text
    assert "Read-only snapshot" in text
    assert "place orders" in text


def test_vercel_status_api_returns_snapshot(tmp_path: Path, monkeypatch) -> None:
    status_path = tmp_path / "status.json"
    payload = _payload()
    status_path.write_text(json.dumps(payload), encoding="utf-8")
    module = _app_module()
    monkeypatch.setattr(module, "STATUS_PATH", status_path)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)

    response = TestClient(module.app).get("/api/status")
    assert response.status_code == 200
    assert response.json()["campaigns"]["swing"]["equity"] == 10000.0
