"""Build the read-only options live-gate report."""

from __future__ import annotations

from pathlib import Path

from tradingbot.options.live_gate import build_options_live_gate, write_options_gate

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    gate = build_options_live_gate(ROOT)
    json_path, md_path = write_options_gate(gate, ROOT)
    print(f"Options live gate: {gate['status']}")
    for check in gate["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}")
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")
    return 0 if gate["status"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
