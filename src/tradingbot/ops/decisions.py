"""Read-only trade-decision context for the dashboard.

The paper accounts do not persist a free-text rationale for every historical
order.  This module reconstructs a *current* decision snapshot from the same
deterministic targets, AI decision records, paper positions, and order journal
that the runner uses.  It is deliberately read-only: it never submits orders or
changes paper state.

The generated artifact is intentionally small.  It contains one row per open
position, plus the latest orders for the lane, so the dashboard can answer
"what is the current decision for this trade, and why?" without recomputing
every strategy on each page load.
"""

from __future__ import annotations

import json
import sqlite3
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from tradingbot.config import AppConfig, load_config
from tradingbot.data.intraday import completed_bars
from tradingbot.data.store import wide
from tradingbot.data.universe import load_bars_with_universe
from tradingbot.execution.orders import latest_weights
from tradingbot.portfolio.risk import enforce_limits
from tradingbot.strategies import build_strategy

DECISIONS_PATH = Path("artifacts/decisions/latest.json")


@dataclass(frozen=True)
class LaneSpec:
    """The config and decision source for one dashboard lane."""

    lane: str
    config_path: Path
    mode: str = "strategy"
    decision_path: Path | None = None


LANE_SPECS: tuple[LaneSpec, ...] = (
    LaneSpec("Trend", Path("config/base.yaml")),
    LaneSpec("XSMOM", Path("config/xsmom.yaml")),
    LaneSpec("Breakout", Path("config/breakout.yaml")),
    LaneSpec("Reversal", Path("config/reversal.yaml")),
    LaneSpec("Meta", Path("config/meta.yaml")),
    LaneSpec("Intraday", Path("config/intraday_meta.yaml")),
    LaneSpec(
        "AI agent",
        Path("config/ai_agent.yaml"),
        mode="ai",
        decision_path=Path("artifacts/ai/decisions.jsonl"),
    ),
    LaneSpec(
        "AI squad",
        Path("config/ai_squad.yaml"),
        mode="ai",
        decision_path=Path("artifacts/ai_squad/decisions.jsonl"),
    ),
    LaneSpec("SUI lab", Path("config/sui.yaml")),
)


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


def _last_jsonl(path: Path) -> dict[str, Any] | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    last: dict[str, Any] | None = None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            tail = deque((line for line in handle if line.strip()), maxlen=1)
        for line in tail:
            payload = json.loads(line)
            if isinstance(payload, dict):
                last = payload
    except (OSError, json.JSONDecodeError):
        return None
    return last


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _round(value: float | None, digits: int = 6) -> float | None:
    return round(value, digits) if value is not None else None


def _price_map(bars: pl.DataFrame) -> dict[str, float]:
    if bars.is_empty():
        return {}
    last = bars.sort("timestamp").group_by("asset").tail(1)
    return {
        str(row["asset"]): float(row["close"])
        for row in last.iter_rows(named=True)
        if row.get("close") is not None
    }


def _series_map(bars: pl.DataFrame, field: str) -> dict[str, pl.Series]:
    frame = wide(bars, field).sort("timestamp")
    return {
        column: frame[column].drop_nulls()
        for column in frame.columns
        if column != "timestamp"
    }


def _strategy_basis(config: AppConfig, strategy_name: str) -> str:
    strategy = config.strategy
    params: Any
    if strategy_name == "trend":
        params = strategy.trend
        return (
            f"{params.lookback}d SMA trend · {params.rebalance} rebalance · "
            f"target vol {params.target_vol:.0%}"
        )
    if strategy_name == "xsmom":
        params = strategy.xsmom
        return (
            f"{params.lookback}d momentum · top {params.top_quantile:.0%} · "
            f"skip {params.skip}d · {params.rebalance} rebalance"
        )
    if strategy_name == "breakout":
        params = strategy.breakout
        return (
            f"{params.lookback}d Donchian breakout · {params.atr_stop:.1f}xATR "
            f"stop · {params.rebalance} rebalance"
        )
    if strategy_name == "reversal":
        params = strategy.reversal
        return (
            f"{params.lookback}d mean reversion · RSI({params.rsi_window}) "
            f"filter · {params.rebalance} rebalance"
        )
    if strategy_name == "meta":
        sleeves = ", ".join(
            f"{name} {weight:.0%}"
            for name, weight in strategy.meta.sleeves.items()
        )
        return f"meta allocator ({sleeves}) · {strategy.meta.rebalance} rebalance"
    return f"{strategy_name} strategy"


