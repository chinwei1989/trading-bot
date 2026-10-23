from __future__ import annotations

from tradingbot.ops.heartbeat import read_heartbeat, write_heartbeat


def test_heartbeat_roundtrip(tmp_path) -> None:
    path = tmp_path / "heartbeat.json"
    write_heartbeat(path, {"status": "ok", "equity": 100.0})
    payload = read_heartbeat(path)
    assert payload is not None
    assert payload["status"] == "ok"
    assert payload["equity"] == 100.0
    assert "timestamp" in payload


def test_missing_heartbeat(tmp_path) -> None:
    assert read_heartbeat(tmp_path / "missing.json") is None
