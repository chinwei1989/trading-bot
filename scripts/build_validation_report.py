"""Build a reproducible walk-forward validation report for the live gate.

Reads the ``artifacts/walkforward_*.json`` files produced by
``python -m tradingbot walkforward`` and writes both a JSON and Markdown
summary. This script is read-only with respect to trading state.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
BARS_PATH = ROOT / "data" / "normalized" / "bars.parquet"
STRATEGIES = ("trend", "xsmom", "breakout", "reversal", "meta")
MIN_DSR = 0.95
MAX_PBO = 0.20


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            check=True,
            text=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else None


def _data_summary() -> dict[str, Any]:
    if not BARS_PATH.exists():
        return {"path": str(BARS_PATH.relative_to(ROOT)), "available": False}
    bars = pl.read_parquet(BARS_PATH)
    assets = sorted(bars["asset"].unique().to_list()) if "asset" in bars.columns else []
    return {
        "path": str(BARS_PATH.relative_to(ROOT)),
        "available": True,
        "rows": bars.height,
        "assets": assets,
        "n_assets": len(assets),
        "start": str(bars["timestamp"].min()),
        "end": str(bars["timestamp"].max()),
        "sha256": _sha256(BARS_PATH),
    }


def _strategy_summary(name: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {"strategy": name, "available": False, "passed": False}
    metrics = payload.get("oos_metrics", {})
    dsr = float(payload.get("dsr", 0.0))
    pbo = float(payload.get("pbo", 1.0))
    return {
        "strategy": name,
        "available": True,
        "folds": len(payload.get("folds", [])),
        "trials": int(payload.get("n_trials", 0)),
        "dsr": dsr,
        "pbo": pbo,
        "oos_sharpe": float(metrics.get("sharpe", 0.0)),
        "oos_cagr": float(metrics.get("cagr", 0.0)),
        "oos_max_dd": float(metrics.get("max_dd", 0.0)),
        "oos_turnover": float(metrics.get("turnover_annual", 0.0)),
        "passed": dsr >= MIN_DSR and pbo <= MAX_PBO,
        "fold_details": payload.get("folds", []),
    }


def _fmt_pct(value: float) -> str:
    return f"{value:.1%}"


def _sensitivity_summary() -> list[dict[str, Any]]:
    """Read optional 180-day (or other suffix) stress runs."""
    summaries: list[dict[str, Any]] = []
    for suffix in ("_180d",):
        for name in STRATEGIES:
            payload = _load_json(ARTIFACTS / f"walkforward_{name}{suffix}.json")
            if payload is None:
                continue
            summary = _strategy_summary(name, payload)
            summary["suffix"] = suffix
            summary["label"] = "180-day OOS" if suffix == "_180d" else suffix
            summaries.append(summary)
    return summaries


def _sensitivity_markdown(report: dict[str, Any]) -> list[str]:
    sensitivity = report.get("sensitivity", [])
    lines = [
        "## Sensitivity: 180-day OOS folds",
        "",
    ]
    if not sensitivity:
        lines.extend(["Not run. The primary table uses 365-day OOS folds.", ""])
        return lines
    lines.extend(
        [
            "Shorter folds add more test windows and more selection events. "
            "The trial count rises, so DSR is expected to fall.",
            "",
            "| Strategy | Folds | Trials | DSR | PBO | OOS Sharpe | OOS CAGR | Max DD | Gate |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for summary in sensitivity:
        lines.append(
            "| {strategy} | {folds} | {trials} | {dsr:.3f} | {pbo:.3f} | "
            "{sharpe:.2f} | {cagr} | {dd} | {gate} |".format(
                strategy=summary["strategy"],
                folds=summary["folds"],
                trials=summary["trials"],
                dsr=summary["dsr"],
                pbo=summary["pbo"],
                sharpe=summary["oos_sharpe"],
                cagr=_fmt_pct(summary["oos_cagr"]),
                dd=_fmt_pct(summary["oos_max_dd"]),
                gate="PASS" if summary["passed"] else "FAIL",
            )
        )
    lines.extend(
        [
            "",
            "The 180-day runs use the same 900-day training window and 260-day warm-up.",
            "",
        ]
    )
    return lines


def _markdown(report: dict[str, Any]) -> str:
    data = report["data"]
    lines = [
        "# Walk-Forward Validation - 9-Asset Universe",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## Evidence",
        "",
        f"- Code commit: `{report['code_commit']}`",
        f"- Data: `{data.get('path')}`",
        f"- Rows: {data.get('rows', 0):,}",
        f"- Assets: {data.get('n_assets', 0)} - {', '.join(data.get('assets', []))}",
        f"- Range: {data.get('start')} to {data.get('end')}",
        f"- SHA-256: `{data.get('sha256', 'missing')}`",
        "",
        "## Method",
        "",
        "- Train: 900 days",
        "- Test: 365 days",
        "- Step: 365 days",
        "- Warm-up: 260 days",
        "- Costs: 10 bps commission + 5 bps slippage, next-bar execution",
        f"- Gate: DSR >= {MIN_DSR:.2f} and PBO <= {MAX_PBO:.2f}",
        "",
        "## Results",
        "",
        "| Strategy | Folds | Trials | DSR | PBO | OOS Sharpe | OOS CAGR | Max DD | Turnover | Gate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for summary in report["strategies"]:
        if not summary["available"]:
            lines.append(f"| {summary['strategy']} | — | — | — | — | — | — | — | — | MISSING |")
            continue
        lines.append(
            "| {strategy} | {folds} | {trials} | {dsr:.3f} | {pbo:.3f} | "
            "{sharpe:.2f} | {cagr} | {dd} | {turnover:.1f}x | {gate} |".format(
                strategy=summary["strategy"],
                folds=summary["folds"],
                trials=summary["trials"],
                dsr=summary["dsr"],
                pbo=summary["pbo"],
                sharpe=summary["oos_sharpe"],
                cagr=_fmt_pct(summary["oos_cagr"]),
                dd=_fmt_pct(summary["oos_max_dd"]),
                turnover=summary["oos_turnover"],
                gate="PASS" if summary["passed"] else "FAIL",
            )
        )
    lines.append("")
    lines.extend(_sensitivity_markdown(report))
    lines.extend(
        [
            "",
            "## Fold detail",
            "",
        ]
    )
    for summary in report["strategies"]:
        if not summary["available"]:
            continue
        lines.append(f"### {summary['strategy']}")
        lines.append("")
        lines.append("| Test window | Train Sharpe | Test Sharpe | Test return | Test max DD | Best params |")
        lines.append("|---|---:|---:|---:|---:|---|")
        for fold in summary["fold_details"]:
            params = json.dumps(fold.get("best_params", {}), sort_keys=True)
            lines.append(
                "| {start} to {end} | {train:.2f} | {test:.2f} | {ret} | {dd} | `{params}` |".format(
                    start=str(fold.get("test_start", ""))[:10],
                    end=str(fold.get("test_end", ""))[:10],
                    train=float(fold.get("train_sharpe", 0.0)),
                    test=float(fold.get("test_sharpe", 0.0)),
                    ret=_fmt_pct(float(fold.get("test_return", 0.0))),
                    dd=_fmt_pct(float(fold.get("test_max_dd", 0.0))),
                    params=params,
                )
            )
        lines.append("")
    lines.extend(
        [
            "## Verdict",
            "",
            report["verdict"],
            "",
            "## Notes",
            "",
            "- SUI starts on 2023-05-03, so folds before that date are effectively an 8-asset universe. No synthetic history is added.",
            "- The 365-day folds end on 2026-03-04; later bars are not part of the final test window.",
            "- DSR is corrected for the parameter trials within each strategy, but not for selecting the best strategy across the family.",
            "- This report is evidence only. It does not place orders or change any paper/live state.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    summaries = [
        _strategy_summary(name, _load_json(ARTIFACTS / f"walkforward_{name}.json"))
        for name in STRATEGIES
    ]
    passing = [s["strategy"] for s in summaries if s["passed"]]
    missing = [s["strategy"] for s in summaries if not s["available"]]
    if missing:
        verdict = (
            "INCOMPLETE — missing walk-forward evidence for: "
            + ", ".join(missing)
            + ". Live gate remains NO_GO."
        )
    elif not passing:
        verdict = "NO STRATEGY PASSES the DSR/PBO gate. Live capital remains NO_GO."
    elif len(passing) == len(summaries):
        verdict = "All strategies pass the DSR/PBO gate. Other live-gate checks still apply."
    else:
        verdict = (
            "Passing DSR/PBO: "
            + ", ".join(passing)
            + ". Failing: "
            + ", ".join(s["strategy"] for s in summaries if not s["passed"])
            + ". A family-wide live GO still requires every hard gate and the configured strategy to pass."
        )
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "code_commit": _git_commit(),
        "data": _data_summary(),
        "method": {
            "train_days": 900,
            "test_days": 365,
            "step_days": 365,
            "warmup_days": 260,
            "min_dsr": MIN_DSR,
            "max_pbo": MAX_PBO,
        },
        "strategies": summaries,
        "sensitivity": _sensitivity_summary(),
        "passing": passing,
        "missing": missing,
        "verdict": verdict,
    }
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    json_path = ARTIFACTS / "validation_report.json"
    md_path = ARTIFACTS / "validation_report.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    print(f"Validation evidence: {json_path}")
    print(f"Validation report: {md_path}")
    print(verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
