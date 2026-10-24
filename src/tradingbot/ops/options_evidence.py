"""Read-only evidence summary for the options paper and free replay lanes.

The scorecard is deliberately descriptive. It never changes policy, sizes a
position, or places an order. Its job is to make the current evidence explicit,
including the fact that one free chain day is not a backtest.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
AI_DIR = Path("artifacts") / "ai_options_30m"
REPLAY_PATH = Path("artifacts") / "options_tardis" / "tardis_replay_2026-10-01.json"
TARGET_PAPER_DAYS = 56


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif value:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def _max_drawdown(values: list[float]) -> float:
    best = 0.0
    peak = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            best = min(best, value / peak - 1.0)
    return best


def _stage_from_name(path: Path) -> str:
    stem = path.stem
    return stem.split("_", 1)[-1] if "_" in stem else stem


def _squad_evidence(squad_dir: Path) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    manifests = sorted(
        squad_dir.glob("*/manifest.json"),
        key=lambda path: path.stat().st_mtime,
    )
    for manifest_path in manifests:
        run_dir = manifest_path.parent
        memos: dict[str, dict[str, Any]] = {}
        for path in sorted(run_dir.glob("*.json")):
            if path.name == "manifest.json":
                continue
            memo = _load_json(path)
            if not memo:
                continue
            stage = str(memo.get("stage") or _stage_from_name(path))
            memos[stage] = memo
        if not memos:
            continue
        risk = memos.get("risk", {})
        execution = memos.get("execution", {})
        chair = memos.get("chair", {})
        risk_choices = risk.get("choices") if isinstance(risk.get("choices"), dict) else {}
        exec_choices = (
            execution.get("choices") if isinstance(execution.get("choices"), dict) else {}
        )
        chair_choices = (
            chair.get("choices") if isinstance(chair.get("choices"), dict) else {}
        )
        runs.append(
            {
                "run_id": run_dir.name,
                "as_of": risk.get("as_of") or chair.get("as_of") or "",
                "macro_regime": memos.get("macro", {}).get("regime"),
                "risk_regime": risk.get("regime"),
                "execution_regime": execution.get("regime"),
                "chair_regime": chair.get("regime"),
                "chair_confidence": chair.get("confidence"),
                "risk_choices": risk_choices,
                "execution_choices": exec_choices,
                "chair_choices": chair_choices,
            }
        )

    veto_assets = sum(
        1
        for run in runs
        for value in run["risk_choices"].values()
        if str(value).lower() == "veto"
    )
    block_assets = sum(
        1
        for run in runs
        for value in run["execution_choices"].values()
        if str(value).lower() == "block"
    )
    runs_with_veto = sum(
        1
        for run in runs
        if any(str(value).lower() == "veto" for value in run["risk_choices"].values())
    )
    runs_with_block = sum(
        1
        for run in runs
        if any(str(value).lower() == "block" for value in run["execution_choices"].values())
    )
    chair_flat_runs = sum(
        1
        for run in runs
        if run["chair_choices"]
        and all(str(value).lower() == "flat" for value in run["chair_choices"].values())
    )
    latest = runs[-1] if runs else None
    return {
        "runs": len(runs),
        "runs_with_risk_veto": runs_with_veto,
        "runs_with_execution_block": runs_with_block,
        "risk_veto_assets": veto_assets,
        "execution_block_assets": block_assets,
        "macro_risk_off_runs": sum(
            1 for run in runs if str(run["macro_regime"]).lower() == "risk_off"
        ),
        "chair_flat_runs": chair_flat_runs,
        "latest": latest,
    }


def _deduped_performance(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one row per decision slot, preferring an explicit ``as_of``."""
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("as_of") or row.get("timestamp") or "")
        if not key:
            continue
        latest[key] = row
    return [latest[key] for key in sorted(latest)]


