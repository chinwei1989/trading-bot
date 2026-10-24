"""Hard evidence gate for the options live lane.

This is a separate, stricter gate from the spot live gate. It is read-only and
never enables execution. The options lane has no live adapter, so the only safe
result today is NO_GO.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tradingbot.config import AppConfig, load_config
from tradingbot.ops.options_evidence import build_options_evidence

MIN_PAPER_DAYS = 56
LIVE_EXCHANGES = {"deribit", "okx", "bybit"}


@dataclass(frozen=True)
class OptionsGateCheck:
    name: str
    passed: bool
    detail: str


def _resolve(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def _config(root: Path, config: AppConfig | None) -> AppConfig:
    return config or load_config(root / "config" / "ai_options_30m.yaml")


def build_options_live_gate(
    root: Path,
    *,
    config: AppConfig | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    cfg = _config(root, config)
    evidence = build_options_evidence(root)
    paper = evidence["paper"]
    checks: list[OptionsGateCheck] = []

    checks.append(
        OptionsGateCheck(
            "options paper days",
            int(paper.get("paper_days") or 0) >= MIN_PAPER_DAYS,
            f"{paper.get('paper_days', 0)} vs required {MIN_PAPER_DAYS}",
        )
    )
    checks.append(
        OptionsGateCheck(
            "options paper fills",
            int(paper.get("fills") or 0) > 0,
            f"{paper.get('fills', 0)} fills",
        )
    )
    drawdown = float(paper.get("max_drawdown") or 0.0)
    checks.append(
        OptionsGateCheck(
            "options drawdown",
            drawdown >= -float(cfg.risk.max_drawdown),
            f"{drawdown:.2%} vs limit {-float(cfg.risk.max_drawdown):.2%}",
        )
    )
    kill = _resolve(root, cfg.risk.kill_switch_file)
    checks.append(
        OptionsGateCheck(
            "options kill switch",
            not kill.exists(),
            "inactive" if not kill.exists() else "ACTIVE",
        )
    )
    checks.append(
        OptionsGateCheck(
            "options live broker config",
            cfg.broker.name != "paper" and not cfg.broker.paper,
            f"broker={cfg.broker.name} paper={cfg.broker.paper}",
        )
    )
    checks.append(
        OptionsGateCheck(
            "options live venue",
            cfg.broker.exchange.lower() in LIVE_EXCHANGES,
            f"exchange={cfg.broker.exchange} (allowed: {sorted(LIVE_EXCHANGES)})",
        )
    )
    checks.append(
        OptionsGateCheck(
            "options live adapter",
            False,
            "not implemented; only read-only Deribit public data exists",
        )
    )
    credentials = bool(
        os.getenv("DERIBIT_CLIENT_ID") and os.getenv("DERIBIT_CLIENT_SECRET")
    )
    checks.append(
        OptionsGateCheck(
            "options credentials",
            credentials,
            "DERIBIT_CLIENT_ID/SECRET present" if credentials else "missing",
        )
    )
    checks.append(
        OptionsGateCheck(
            "options evidence",
            evidence.get("status") == "target_days_reached",
            f"status={evidence.get('status')}",
        )
    )
    passed = all(check.passed for check in checks)
    return {
        "status": "GO" if passed else "NO_GO",
        "generated_at": datetime.now(UTC).isoformat(),
        "checks": [
            {"name": check.name, "passed": check.passed, "detail": check.detail}
            for check in checks
        ],
        "failed": [check.name for check in checks if not check.passed],
    }


def write_options_gate(gate: dict[str, Any], root: Path) -> tuple[Path, Path]:
    out = root / "artifacts"
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "OPTIONS_LIVE_GATE.json"
    md_path = out / "OPTIONS_LIVE_GATE.md"
    json_path.write_text(json.dumps(gate, indent=2), encoding="utf-8")
    lines = [
        "# Options live gate",
        "",
        f"**Status: {gate['status']}**",
        "",
        f"Generated: `{gate['generated_at']}`",
        "",
        "| Check | Result | Detail |",
        "|---|---|---|",
    ]
    for check in gate["checks"]:
        lines.append(
            f"| {check['name']} | {'PASS' if check['passed'] else 'FAIL'} | "
            f"{check['detail']} |"
        )
    lines.extend(
        [
            "",
            "No option order can be placed by this report. A GO requires every check.",
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path
