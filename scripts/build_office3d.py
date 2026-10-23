"""Build the self-contained 3D agent office HTML."""

from __future__ import annotations

from pathlib import Path

from tradingbot.ops.office3d import build_office_html

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    html = build_office_html(ROOT)
    out = ROOT / "artifacts" / "office3d" / "office.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Wrote: {out} ({len(html):,} bytes)")
    print("Open it directly, or use the Streamlit dashboard's '3D Office' view.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