def _strategy_facts(
    bars: pl.DataFrame,
    config: AppConfig,
    strategy_name: str,
    assets: set[str],
) -> dict[str, list[str]]:
    """Small, deterministic facts that explain the current signal."""
    facts: dict[str, list[str]] = {asset: [] for asset in assets}
    try:
        close = _series_map(bars, "close")
    except (KeyError, ValueError):
        return facts

    for asset in assets:
        series = close.get(asset)
        if series is None or series.is_empty():
            continue
        if strategy_name == "trend":
            lookback = config.strategy.trend.lookback
            if series.len() >= lookback:
                price = _float(series.tail(1).item())
                sma = _float(series.tail(lookback).mean())
                if sma > 0:
                    facts[asset].append(
                        f"price {price / sma - 1:+.1%} vs {lookback}d SMA"
                    )
        elif strategy_name == "xsmom":
            lookback = config.strategy.xsmom.lookback
            skip = config.strategy.xsmom.skip
            if series.len() >= lookback + skip + 1:
                end = series.len() - skip - 1
                start = end - lookback
                momentum = _float(series[end]) / _float(series[start]) - 1
                facts[asset].append(
                    f"{lookback}d momentum {momentum:+.1%} (skip {skip}d)"
                )
        elif strategy_name == "breakout":
            lookback = config.strategy.breakout.lookback
            try:
                highs = _series_map(bars, "high").get(asset)
            except (KeyError, ValueError):
                highs = None
            if highs is not None and highs.len() >= lookback:
                prior_high = _float(highs.shift(1).tail(lookback).max())
                price = _float(series.tail(1).item())
                if prior_high > 0:
                    facts[asset].append(
                        f"price {price / prior_high - 1:+.1%} vs {lookback}d high"
                    )
        elif strategy_name == "reversal":
            lookback = config.strategy.reversal.lookback
            if series.len() >= lookback:
                window = series.tail(lookback)
                mean = _float(window.mean())
                std = _float(window.std())
                price = _float(series.tail(1).item())
                if std > 0:
                    facts[asset].append(
                        f"{lookback}d z-score {(price - mean) / std:+.2f}"
                    )
    return facts


def _strategy_snapshot(
    root: Path,
    config: AppConfig,
) -> tuple[dict[str, float], dict[str, float], str | None, dict[str, list[str]], str]:
    bars_path = _resolve(root, config.data.bars_path)
    if not bars_path.exists():
        return {}, {}, None, {}, _strategy_basis(config, config.strategy.name)
    universe_path = (
        _resolve(root, config.data.universe_path)
        if config.data.universe_path
        else None
    )
    bars = completed_bars(
        load_bars_with_universe(bars_path, universe_path),
        config.data.interval,
    )
    if bars.is_empty():
        return {}, {}, None, {}, _strategy_basis(config, config.strategy.name)
    strategy = build_strategy(config.strategy, config.backtest.periods_per_year)
    result = strategy.generate_weights(bars)
    weights = enforce_limits(result.weights, config.risk)
    latest = latest_weights(weights)
    if latest.is_empty():
        return {}, _price_map(bars), None, {}, _strategy_basis(
            config, config.strategy.name
        )
    targets = {
        str(row["asset"]): float(row["weight"])
        for row in latest.iter_rows(named=True)
    }
    prices = _price_map(bars)
    as_of = str(latest["timestamp"].max())
    facts = _strategy_facts(
        bars,
        config,
        config.strategy.name,
        set(targets) | set(prices),
    )
    return targets, prices, as_of, facts, _strategy_basis(
        config, config.strategy.name
    )


def _equity(
    state_positions: dict[str, Any],
    prices: dict[str, float],
    initial_cash: float,
    cash: float,
) -> float:
    marked = sum(
        _float(position.get("qty", 0.0))
        * prices.get(asset, 0.0)
        for asset, position in state_positions.items()
        if isinstance(position, dict)
    )
    value = cash + marked
    return value if value > 0 else initial_cash


