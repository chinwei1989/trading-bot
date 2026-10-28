"""Generate the static dashboard snapshot for the Next.js frontend."""

from __future__ import annotations

from pathlib import Path

from tradingbot.ops.frontend_data import write_dashboard_snapshot

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    payload = write_dashboard_snapshot(ROOT, ROOT / "frontend" / "public" / "dashboard.json")
    # Also expose it to the existing Vercel/FastAPI lite surface.
    write_dashboard_snapshot(ROOT, ROOT / "deploy" / "dashboard.json")
    print(
        "frontend snapshot written:",
        f"{len(payload.get('positions', []))} positions,",
        f"{len(payload.get('lanes', []))} lanes,",
        f"{payload.get('data_as_of')}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
