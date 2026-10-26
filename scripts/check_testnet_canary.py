"""Validate the latest Deribit testnet canary report.

Read-only and offline. Fails when the canary is stale, reported a failure, or
left any open orders or positions behind.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "artifacts" / "ai_options_30m" / "testnet_canary" / "latest.json"


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-age-hours", type=float, default=36.0)
    args = parser.parse_args()

    if not args.report.exists():
        print(f"canary report missing: {args.report}")
        return 1
    try:
        report: dict[str, Any] = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"canary report unreadable: {exc}")
        return 1

    generated_at = report.get("generated_at")
    if not isinstance(generated_at, str):
        print("canary report has no generated_at")
        return 1
    try:
        age_hours = (datetime.now(UTC) - _parse_time(generated_at)).total_seconds() / 3600.0
    except ValueError:
        print(f"canary report has invalid generated_at: {generated_at}")
        return 1
    if age_hours > args.max_age_hours:
        print(f"canary report stale: {age_hours:.1f}h > {args.max_age_hours:.1f}h")
        return 1
    if not report.get("ok"):
        print("canary reported failure")
        for issue in report.get("issues", []):
            print(f"issue: {issue}")
        return 1

    final = report.get("final_reconcile")
    if not isinstance(final, dict):
        print("canary report has no final reconciliation")
        return 1
    if not final.get("ok"):
        print("canary final reconciliation failed")
        return 1
    if final.get("open_orders"):
        print(f"canary left open orders: {final['open_orders']}")
        return 1
    if final.get("local_positions"):
        print(f"canary left local positions: {final['local_positions']}")
        return 1
    if final.get("remote_positions"):
        print(f"canary left remote positions: {final['remote_positions']}")
        return 1

    print(
        f"canary ok: mode={report.get('mode')} age={age_hours:.1f}h "
        f"open_orders=0 positions=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
