"""Write the read-only readiness snapshot used by the dashboard/operators."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tradingbot.ops.readiness import build_readiness

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        **build_readiness(ROOT),
    }
    out = ROOT / "artifacts"
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "READINESS.json"
    md_path = out / "READINESS.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        "# Readiness",
        "",
        f"Generated: `{report['generated_at']}`",
        f"Paper infrastructure ready: **{report['paper_ready']}**",
        f"Paper evidence window complete: **{report['paper_evidence_ready']}**",
        f"Live ready: **{report['live_ready']}**",
        "",
        "| Check | Value |",
        "|---|---|",
        f"| Code checks | {report['code_status']} |",
        f"| Campaign health | {report['health_status']} |",
        f"| Spot live gate | {report['live_gate']} |",
        f"| Options live gate | {report['options_live_gate']} |",
        f"| Options evidence | {report['options_status']} |",
        f"| Paper days | {report['paper_days']} / {report['target_paper_days']} |",
        "",
        "## Blockers",
        "",
    ]
    lines.extend(f"- {blocker}" for blocker in report["blockers"])
    lines.extend(
        [
            "",
            "`paper_ready` means code and campaign health are operational. "
            "It does not mean the strategy has 56 days of evidence or live approval.",
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"paper_ready={report['paper_ready']} live_ready={report['live_ready']}")
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
