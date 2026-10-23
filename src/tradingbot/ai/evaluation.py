"""AI-agent evaluation scorecard.

This is deliberately separate from the deterministic evaluation report. It
measures the AI paper account, provider behavior, confidence calibration, and
TCA. It never places orders.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from tradingbot.backtest.metrics import compute_metrics, max_drawdown
from tradingbot.config import AppConfig
from tradingbot.data.store import load_bars, wide
from tradingbot.ops.evaluation import compute_tca, load_journal
from tradingbot.ops.performance import load_performance


def _resolve(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def _load_decisions(root: Path) -> list[dict[str, Any]]:
    path = root / "artifacts" / "ai" / "decisions.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _mean_column(frame: pl.DataFrame, column: str) -> float:
    if column not in frame.columns or frame.is_empty():
        return 0.0
    values = frame[column].to_numpy().astype(float)
    values = values[np.isfinite(values)]
    return float(values.mean()) if values.size else 0.0


def _metrics_from_performance(perf: pl.DataFrame, periods_per_year: int) -> dict[str, Any]:
    if perf.is_empty() or "equity" not in perf.columns:
        return {
            "status": "no_data",
            "n_days": 0,
            "final_equity": 0.0,
            "total_return": 0.0,
            "cagr": 0.0,
            "vol": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "max_dd": 0.0,
            "avg_gross": 0.0,
            "avg_cash_pct": 0.0,
        }
    frame = perf.sort("timestamp")
    if "timestamp" in frame.columns:
        frame = frame.with_columns(pl.col("timestamp").dt.date().alias("_day")).unique(
            subset=["_day"], keep="last"
        )
    else:
        frame = frame.unique(keep="last")
    equity = frame["equity"].to_numpy().astype(float)
    equity = equity[np.isfinite(equity)]
    if len(equity) == 0:
        return {
            "status": "no_data",
            "n_days": 0,
            "final_equity": 0.0,
            "total_return": 0.0,
            "cagr": 0.0,
            "vol": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "max_dd": 0.0,
            "avg_gross": 0.0,
            "avg_cash_pct": 0.0,
        }
    if len(equity) == 1:
        base = {
            "status": "insufficient_data",
            "n_days": 1,
            "final_equity": float(equity[0]),
            "total_return": 0.0,
            "cagr": 0.0,
            "vol": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "max_dd": 0.0,
            "avg_gross": _mean_column(frame, "gross_exposure"),
            "avg_cash_pct": _mean_column(frame, "cash") / max(_mean_column(frame, "equity"), 1e-9),
        }
        return base
    rets = np.diff(equity) / equity[:-1]
    metrics: dict[str, Any] = compute_metrics(
        rets,
        periods_per_year=periods_per_year,
        gross_exposure=frame["gross_exposure"].to_numpy()
        if "gross_exposure" in frame.columns
        else None,
    )
    first_ts = frame["timestamp"][0]
    last_ts = frame["timestamp"][-1]
    metrics.update(
        {
            "status": "ok",
            "n_days": len(equity),
            "final_equity": float(equity[-1]),
            "total_return": float(equity[-1] / equity[0] - 1.0),
            "max_dd": float(max_drawdown(equity)),
            "avg_gross": _mean_column(frame, "gross_exposure"),
            "avg_cash_pct": _mean_column(frame, "cash")
            / max(_mean_column(frame, "equity"), 1e-9),
            "start": str(first_ts),
            "end": str(last_ts),
        }
    )
    return metrics


def _confidence_calibration(
    decisions: list[dict[str, Any]], bars: pl.DataFrame
) -> list[dict[str, Any]]:
    if not decisions or bars.is_empty():
        return []
    close = wide(bars, "close").sort("timestamp")
    timestamps = close["timestamp"].to_list()
    records: list[tuple[float, float]] = []
    for decision in decisions:
        if decision.get("status") == "error":
            continue
        target = decision.get("target_weights")
        if not isinstance(target, dict) or not target:
            continue
        as_of = decision.get("as_of")
        try:
            ts = datetime.fromisoformat(str(as_of))
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        index = None
        for i, candidate in enumerate(timestamps):
            if candidate <= ts:
                index = i
            else:
                break
        if index is None or index + 1 >= len(timestamps):
            continue
        current = close.row(index, named=True)
        following = close.row(index + 1, named=True)
        realized = 0.0
        used = 0
        for asset, weight in target.items():
            if asset not in close.columns or not isinstance(weight, (int, float)):
                continue
            price_now = current.get(asset)
            price_next = following.get(asset)
            if price_now and price_next and float(weight) != 0.0:
                realized += float(weight) * (float(price_next) / float(price_now) - 1.0)
                used += 1
        if used:
            records.append((float(decision.get("confidence", 0.0)), realized))

    bins = [(0.0, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]
    out: list[dict[str, Any]] = []
    for low, high in bins:
        values = [ret for conf, ret in records if low <= conf < high]
        if not values:
            continue
        arr = np.asarray(values)
        out.append(
            {
                "confidence_bucket": f"{low:.1f}-{high:.1f}",
                "n": int(arr.size),
                "mean_next_return": float(arr.mean()),
                "hit_rate": float((arr > 0).mean()),
            }
        )
    return out


def _provider_stats(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    if not decisions:
        return {
            "decisions": 0,
            "fallback": 0,
            "fallback_rate": 0.0,
            "dry_runs": 0,
            "errors": 0,
            "mean_latency_ms": 0.0,
            "providers": {},
        }
    providers: dict[str, int] = {}
    for row in decisions:
        provider = str(row.get("provider", "unknown"))
        providers[provider] = providers.get(provider, 0) + 1
    latency = [float(row.get("latency_ms", 0.0)) for row in decisions]
    return {
        "decisions": len(decisions),
        "fallback": sum(1 for row in decisions if row.get("fallback")),
        "fallback_rate": sum(1 for row in decisions if row.get("fallback")) / len(decisions),
        "dry_runs": sum(1 for row in decisions if row.get("dry_run")),
        "errors": sum(1 for row in decisions if row.get("status") == "error"),
        "mean_latency_ms": float(np.mean(latency)) if latency else 0.0,
        "providers": providers,
    }


def build_scorecard(config: AppConfig, root: Path) -> dict[str, Any]:
    perf = load_performance(_resolve(root, config.broker.performance_path))
    decisions = _load_decisions(root)
    bars_path = _resolve(root, config.data.bars_path)
    bars = load_bars(bars_path) if bars_path.exists() else pl.DataFrame()
    metrics = _metrics_from_performance(perf, config.backtest.periods_per_year)
    benchmarks: dict[str, Any] = {}
    for name, path in {
        "trend": root / "artifacts" / "performance_trend.jsonl",
        "xsmom": root / "artifacts" / "performance_xsmom.jsonl",
    }.items():
        if path.exists():
            benchmarks[name] = _metrics_from_performance(
                load_performance(path), config.backtest.periods_per_year
            )
    tca = (
        compute_tca(load_journal(_resolve(root, config.broker.journal_path)), bars)
        if bars.height
        else {"fills": 0.0, "weighted_slip_bps": 0.0}
    )
    provider = _provider_stats(decisions)
    n_days = int(metrics.get("n_days", 0))
    notes: list[str] = []
    if n_days < 20:
        notes.append("Need at least 20 paper days for meaningful metrics.")
    if provider["decisions"] and provider["fallback_rate"] >= 0.999:
        notes.append("All recorded decisions are fallback decisions; this is not AI evidence.")
    if metrics.get("status") == "insufficient_data":
        notes.append("Only one performance point exists.")
    status = "ok"
    if n_days < 20:
        status = "insufficient_data"
    elif provider["decisions"] and provider["fallback_rate"] >= 0.999:
        status = "fallback_only"
    scorecard = {
        "pipeline": "ai_agent",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "n_days": n_days,
        "metrics": metrics,
        "benchmarks": benchmarks,
        "provider": provider,
        "confidence_calibration": _confidence_calibration(decisions, bars),
        "tca": tca,
        "notes": notes,
    }
    return scorecard


def write_scorecard(scorecard: dict[str, Any], root: Path) -> tuple[Path, Path]:
    out = root / "artifacts" / "ai" / "reports"
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "scorecard.json"
    json_path.write_text(json.dumps(scorecard, indent=2, default=str), encoding="utf-8")
    metrics = scorecard.get("metrics", {})
    lines = [
        "# AI-agent paper scorecard",
        "",
        f"- Status: **{scorecard.get('status')}**",
        f"- Generated: {scorecard.get('generated_at')}",
        f"- Paper days: **{scorecard.get('n_days', 0)}**",
        f"- Equity: **${metrics.get('final_equity', 0):,.2f}**",
        f"- Total return: **{metrics.get('total_return', 0):.2%}**",
        f"- CAGR: **{metrics.get('cagr', 0):.2%}**",
        f"- Sharpe: **{metrics.get('sharpe', 0):.2f}**",
        f"- Max drawdown: **{metrics.get('max_dd', 0):.2%}**",
        f"- Avg gross: **{metrics.get('avg_gross', 0):.1%}**",
        f"- Provider decisions: **{scorecard.get('provider', {}).get('decisions', 0)}**",
        f"- Fallback rate: **{scorecard.get('provider', {}).get('fallback_rate', 0):.1%}**",
        f"- TCA: **{scorecard.get('tca', {}).get('weighted_slip_bps', 0):.1f} bps**",
        "",
        "## Benchmarks",
        "",
        "| Sleeve | Return | Sharpe | Max DD | Days |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, bench in scorecard.get("benchmarks", {}).items():
        lines.append(
            f"| {name} | {bench.get('total_return', 0):.2%} | "
            f"{bench.get('sharpe', 0):.2f} | {bench.get('max_dd', 0):.2%} | "
            f"{bench.get('n_days', 0)} |"
        )
    calibration = scorecard.get("confidence_calibration", [])
    if calibration:
        lines.extend(
            [
                "",
                "## Confidence calibration",
                "",
                "| Confidence | n | Mean next return | Hit rate |",
                "|---|---:|---:|---:|",
            ]
        )
        for row in calibration:
            lines.append(
                f"| {row['confidence_bucket']} | {row['n']} | "
                f"{row['mean_next_return']:.3%} | {row['hit_rate']:.1%} |"
            )
    notes = scorecard.get("notes", [])
    if notes:
        lines.extend(["", "## Notes", ""])
        lines.extend(f"- {note}" for note in notes)
    md_path = out / "scorecard.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def format_scorecard(scorecard: dict[str, Any]) -> str:
    metrics = scorecard.get("metrics", {})
    return (
        f"status={scorecard.get('status')} days={scorecard.get('n_days', 0)} "
        f"equity=${metrics.get('final_equity', 0):,.2f} "
        f"sharpe={metrics.get('sharpe', 0):.2f} "
        f"max_dd={metrics.get('max_dd', 0):.2%} "
        f"fallback={scorecard.get('provider', {}).get('fallback_rate', 0):.1%}"
    )
