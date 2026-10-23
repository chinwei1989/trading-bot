"""Hard live-capital gate.

This module is read-only. It evaluates evidence and environment state and
returns GO only when every hard requirement passes. It never places orders.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from tradingbot.config import AppConfig
from tradingbot.ops.performance import load_performance

MIN_PAPER_DAYS = 56
MIN_DSR = 0.95
MAX_PBO = 0.20
MAX_TCA_BPS = 10.0
MAX_DATA_AGE_DAYS = 2
MAX_AI_FALLBACK_RATE = 0.05


@dataclass
class GateCheck:
    name: str
    passed: bool
    detail: str


def _resolve(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def _json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _paper_days(path: Path) -> int:
    perf = load_performance(path)
    if perf.is_empty() or "timestamp" not in perf.columns:
        return 0
    return int(
        perf.select(pl.col("timestamp").dt.date().alias("day"))
        .unique()
        .height
    )


def _check_walkforward(root: Path, strategy: str, checks: list[GateCheck]) -> None:
    path = root / "artifacts" / f"walkforward_{strategy}.json"
    payload = _json(path)
    if payload is None:
        checks.append(GateCheck("walk-forward", False, f"missing {path.name}"))
        return
    dsr = float(payload.get("dsr", 0.0))
    pbo = float(payload.get("pbo", 1.0))
    checks.append(
        GateCheck(
            "deflated Sharpe",
            dsr >= MIN_DSR,
            f"DSR {dsr:.3f} vs required {MIN_DSR:.2f}",
        )
    )
    checks.append(
        GateCheck(
            "PBO",
            pbo <= MAX_PBO,
            f"PBO {pbo:.3f} vs allowed {MAX_PBO:.2f}",
        )
    )


def _check_paper(root: Path, strategy: str, checks: list[GateCheck]) -> None:
    path = root / "artifacts" / f"performance_{strategy}.jsonl"
    days = _paper_days(path)
    checks.append(
        GateCheck(
            "paper campaign",
            days >= MIN_PAPER_DAYS,
            f"{days} unique days vs required {MIN_PAPER_DAYS}",
        )
    )


def _check_evaluation(root: Path, strategy: str, checks: list[GateCheck]) -> None:
    payload = _json(root / "artifacts" / "reports" / f"evaluation_{strategy}.json")
    if payload is None:
        checks.append(GateCheck("paper evaluation", False, "missing evaluation report"))
        return
    tca = payload.get("tca", {})
    slip = float(tca.get("weighted_slip_bps", 0.0))
    fills = float(tca.get("fills", 0.0))
    checks.append(
        GateCheck(
            "TCA",
            slip <= MAX_TCA_BPS and fills > 0,
            f"{slip:.1f} bps, {fills:.0f} fills (max {MAX_TCA_BPS:.1f} bps)",
        )
    )
    age = payload.get("data", {}).get("age_days")
    try:
        age_value = int(age)
    except (TypeError, ValueError):
        age_value = 999
    checks.append(
        GateCheck(
            "data freshness",
            age_value <= MAX_DATA_AGE_DAYS,
            f"{age} days old (max {MAX_DATA_AGE_DAYS})",
        )
    )
    alerts = payload.get("alerts", [])
    checks.append(
        GateCheck("paper alerts", not alerts, "none" if not alerts else "; ".join(map(str, alerts)))
    )


def _check_live_config(config: AppConfig, root: Path, checks: list[GateCheck]) -> None:
    live_broker = config.broker.name != "paper" and not config.broker.paper
    checks.append(
        GateCheck(
            "live broker config",
            live_broker,
            f"broker={config.broker.name} paper={config.broker.paper}",
        )
    )
    checks.append(
        GateCheck(
            "LIVE_TRADING",
            os.getenv("LIVE_TRADING") == "YES",
            "LIVE_TRADING=YES is set" if os.getenv("LIVE_TRADING") == "YES" else "not set",
        )
    )
    if config.broker.name == "ccxt":
        checks.append(
            GateCheck(
                "sandbox disabled",
                not config.broker.sandbox,
                f"sandbox={config.broker.sandbox}",
            )
        )
        keys = bool(os.getenv("CRYPTO_API_KEY") and os.getenv("CRYPTO_API_SECRET"))
        checks.append(GateCheck("crypto keys", keys, "present" if keys else "missing"))
    elif config.broker.name == "alpaca":
        keys = bool(os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY"))
        checks.append(GateCheck("Alpaca keys", keys, "present" if keys else "missing"))
    kill = _resolve(root, config.risk.kill_switch_file)
    checks.append(
        GateCheck(
            "kill switch",
            not kill.exists(),
            "inactive" if not kill.exists() else "ACTIVE",
        )
    )


def _check_ai(root: Path, checks: list[GateCheck]) -> None:
    payload = _json(root / "artifacts" / "ai" / "reports" / "scorecard.json")
    if payload is None:
        checks.append(GateCheck("AI scorecard", False, "missing"))
        return
    days = int(payload.get("n_days", 0))
    fallback = float(payload.get("provider", {}).get("fallback_rate", 1.0))
    status = str(payload.get("status", "missing"))
    checks.append(
        GateCheck(
            "AI paper days",
            days >= MIN_PAPER_DAYS,
            f"{days} vs required {MIN_PAPER_DAYS}",
        )
    )
    checks.append(
        GateCheck(
            "AI is not fallback",
            fallback <= MAX_AI_FALLBACK_RATE,
            f"fallback rate {fallback:.1%} (max {MAX_AI_FALLBACK_RATE:.0%})",
        )
    )
    checks.append(GateCheck("AI scorecard", status == "ok", f"status={status}"))
    checks.append(
        GateCheck(
            "AI live execution",
            False,
            "not implemented; AI lane is paper-only by design",
        )
    )


def build_live_gate(
    config: AppConfig,
    *,
    root: Path | None = None,
    include_ai: bool = False,
) -> dict[str, Any]:
    root = root or Path.cwd()
    checks: list[GateCheck] = []
    strategy = config.strategy.name
    if strategy == "combined":
        for name in ("trend", "xsmom"):
            _check_walkforward(root, name, checks)
            _check_paper(root, name, checks)
            _check_evaluation(root, name, checks)
    else:
        _check_walkforward(root, strategy, checks)
        _check_paper(root, strategy, checks)
        _check_evaluation(root, strategy, checks)
    _check_live_config(config, root, checks)
    if include_ai:
        _check_ai(root, checks)
    passed = all(check.passed for check in checks)
    return {
        "status": "GO" if passed else "NO_GO",
        "generated_at": datetime.now(UTC).isoformat(),
        "config_strategy": strategy,
        "checks": [
            {"name": c.name, "passed": c.passed, "detail": c.detail} for c in checks
        ],
        "failed": [c.name for c in checks if not c.passed],
    }


def write_gate(gate: dict[str, Any], root: Path) -> tuple[Path, Path]:
    out = root / "artifacts"
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "LIVE_GATE.json"
    json_path.write_text(json.dumps(gate, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Live-capital gate",
        "",
        f"**Status: {gate['status']}**",
        "",
        f"Generated: {gate['generated_at']}",
        "",
        "| Check | Result | Detail |",
        "|---|---|---|",
    ]
    for check in gate["checks"]:
        lines.append(
            f"| {check['name']} | {'PASS' if check['passed'] else 'FAIL'} | {check['detail']} |"
        )
    lines.extend(
        [
            "",
            "No live order can be placed by this report. A GO requires every check to pass.",
            "",
        ]
    )
    md_path = out / "LIVE_GATE.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path