def _paper_evidence(performance_path: Path, decisions_path: Path) -> dict[str, Any]:
    performance = _deduped_performance(_load_jsonl(performance_path))
    decisions = _load_jsonl(decisions_path)
    paper_decisions: dict[str, dict[str, Any]] = {}
    for row in decisions:
        if row.get("dry_run"):
            continue
        as_of = _parse_timestamp(row.get("as_of"))
        if as_of is None:
            continue
        paper_decisions[as_of.isoformat()] = row

    perf_by_as_of: dict[str, dict[str, Any]] = {}
    for row in performance:
        as_of = _parse_timestamp(row.get("as_of"))
        if as_of is not None:
            perf_by_as_of[as_of.isoformat()] = row

    cycles: list[dict[str, Any]] = []
    equity_values: list[float] = []
    paper_dates: set[str] = set()
    flat_cycles = 0
    risk_off_cycles = 0
    total_orders = 0
    total_fills = 0
    last_positions = 0
    first_ts: datetime | None = None
    last_ts: datetime | None = None

    if paper_decisions:
        ordered = sorted(paper_decisions.items())
        for as_of_iso, row in ordered:
            ts = _parse_timestamp(as_of_iso)
            if ts is None:
                continue
            try:
                equity_value = float(row.get("equity") or 0.0)
            except (TypeError, ValueError):
                continue
            perf_row = perf_by_as_of.get(as_of_iso, {})
            directions = row.get("directions")
            directions = directions if isinstance(directions, dict) else {}
            all_flat = not directions or all(
                str(value).lower() == "flat" for value in directions.values()
            )
            if all_flat:
                flat_cycles += 1
            if str(row.get("regime", "")).lower() == "risk_off":
                risk_off_cycles += 1
            n_orders = int(perf_row.get("n_orders") or 0)
            n_fills = int(perf_row.get("n_fills") or 0)
            total_orders += n_orders
            total_fills += n_fills
            last_positions = int(perf_row.get("positions") or last_positions)
            equity_values.append(equity_value)
            paper_dates.add(ts.date().isoformat())
            first_ts = ts if first_ts is None else min(first_ts, ts)
            last_ts = ts if last_ts is None else max(last_ts, ts)
            cycles.append(
                {
                    "timestamp": as_of_iso,
                    "equity": equity_value,
                    "cash": float(row.get("cash") or 0.0),
                    "regime": row.get("regime"),
                    "confidence": float(row.get("confidence") or 0.0),
                    "directions": directions,
                    "n_orders": n_orders,
                    "n_fills": n_fills,
                    "positions": int(perf_row.get("positions") or 0),
                }
            )
    else:
        for row in performance:
            ts = _parse_timestamp(row.get("timestamp"))
            equity = row.get("equity")
            if equity is None:
                continue
            try:
                equity_value = float(equity)
            except (TypeError, ValueError):
                continue
            equity_values.append(equity_value)
            if ts is not None:
                paper_dates.add(ts.date().isoformat())
                first_ts = ts if first_ts is None else min(first_ts, ts)
                last_ts = ts if last_ts is None else max(last_ts, ts)
            directions = row.get("directions")
            directions = directions if isinstance(directions, dict) else {}
            all_flat = not directions or all(
                str(value).lower() == "flat" for value in directions.values()
            )
            if all_flat:
                flat_cycles += 1
            if str(row.get("regime", "")).lower() == "risk_off":
                risk_off_cycles += 1
            try:
                total_orders += int(row.get("n_orders") or 0)
                total_fills += int(row.get("n_fills") or 0)
                last_positions = int(row.get("positions") or last_positions)
            except (TypeError, ValueError):
                pass
            cycles.append(
                {
                    "timestamp": ts.isoformat() if ts else "",
                    "equity": equity_value,
                    "cash": float(row.get("cash") or 0.0),
                    "regime": row.get("regime"),
                    "confidence": float(row.get("confidence") or 0.0),
                    "directions": directions,
                    "n_orders": int(row.get("n_orders") or 0),
                    "n_fills": int(row.get("n_fills") or 0),
                    "positions": int(row.get("positions") or 0),
                }
            )

    expected_cycles: int | None = None
    coverage: float | None = None
    if first_ts is not None and last_ts is not None:
        span_seconds = max(0.0, (last_ts - first_ts).total_seconds())
        expected_cycles = int(span_seconds // 1800) + 1
        if expected_cycles > 0:
            coverage = len(cycles) / expected_cycles

    initial_equity = equity_values[0] if equity_values else 0.0
    final_equity = equity_values[-1] if equity_values else 0.0
    return {
        "paper_days": len(paper_dates),
        "cycles": len(cycles),
        "expected_cycles": expected_cycles,
        "cycle_coverage": coverage,
        "flat_cycles": flat_cycles,
        "risk_off_cycles": risk_off_cycles,
        "orders": total_orders,
        "fills": total_fills,
        "positions": last_positions,
        "initial_equity": initial_equity,
        "final_equity": final_equity,
        "return_pct": final_equity / initial_equity - 1.0 if initial_equity else 0.0,
        "max_drawdown": _max_drawdown(equity_values),
        "first_timestamp": first_ts.isoformat() if first_ts else None,
        "last_timestamp": last_ts.isoformat() if last_ts else None,
        "cycle_rows": cycles[-24:],
    }


def _replay_evidence(path: Path) -> dict[str, Any] | None:
    payload = _load_json(path)
    if not payload:
        return None
    keys = [
        "chain_date",
        "snapshots",
        "underlying_bars",
        "signal_source",
        "signal_timestamp",
        "final_equity",
        "total_return",
        "max_drawdown",
        "total_fills",
        "total_fees",
        "cycles_blocked",
        "fills",
        "limitations",
    ]
    return {key: payload.get(key) for key in keys}


def build_options_evidence(root: str | Path = ROOT) -> dict[str, Any]:
    """Build the read-only options evidence payload from local artifacts."""
    base = Path(root)
    ai_dir = base / AI_DIR
    paper = _paper_evidence(
        ai_dir / "performance.jsonl",
        ai_dir / "decisions.jsonl",
    )
    squad = _squad_evidence(ai_dir / "squad")
    replay = _replay_evidence(base / REPLAY_PATH)
    warnings: list[str] = []
    if paper["paper_days"] < TARGET_PAPER_DAYS:
        warnings.append(
            f"Forward paper has {paper['paper_days']} day(s); "
            f"the target is {TARGET_PAPER_DAYS}."
        )
    if paper["fills"] == 0:
        warnings.append("Forward paper has no option fills yet.")
    if replay is None:
        warnings.append("Free one-day real-chain replay artifact is missing.")
    elif int(replay.get("snapshots") or 0) < 2:
        warnings.append("Free replay has too few snapshots to evaluate.")
    else:
        warnings.append(
            "The free replay is one day only and is not evidence of edge. "
            "Tardis is a paid vendor; only its first-day export was used."
        )
    status = "insufficient"
    if paper["paper_days"] >= TARGET_PAPER_DAYS:
        status = "target_days_reached"
    elif paper["paper_days"] >= 20:
        status = "accumulating"
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "target_paper_days": TARGET_PAPER_DAYS,
        "paper": paper,
        "squad": squad,
        "replay": replay,
        "warnings": warnings,
    }


