from __future__ import annotations

from pathlib import Path

from tradingbot.ops.logs import build_logs_payload


def test_logs_payload_redacts_secrets_and_ignores_other_files(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "campaign.log").write_text(
        "\n".join(
            [
                "cycle start",
                f"report: {tmp_path / 'artifacts' / 'report.json'}",
                "TYPESAFE_API_KEY=sk-live-1234567890",
                '{"secret": "do-not-show", "token": "abc123"}',
                "telegram https://api.telegram.org/bot123456:ABC/sendMessage",
                "password: hunter2",
            ]
        ),
        encoding="utf-8",
    )
    (logs / "private.log").write_text("API_KEY=private", encoding="utf-8")

    payload = build_logs_payload(tmp_path)

    assert payload["redacted"] is True
    assert [item["name"] for item in payload["files"]] == ["campaign.log"]
    rendered = "\n".join(payload["files"][0]["lines"])
    assert "sk-live" not in rendered
    assert "do-not-show" not in rendered
    assert "abc123" not in rendered
    assert "123456:ABC" not in rendered
    assert "hunter2" not in rendered
    assert "[REDACTED]" in rendered
    assert str(tmp_path) not in rendered
    assert "<repo>" in rendered


def test_logs_payload_bounds_tail(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "campaign.log").write_text(
        "\n".join(f"line {index}" for index in range(500)),
        encoding="utf-8",
    )

    payload = build_logs_payload(tmp_path)
    lines = payload["files"][0]["lines"]

    assert len(lines) == 200
    assert lines[0] == "line 300"
    assert lines[-1] == "line 499"
    assert payload["files"][0]["truncated"] is True
