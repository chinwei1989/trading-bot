from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tradingbot.ops.campaign_health import (
    CampaignSpec,
    build_health,
    check_campaign,
    default_campaigns,
    format_health,
    write_health,
)


def _write_perf(path: Path, timestamp: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"timestamp": timestamp, "equity": 10_000.0}) + "\n", encoding="utf-8")


def _spec() -> CampaignSpec:
    return CampaignSpec(
        "trend",
        Path("performance.jsonl"),
        Path("heartbeat.json"),
    )


def test_default_campaigns_include_ai_squad() -> None:
    names = {campaign.name for campaign in default_campaigns()}
    assert "ai_squad" in names


def test_fresh_campaign_is_ok(tmp_path: Path) -> None:
    now = datetime(2026, 10, 23, 7, 30, tzinfo=UTC)
    _write_perf(tmp_path / "performance.jsonl", "2026-10-23T07:20:00+00:00")
    (tmp_path / "heartbeat.json").write_text(
        json.dumps({"status": "ok", "timestamp": "2026-10-23T07:20:00+00:00"}),
        encoding="utf-8",
    )
    check = check_campaign(_spec(), tmp_path, now=now)
    assert check.status == "ok"
    assert check.days == 1
    assert check.heartbeat == "ok"


def test_missing_campaign_is_flagged(tmp_path: Path) -> None:
    check = check_campaign(_spec(), tmp_path)
    assert check.status == "missing"


def test_previous_day_is_stale_even_if_within_26h(tmp_path: Path) -> None:
    now = datetime(2026, 10, 23, 7, 30, tzinfo=UTC)
    # 15:30 Singapore on the previous local day.
    _write_perf(tmp_path / "performance.jsonl", "2026-10-22T07:30:00+00:00")
    check = check_campaign(_spec(), tmp_path, now=now)
    assert check.status == "stale"


def test_error_heartbeat_fails(tmp_path: Path) -> None:
    now = datetime(2026, 10, 23, 7, 30, tzinfo=UTC)
    _write_perf(tmp_path / "performance.jsonl", "2026-10-23T07:20:00+00:00")
    (tmp_path / "heartbeat.json").write_text(
        json.dumps({"status": "error", "error": "broker unavailable"}),
        encoding="utf-8",
    )
    check = check_campaign(_spec(), tmp_path, now=now)
    assert check.status == "error"
    assert "broker unavailable" in check.detail


def test_report_and_markdown(tmp_path: Path) -> None:
    # build_health uses the default campaign list, so a fresh trend row alone
    # is not enough; the aggregate must be degraded.
    now = datetime(2026, 10, 23, 7, 30, tzinfo=UTC)
    _write_perf(tmp_path / "artifacts/performance_trend.jsonl", "2026-10-23T07:20:00+00:00")
    report = build_health(tmp_path, now=now)
    assert report["status"] == "DEGRADED"
    assert report["required_days"] == 56
    text = format_health(report)
    assert "trend" in text
    json_path, md_path = write_health(report, tmp_path)
    assert json_path.exists() and md_path.exists()
    assert "Campaign health" in md_path.read_text(encoding="utf-8")
