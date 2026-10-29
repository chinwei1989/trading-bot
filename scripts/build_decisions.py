"""Generate the read-only trade-decision snapshot for the dashboard."""

from __future__ import annotations

from pathlib import Path

from tradingbot.ops.decisions import write_decision_snapshots

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    payload = write_decision_snapshots(ROOT)
    rows = sum(len(lane.get("decisions", [])) for lane in payload["lanes"])
    errors = [lane["lane"] for lane in payload["lanes"] if lane.get("error")]
    print(
        "decisions written:",
        f"{len(payload['lanes'])} lanes,",
        f"{rows} open-position decisions",
    )
    if errors:
        print("lanes with errors:", ", ".join(errors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
