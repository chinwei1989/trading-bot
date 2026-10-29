"""Pure-Python data adapter for the Next.js dashboard and Vercel snapshot."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from tradingbot.ops.ai_summary import (
    SPOT_LANES,
    _json,
    _state,
)
from tradingbot.ops.logs import build_logs_payload
from tradingbot.ops.readiness import build_readiness

LANE_COLORS = {
    "Trend": "#38bdf8",
    "XSMOM": "#2dd4bf",
    "Breakout": "#fbbf24",
    "Reversal": "#f472b6",
    "Meta": "#a78bfa",
    "Intraday": "#60a5fa",
    "AI agent": "#c084fc",
    "AI squad": "#fb7185",
    "SUI lab": "#22d3ee",
}

PERFORMANCE_RANGE_DAYS = {"7D": 7, "30D": 30, "3M": 90, "1Y": 365}
PERFORMANCE_RANGES = ["Today", "7D", "30D", "3M", "1Y", "All"]

OPTION_LANE_REPORTS = {
    "AI options 30m": "artifacts/ai_options_30m/reports/latest.json",
    "Swing options": "artifacts/options_swing/reports/latest.json",
    "ETH options lab": "artifacts/ai_options_eth/reports/latest.json",
    "BTC options lab": "artifacts/ai_options_btc_lab/reports/latest.json",
}


def _perf_frame(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        frame = pd.read_json(path, lines=True)
    except ValueError:
        return pd.DataFrame()
    if "timestamp" not in frame.columns and "as_of" in frame.columns:
        frame["timestamp"] = pd.to_datetime(frame["as_of"], utc=True, errors="coerce")
    if "timestamp" in frame.columns:
        frame["timestamp"] = pd.to_datetime(
            frame["timestamp"], utc=True, errors="coerce"
        )
        frame = frame.sort_values("timestamp")
    return frame


def _initial_cash(spec: dict[str, str], root: Path) -> float:
    state = _json(root / spec["state"]) or {}
    try:
        return float(state.get("initial_cash", 10_000.0) or 10_000.0)
    except (TypeError, ValueError):
        return 10_000.0


def _performance_frames(root: Path) -> list[tuple[str, pd.DataFrame, float]]:
    frames: list[tuple[str, pd.DataFrame, float]] = []
    for lane, spec in SPOT_LANES.items():
        frame = _perf_frame(root / spec["performance"])
        if frame.empty or "equity" not in frame.columns:
            continue
        frame = frame[["timestamp", "equity"]].dropna().copy()
        if frame.empty:
            continue
        frames.append((lane, frame, _initial_cash(spec, root)))
    return frames


def _aggregate_today(
    frames: list[tuple[str, pd.DataFrame, float]],
) -> pd.Series:
    end = max(frame["timestamp"].max() for _, frame, _ in frames)
    start = end.normalize()
    points = {start}
    for _, frame, _ in frames:
        points.update(ts for ts in frame["timestamp"] if ts >= start)
    index = pd.DatetimeIndex(sorted(points))
    index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    total = pd.Series(0.0, index=index, dtype=float)
    for _, frame, initial in frames:
        series = frame.set_index("timestamp")["equity"].sort_index()
        series = (
            series.reindex(series.index.union(index))
            .ffill()
            .reindex(index)
            .fillna(initial)
        )
        total = total.add(series, fill_value=0.0)
    return total


def _aggregate_daily(
    frames: list[tuple[str, pd.DataFrame, float]],
) -> pd.Series:
    starts = [frame["timestamp"].min() for _, frame, _ in frames]
    ends = [frame["timestamp"].max() for _, frame, _ in frames]
    index = pd.date_range(
        start=min(starts).normalize(),
        end=max(ends).normalize(),
        freq="D",
    )
    total = pd.Series(0.0, index=index, dtype=float)
    for _, frame, initial in frames:
        daily = (
            frame.set_index("timestamp")["equity"]
            .resample("1D")
            .last()
            .reindex(index)
            .ffill()
            .fillna(initial)
        )
        total = total.add(daily, fill_value=0.0)
    return total


def _range_payload(
    equity: pd.Series,
    *,
    range_key: str,
    granularity: str,
) -> dict[str, Any]:
    equity = equity.dropna()
    if equity.empty:
        return {
            "range": range_key,
            "granularity": granularity,
            "points": [],
            "period_pnl": 0.0,
            "period_return": 0.0,
            "best": 0.0,
            "worst": 0.0,
            "latest_equity": 0.0,
            "observations": 0,
        }
    base = float(equity.iloc[0])
    pnl = equity.diff()
    pnl.iloc[0] = 0.0
    pnl_pct = pnl / equity.shift(1)
    pnl_pct.iloc[0] = 0.0
    changes = pnl.iloc[1:]
    points = [
        {
            "timestamp": timestamp.isoformat(),
            "equity": round(float(value), 2),
            "pnl": round(float(pnl.loc[timestamp]), 2),
            "pnl_pct": round(float(pnl_pct.loc[timestamp]), 8),
            "cum_pct": round(float(value / base - 1.0), 8),
        }
        for timestamp, value in equity.items()
    ]
    return {
        "range": range_key,
        "granularity": granularity,
        "points": points,
        "period_pnl": round(float(equity.iloc[-1] - base), 2),
        "period_return": round(float(equity.iloc[-1] / base - 1.0), 8),
        "best": round(float(changes.max()), 2) if not changes.empty else 0.0,
        "worst": round(float(changes.min()), 2) if not changes.empty else 0.0,
        "latest_equity": round(float(equity.iloc[-1]), 2),
        "observations": len(points),
    }


def _performance_ranges(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    frames = _performance_frames(root)
    if not frames:
        return {}, []
    initial_total = float(sum(initial for _, _, initial in frames))
    daily = _aggregate_daily(frames)
    today = _aggregate_today(frames)
    ranges: dict[str, Any] = {}
    for range_key in PERFORMANCE_RANGES:
        if range_key == "Today":
            equity = today
            granularity = "intraday"
        else:
            equity = daily
            granularity = "daily"
            if range_key in PERFORMANCE_RANGE_DAYS:
                end = equity.index.max()
                equity = equity[
                    equity.index
                    >= end - timedelta(days=PERFORMANCE_RANGE_DAYS[range_key] - 1)
                ]
        ranges[range_key] = _range_payload(
            equity,
            range_key=range_key,
            granularity=granularity,
        )
        ranges[range_key]["initial_total"] = initial_total
    curves: list[dict[str, Any]] = []
    for lane, frame, initial in frames:
        daily_lane = (
            frame.set_index("timestamp")["equity"].resample("1D").last().dropna()
        )
        curves.append(
            {
                "lane": lane,
                "color": LANE_COLORS.get(lane, "#94a3b8"),
                "initial": initial,
                "points": [
                    {
                        "timestamp": timestamp.isoformat(),
                        "equity": round(float(value), 2),
                    }
                    for timestamp, value in daily_lane.items()
                ],
            }
        )
    return ranges, curves


def _validation_payload(root: Path) -> dict[str, Any]:
    report = _json(root / "artifacts" / "validation_report.json") or {}
    if not report:
        return {}

    def _strategy_rows(rows: Any) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            pbo = row.get("pbo")
            result.append(
                {
                    "strategy": str(row.get("strategy", "")),
                    "folds": int(row.get("folds", 0) or 0),
                    "trials": int(row.get("trials", 0) or 0),
                    "dsr": float(row.get("dsr", 0.0) or 0.0),
                    "pbo": 1.0 if pbo is None else float(pbo),
                    "oos_sharpe": float(row.get("oos_sharpe", 0.0) or 0.0),
                    "oos_cagr": float(row.get("oos_cagr", 0.0) or 0.0),
                    "oos_max_dd": float(row.get("oos_max_dd", 0.0) or 0.0),
                    "passed": bool(row.get("passed")),
                }
            )
        return result

    data_raw = report.get("data")
    method_raw = report.get("method")
    data: dict[str, Any] = data_raw if isinstance(data_raw, dict) else {}
    method: dict[str, Any] = method_raw if isinstance(method_raw, dict) else {}
    return {
        "generated_at": report.get("generated_at"),
        "code_commit": report.get("code_commit"),
        "data": {
            "rows": int(data.get("rows", 0) or 0),
            "n_assets": int(data.get("n_assets", 0) or 0),
            "start": data.get("start"),
            "end": data.get("end"),
            "sha256": data.get("sha256"),
        },
        "method": method,
        "strategies": _strategy_rows(report.get("strategies")),
        "sensitivity": _strategy_rows(report.get("sensitivity")),
        "passing": report.get("passing") or [],
        "verdict": report.get("verdict", ""),
    }


def _decisions_payload(root: Path) -> dict[str, Any]:
    payload = _json(root / "artifacts" / "decisions" / "latest.json") or {}
    if not payload:
        return {}
    lanes = payload.get("lanes")
    return {
        "generated_at": payload.get("generated_at"),
        "lanes": lanes if isinstance(lanes, list) else [],
    }


def _option_payload(root: Path) -> dict[str, Any]:
    evidence = _json(root / "artifacts" / "options_evidence" / "latest.json") or {}
    gate = _json(root / "artifacts" / "OPTIONS_LIVE_GATE.json") or {}
    lanes: list[dict[str, Any]] = []
    for lane, relative in OPTION_LANE_REPORTS.items():
        report = _json(root / relative) or {}
        account = report.get("account_after") or report.get("paper", {}).get(
            "account_after", {}
        )
        lanes.append(
            {
                "lane": lane,
                "status": report.get("status", "missing"),
                "equity": account.get("equity"),
                "as_of": report.get("as_of"),
                "directions": report.get("directions") or {},
            }
        )
    return {
        "evidence": evidence,
        "live_gate": gate,
        "lanes": lanes,
    }


def build_dashboard_payload(root: Path) -> dict[str, Any]:
    root = root.resolve()
    state = _state(root)
    readiness = _json(root / "artifacts" / "READINESS.json")
    if not readiness:
        readiness = build_readiness(root)
    ranges, curves = _performance_ranges(root)
    gist = _json(root / "artifacts" / "ai_summary" / "latest.json")
    positions = sorted(
        state.get("positions", []),
        key=lambda row: abs(float(row.get("value", 0.0))),
        reverse=True,
    )
    spot_lanes = []
    for lane in state.get("spot_lanes", []):
        spot_lanes.append(
            {
                **lane,
                "color": LANE_COLORS.get(str(lane.get("lane")), "#94a3b8"),
            }
        )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "data_as_of": state.get("as_of"),
        "source": "local artifacts",
        "ai_gist": gist,
        "readiness": readiness,
        "portfolio": state.get("portfolio") or {},
        "lanes": spot_lanes,
        "positions": positions,
        "top_positions": state.get("top_positions") or [],
        "sui": state.get("sui") or {},
        "options_holdings": state.get("options") or {},
        "options": _option_payload(root),
        "validation": _validation_payload(root),
        "decisions": _decisions_payload(root),
        "logs": build_logs_payload(root),
        "performance": {
            "ranges": ranges,
            "lane_curves": curves,
        },
    }


def write_dashboard_snapshot(root: Path, destination: Path) -> dict[str, Any]:
    payload = build_dashboard_payload(root)
    payload["source"] = "snapshot"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )
    return payload