def _orders(config: AppConfig, root: Path, lane: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    path = _resolve(root, config.broker.journal_path)
    if not path.exists():
        return [], {}
    try:
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT ts, asset, side, qty, status, avg_price, reference_price
                FROM orders
                ORDER BY ts DESC
                LIMIT 12
                """
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return [], {}
    recent: list[dict[str, Any]] = []
    by_asset: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = {
            "lane": lane,
            "timestamp": row["ts"],
            "asset": row["asset"],
            "side": row["side"],
            "qty": _round(_float(row["qty"])),
            "status": row["status"],
            "avg_price": _round(_float(row["avg_price"]), 8)
            if row["avg_price"] is not None
            else None,
            "reference_price": _round(_float(row["reference_price"]), 8)
            if row["reference_price"] is not None
            else None,
        }
        recent.append(item)
        by_asset.setdefault(str(row["asset"]), item)
    return recent, by_asset


def _decision(target: float, current: float, min_weight: float) -> str:
    if abs(current) < 1e-9 and target <= 1e-9:
        return "FLAT"
    if target <= 1e-9:
        return "EXIT"
    if abs(current) < 1e-9:
        return "ENTER"
    drift = target - current
    if drift > min_weight:
        return "ADD"
    if drift < -min_weight:
        return "TRIM"
    return "HOLD"


def _reason(
    *,
    decision: str,
    target: float,
    current: float,
    min_weight: float,
    basis: str,
    facts: list[str],
    mode: str,
    regime: str | None = None,
    confidence: float | None = None,
) -> str:
    drift = target - current
    if decision == "HOLD":
        core = (
            f"Latest target is {target:.2%} vs held {current:.2%} "
            f"(drift {drift:+.2%}); inside the {min_weight:.2%} rebalance band. "
            "No order is due."
        )
    elif decision == "ADD":
        core = (
            f"Latest target is {target:.2%} vs held {current:.2%} "
            f"(+{drift:.2%}); the next rebalance would add exposure."
        )
    elif decision == "TRIM":
        core = (
            f"Latest target is {target:.2%} vs held {current:.2%} "
            f"({drift:.2%}); the next rebalance would trim exposure."
        )
    elif decision == "EXIT":
        core = (
            f"Latest target is {target:.2%} but the position is {current:.2%}; "
            "the next rebalance would close it."
        )
    elif decision == "ENTER":
        core = (
            f"Latest target is {target:.2%} with no current position; "
            "the next rebalance would open it."
        )
    else:
        core = "No target or open position; no trade is due."
    evidence = "; ".join(facts)
    if mode == "ai":
        model = f"AI decision ({regime or 'unknown'} regime"
        if confidence is not None:
            model += f", {confidence:.0%} confidence"
        model += ")"
    else:
        model = f"Model: {basis}"
    parts = [core]
    if evidence:
        parts.append(f"Evidence: {evidence}.")
    parts.append(f"{model}.")
    return " ".join(parts)


def _lane_summary(
    decisions: list[dict[str, Any]],
    target_gross: float,
    current_gross: float,
) -> str:
    if not decisions:
        return (
            f"No open positions · target gross {target_gross:.2%} · "
            f"current gross {current_gross:.2%}"
        )
    counts: dict[str, int] = {}
    for row in decisions:
        counts[row["decision"]] = counts.get(row["decision"], 0) + 1
    count_text = ", ".join(f"{counts[key]} {key.lower()}" for key in sorted(counts))
    return (
        f"{len(decisions)} open · {count_text} · target gross "
        f"{target_gross:.2%} · current gross {current_gross:.2%}"
    )


def build_lane_snapshot(root: Path, spec: LaneSpec) -> dict[str, Any]:
    root = root.resolve()
    config = load_config(_resolve(root, spec.config_path))
    record: dict[str, Any] = {}
    if spec.mode == "ai":
        loaded = (
            _last_jsonl(_resolve(root, spec.decision_path))
            if spec.decision_path
            else None
        )
        record = loaded or {}
        targets = {
            str(asset): _float(weight)
            for asset, weight in (record.get("target_weights") or {}).items()
        }
        prices = _price_map(
            completed_bars(
                load_bars_with_universe(
                    _resolve(root, config.data.bars_path),
                    _resolve(root, config.data.universe_path)
                    if config.data.universe_path
                    else None,
                ),
                config.data.interval,
            )
        )
        as_of = record.get("as_of") or record.get("created_at")
        provider = record.get("provider") or "model"
        model_name = record.get("model") or "unknown model"
        basis = (
            f"AI {provider} · {model_name} · "
            f"regime {record.get('regime', 'unknown')}"
        )
        facts: dict[str, list[str]] = {}
        mode = "ai"
        regime = str(record.get("regime")) if record.get("regime") is not None else None
        confidence = (
            _float(record.get("confidence"))
            if record.get("confidence") is not None
            else None
        )
        target_source = "AI decision record" if record else "no AI decision record"
    else:
        targets, prices, as_of, facts, basis = _strategy_snapshot(root, config)
        mode = "strategy"
        regime = None
        confidence = None
        target_source = "strategy target"

    state = _json(_resolve(root, config.broker.state_path)) or {}
    positions = state.get("positions") or {}
    if not isinstance(positions, dict):
        positions = {}
    cash = _float(state.get("cash", config.broker.initial_cash))
    initial_cash = _float(state.get("initial_cash", config.broker.initial_cash))
    equity = _equity(positions, prices, initial_cash, cash)
    min_weight = max(
        config.broker.min_notional / equity if equity > 0 else 0.005,
        0.005,
    )
    recent_orders, order_by_asset = _orders(config, root, spec.lane)

    decision_rows: list[dict[str, Any]] = []
    for asset, raw_position in positions.items():
        if not isinstance(raw_position, dict):
            continue
        qty = _float(raw_position.get("qty", 0.0))
        if abs(qty) < 1e-12:
            continue
        price = prices.get(asset)
        value = qty * price if price is not None else 0.0
        current_weight = value / equity if equity > 0 else 0.0
        target_weight = targets.get(asset, 0.0)
        decision = _decision(target_weight, current_weight, min_weight)
        entry_raw = raw_position.get("avg_entry_price")
        entry = _float(entry_raw) if entry_raw is not None else None
        if entry is not None and entry <= 0:
            entry = None
        pnl = (price - entry) * qty if price is not None and entry is not None else None
        pnl_pct = pnl / (abs(qty) * entry) if pnl is not None and entry else None
        asset_facts = facts.get(asset, [])
        if price is not None:
            asset_facts = [*asset_facts, f"mark ${price:,.4f}"]
        decision_rows.append(
            {
                "asset": asset,
                "side": "long" if qty > 0 else "short",
                "decision": decision,
                "reason": _reason(
                    decision=decision,
                    target=target_weight,
                    current=current_weight,
                    min_weight=min_weight,
                    basis=basis,
                    facts=asset_facts,
                    mode=mode,
                    regime=regime,
                    confidence=confidence,
                ),
                "target_weight": _round(target_weight, 8),
                "current_weight": _round(current_weight, 8),
                "drift": _round(target_weight - current_weight, 8),
                "qty": _round(qty),
                "entry": _round(entry, 8),
                "last_price": _round(price, 8),
                "value": _round(value, 2),
                "pnl": _round(pnl, 2),
                "pnl_pct": _round(pnl_pct, 6),
                "signal_as_of": as_of,
                "facts": asset_facts,
                "last_order": order_by_asset.get(asset),
            }
        )

    decision_rows.sort(
        key=lambda row: (
            row["decision"] in {"EXIT", "TRIM"},
            -abs(_float(row.get("value"))),
            str(row["asset"]),
        )
    )
    stance_by_asset = {str(row["asset"]): row for row in decision_rows}
    for order in recent_orders:
        stance = stance_by_asset.get(str(order["asset"]))
        if stance is None:
            order["reason"] = "Historical order; no current position or target."
        else:
            order["reason"] = (
                f"Current stance {stance['decision']} · "
                f"target {_float(stance['target_weight']):.2%} vs held "
                f"{_float(stance['current_weight']):.2%}."
            )
    target_gross = sum(abs(weight) for weight in targets.values())
    current_gross = sum(abs(_float(row.get("value"))) for row in decision_rows) / (
        equity if equity > 0 else 1.0
    )
    return {
        "lane": spec.lane,
        "strategy": config.strategy.name if mode == "strategy" else "ai",
        "mode": mode,
        "as_of": as_of,
        "target_source": target_source,
        "basis": basis,
        "regime": regime,
        "confidence": confidence,
        "provider": record.get("provider") if mode == "ai" else None,
        "model": record.get("model") if mode == "ai" else None,
        "equity": _round(equity, 2),
        "target_gross": _round(target_gross, 6),
        "current_gross": _round(current_gross, 6),
        "summary": _lane_summary(decision_rows, target_gross, current_gross),
        "decisions": decision_rows,
        "recent_orders": recent_orders,
    }


def write_decision_snapshots(root: Path) -> dict[str, Any]:
    """Generate the dashboard's read-only decision artifact."""
    root = root.resolve()
    lanes: list[dict[str, Any]] = []
    for spec in LANE_SPECS:
        try:
            lanes.append(build_lane_snapshot(root, spec))
        except Exception as exc:  # one broken lane must not hide the others
            lanes.append(
                {
                    "lane": spec.lane,
                    "strategy": "unknown",
                    "mode": spec.mode,
                    "as_of": None,
                    "target_source": "error",
                    "summary": f"Decision snapshot unavailable: {type(exc).__name__}",
                    "error": f"{type(exc).__name__}: {exc}",
                    "decisions": [],
                    "recent_orders": [],
                }
            )
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "lanes": lanes,
    }
    out = root / DECISIONS_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    temp.replace(out)
    return payload
