"""Daily campaign health checks.

The trading campaigns are scheduled tasks. A live gate can only accumulate
paper days if every campaign actually writes a fresh performance row. This
module checks the expected campaign files after the scheduled window and writes
a small JSON/Markdown report.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import polars as pl

from tradingbot.ops.heartbeat import read_heartbeat
from tradingbot.ops.performance import load_performance

SINGAPORE = ZoneInfo("Asia/Singapore")
DEFAULT_MAX_AGE_HOURS = 26.0
REQUIRED_PAPER_DAYS = 56


@dataclass(frozen=True)
class CampaignSpec:
    name: str
    performance_path: Path
    heartbeat_path: Path


@dataclass(frozen=True)
class CampaignCheck:
    name: str
    status: Literal["ok", "stale", "missing", "error"]
    latest: str | None
    age_hours: float | None
    days: int
    heartbeat: str | None
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "latest": self.latest,
            "age_hours": round(self.age_hours, 2) if self.age_hours is not None else None,
            "days": self.days,
            "heartbeat": self.heartbeat,
            "detail": self.detail,
        }


def default_campaigns() -> list[CampaignSpec]:
    """Campaign files written by the three scheduled paper tasks."""
    return [
        CampaignSpec(
            "trend",
            Path("artifacts/performance_trend.jsonl"),
            Path("artifacts/heartbeat.json"),
        ),
        CampaignSpec(
            "xsmom",
            Path("artifacts/performance_xsmom.jsonl"),
            Path("artifacts/heartbeat_xsmom.json"),
        ),
        CampaignSpec(
            "breakout",
            Path("artifacts/performance_breakout.jsonl"),
            Path("artifacts/heartbeat_breakout.json"),
        ),
        CampaignSpec(
            "reversal",
            Path("artifacts/performance_reversal.jsonl"),
            Path("artifacts/heartbeat_reversal.json"),
        ),
        CampaignSpec(
            "meta",
            Path("artifacts/performance_meta.jsonl"),
            Path("artifacts/heartbeat_meta.json"),
        ),
        CampaignSpec(
            "ai",
            Path("artifacts/ai/performance.jsonl"),
            Path("artifacts/ai/heartbeat.json"),
        ),
    ]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _unique_local_days(perf: pl.DataFrame) -> int:
    if perf.is_empty() or "timestamp" not in perf.columns:
        return 0
    return int(
        perf.select(
            pl.col("timestamp").dt.convert_time_zone("Asia/Singapore").dt.date().n_unique()
        ).item()
    )


def check_campaign(
    spec: CampaignSpec,
    root: Path,
    *,
    now: datetime | None = None,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
) -> CampaignCheck:
    """Check one campaign's latest performance row and heartbeat."""
    now = _as_utc(now or datetime.now(UTC))
    path = root / spec.performance_path
    if not path.exists():
        return CampaignCheck(spec.name, "missing", None, None, 0, None, f"missing {path}")

    perf = load_performance(path)
    if perf.is_empty() or "timestamp" not in perf.columns:
        return CampaignCheck(spec.name, "missing", None, None, 0, None, f"empty {path}")

    timestamps = perf["timestamp"].drop_nulls()
    if timestamps.is_empty():
        return CampaignCheck(spec.name, "missing", None, None, 0, None, "no timestamps")

    latest = _as_utc(timestamps.max())  # type: ignore[arg-type]
    age_hours = max(0.0, (now - latest).total_seconds() / 3600.0)
    days = _unique_local_days(perf)
    heartbeat_payload = read_heartbeat(root / spec.heartbeat_path)
    heartbeat = str(heartbeat_payload.get("status")) if heartbeat_payload else None

    if heartbeat_payload is not None and heartbeat_payload.get("status") == "error":
        detail = f"heartbeat reports error: {heartbeat_payload.get('error')}"
        return CampaignCheck(
            spec.name, "error", latest.isoformat(), age_hours, days, heartbeat, detail
        )

    latest_local = latest.astimezone(SINGAPORE).date()
    today_local = now.astimezone(SINGAPORE).date()
    if latest_local != today_local:
        detail = f"no row for {today_local}; latest local date {latest_local}"
        return CampaignCheck(
            spec.name, "stale", latest.isoformat(), age_hours, days, heartbeat, detail
        )
    if age_hours > max_age_hours:
        detail = f"latest row is {age_hours:.1f}h old (max {max_age_hours:.0f}h)"
        return CampaignCheck(
            spec.name, "stale", latest.isoformat(), age_hours, days, heartbeat, detail
        )
    return CampaignCheck(
        spec.name,
        "ok",
        latest.isoformat(),
        age_hours,
        days,
        heartbeat,
        "fresh paper row",
    )


def build_health(
    root: Path,
    *,
    now: datetime | None = None,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
) -> dict[str, Any]:
    now = _as_utc(now or datetime.now(UTC))
    checks = [
        check_campaign(spec, root, now=now, max_age_hours=max_age_hours)
        for spec in default_campaigns()
    ]
    ok = all(check.status == "ok" for check in checks)
    return {
        "status": "OK" if ok else "DEGRADED",
        "generated_at": now.isoformat(),
        "required_days": REQUIRED_PAPER_DAYS,
        "max_age_hours": max_age_hours,
        "campaigns": [check.as_dict() for check in checks],
    }


def format_health(report: dict[str, Any]) -> str:
    lines = [
        f"Campaign health: {report['status']}",
        f"paper days required: {report['required_days']}",
    ]
    for campaign in report["campaigns"]:
        age = campaign.get("age_hours")
        age_text = f"{age:.1f}h" if age is not None else "n/a"
        lines.append(
            f"  [{campaign['status'].upper():>7}] {campaign['name']:<9} "
            f"days={campaign['days']:>2} latest_age={age_text:>6} "
            f"heartbeat={campaign.get('heartbeat') or 'n/a'} "
            f"({campaign['detail']})"
        )
    return "\n".join(lines)


def write_health(report: dict[str, Any], root: Path) -> tuple[Path, Path]:
    out_dir = root / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "CAMPAIGN_HEALTH.json"
    md_path = out_dir / "CAMPAIGN_HEALTH.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md = ["# Campaign health", "", f"**Status: {report['status']}**", ""]
    md.extend(
        [
            "| Campaign | Status | Days | Latest age (h) | Heartbeat | Detail |",
            "|---|---|---:|---:|---|---|",
        ]
    )
    for c in report["campaigns"]:
        md.append(
            f"| {c['name']} | {c['status']} | {c['days']} | "
            f"{c['age_hours'] if c['age_hours'] is not None else 'n/a'} | "
            f"{c.get('heartbeat') or 'n/a'} | {c['detail']} |"
        )
    md.extend(
        [
            "",
            "A degraded report means no new paper row was written in the scheduled window.",
            "Inspect `logs/health.log`, `logs/campaign.log`, and `logs/sleeves.log`.",
        ]
    )
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return json_path, md_path


def notify_health(report: dict[str, Any]) -> bool:
    if report["status"] == "OK":
        return False
    from tradingbot.ops.alerts import notify

    bad = [c for c in report["campaigns"] if c["status"] != "ok"]
    return notify(
        f"tradingbot campaign health: {report['status']}",
        [f"{c['name']}: {c['status']} — {c['detail']}" for c in bad],
    )
