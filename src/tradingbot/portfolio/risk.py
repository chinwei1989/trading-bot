"""Deterministic risk checks with veto power."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import polars as pl

from tradingbot.config import RiskConfig


class RiskLimitBreached(RuntimeError):
    """Raised when a hard risk limit is violated."""


@dataclass
class RiskReport:
    max_gross: float
    max_net: float
    max_asset: float
    drawdown: float
    breached: list[str]


def current_drawdown(equity: np.ndarray | list[float]) -> float:
    values = np.asarray(equity, dtype=float)
    if values.size == 0:
        return 0.0
    peak = np.maximum.accumulate(values)
    dd = values / peak - 1.0
    return float(dd[-1])


def kill_switch_active(path: str | Path) -> bool:
    return Path(path).exists()


def inspect_weights(weights: pl.DataFrame) -> tuple[float, float, float]:
    """Return (max gross, max abs net, max single asset weight)."""
    if weights.is_empty():
        return 0.0, 0.0, 0.0
    grouped = weights.group_by("timestamp").agg(
        pl.col("weight").abs().sum().alias("gross"),
        pl.col("weight").sum().abs().alias("net"),
    )
    return (
        float(cast(Any, grouped["gross"].max()) or 0.0),
        float(cast(Any, grouped["net"].max()) or 0.0),
        float(cast(Any, weights["weight"].abs().max()) or 0.0),
    )


def check_limits(
    weights: pl.DataFrame,
    config: RiskConfig,
    equity: list[float] | None = None,
) -> RiskReport:
    gross, net, asset = inspect_weights(weights)
    dd = current_drawdown(equity) if equity else 0.0
    breached: list[str] = []
    if gross > config.max_gross + 1e-9:
        breached.append(f"gross {gross:.3f} > {config.max_gross:.3f}")
    if net > config.max_net + 1e-9:
        breached.append(f"net {net:.3f} > {config.max_net:.3f}")
    if asset > config.max_asset_weight + 1e-9:
        breached.append(f"asset {asset:.3f} > {config.max_asset_weight:.3f}")
    if dd < -config.max_drawdown - 1e-9:
        breached.append(f"drawdown {dd:.3f} < -{config.max_drawdown:.3f}")
    return RiskReport(gross, net, asset, dd, breached)


def enforce_limits(weights: pl.DataFrame, config: RiskConfig) -> pl.DataFrame:
    """Clip per-asset weights and scale gross/net exposure to limits."""
    if weights.is_empty():
        return weights
    out = weights.with_columns(
        pl.col("weight").clip(-config.max_asset_weight, config.max_asset_weight)
    )
    stats = out.group_by("timestamp").agg(
        pl.col("weight").abs().sum().alias("gross"),
        pl.col("weight").sum().abs().alias("net"),
    )
    out = out.join(stats, on="timestamp", how="left").with_columns(
        pl.max_horizontal(
            pl.when(pl.col("gross") > 0)
            .then(pl.col("gross") / config.max_gross)
            .otherwise(1.0),
            pl.when(pl.col("net") > 0)
            .then(pl.col("net") / config.max_net)
            .otherwise(1.0),
            pl.lit(1.0),
        ).alias("_scale")
    )
    out = out.with_columns((pl.col("weight") / pl.col("_scale")).alias("weight"))
    return out.select(["timestamp", "asset", "weight"]).sort(["timestamp", "asset"])


def assert_safe(
    weights: pl.DataFrame,
    config: RiskConfig,
    equity: list[float] | None = None,
    kill_file: str | Path | None = None,
) -> None:
    if kill_file and kill_switch_active(kill_file):
        raise RiskLimitBreached(f"kill switch present: {kill_file}")
    report = check_limits(weights, config, equity)
    if report.breached:
        raise RiskLimitBreached("; ".join(report.breached))