def write_options_evidence(
    root: str | Path = ROOT,
    output_dir: str | Path | None = None,
) -> tuple[Path, Path]:
    """Write JSON and Markdown evidence snapshots. Read-only with respect to trading."""
    base = Path(root)
    evidence = build_options_evidence(base)
    out = Path(output_dir) if output_dir else base / "artifacts" / "options_evidence"
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "latest.json"
    md_path = out / "report.md"
    json_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    paper = evidence["paper"]
    squad = evidence["squad"]
    replay = evidence["replay"] or {}
    lines = [
        "# Options Evidence",
        "",
        f"Generated: `{evidence['generated_at']}`",
        f"Status: **{evidence['status']}**",
        "",
        "## Forward paper",
        "",
        f"- Paper days: **{paper['paper_days']} / {evidence['target_paper_days']}**",
        f"- Cycles: **{paper['cycles']}** (expected {paper['expected_cycles']})",
        f"- Flat cycles: **{paper['flat_cycles']}**",
        f"- Risk-off cycles: **{paper['risk_off_cycles']}**",
        f"- Orders / fills: **{paper['orders']} / {paper['fills']}**",
        f"- Equity: **${paper['final_equity']:,.2f}**",
        f"- Return: **{paper['return_pct']:.2%}**",
        f"- Max drawdown: **{paper['max_drawdown']:.2%}**",
        "",
        "## Squad controls",
        "",
        f"- Squad runs: **{squad['runs']}**",
        f"- Runs with risk veto: **{squad['runs_with_risk_veto']}**",
        f"- Runs with execution block: **{squad['runs_with_execution_block']}**",
        f"- Vetoed asset decisions: **{squad['risk_veto_assets']}**",
        f"- Blocked asset decisions: **{squad['execution_block_assets']}**",
        f"- Macro risk-off runs: **{squad['macro_risk_off_runs']}**",
        f"- Chair flat runs: **{squad['chair_flat_runs']}**",
        "",
        "## Free real-chain replay",
        "",
        f"- Date: `{replay.get('chain_date', '?')}`",
        f"- Snapshots: **{replay.get('snapshots', 0)}**",
        f"- Fills: **{replay.get('total_fills', 0)}**",
        f"- Return: **{float(replay.get('total_return') or 0):.2%}**",
        f"- Max drawdown: **{float(replay.get('max_drawdown') or 0):.2%}**",
        f"- Fees: **${float(replay.get('total_fees') or 0):,.2f}**",
        "",
        "## Warnings",
        "",
    ]
    lines.extend(f"- {warning}" for warning in evidence["warnings"])
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path
