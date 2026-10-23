"""Cost-aware vectorized portfolio backtester.

Execution convention:
  - A target weight for timestamp t is a decision made at the close of t.
  - It becomes effective at the next bar's open (execution_lag=1).
  - Returns are measured open-to-open, so there is no same-close fill.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl

from tradingbot.backtest.metrics import compute_metrics
from tradingbot.config import BacktestConfig
from tradingbot.data.store import asset_columns, long, normalize_bars, wide


@dataclass
class BacktestResult:
    daily: pl.DataFrame
    effective_weights: pl.DataFrame
    metrics: dict[str, float]
    config: BacktestConfig


def _weights_wide(
    weights: pl.DataFrame,
    dates: pl.Series,
    assets: list[str],
) -> pl.DataFrame:
    if weights.is_empty() or "weight" not in weights.columns:
        frame = pl.DataFrame({"timestamp": dates})
        return frame.with_columns([pl.lit(0.0).alias(a) for a in assets])
    w = (
        weights.select(["timestamp", "asset", "weight"])
        .pivot(index="timestamp", on="asset", values="weight")
        .sort("timestamp")
    )
    for a in assets:
        if a not in w.columns:
            w = w.with_columns(pl.lit(0.0).alias(a))
    w = w.select(["timestamp", *assets])
    daily = (
        pl.DataFrame({"timestamp": dates})
        .join(w, on="timestamp", how="left")
        .sort("timestamp")
        .with_columns([pl.col(a).forward_fill().fill_null(0.0) for a in assets])
    )
    return daily


def run_backtest(
    bars: pl.DataFrame,
    weights: pl.DataFrame,
    config: BacktestConfig | None = None,
) -> BacktestResult:
    cfg = config or BacktestConfig()
    bars = normalize_bars(bars)
    open_w = wide(bars, "open").sort("timestamp")
    assets = asset_columns(open_w)
    open_w = open_w.with_columns([pl.col(a).forward_fill() for a in assets])
    if not assets:
        empty = pl.DataFrame(
            {
                "timestamp": [],
                "gross_return": [],
                "cost": [],
                "net_return": [],
                "equity": [],
                "turnover": [],
                "gross_exposure": [],
                "net_exposure": [],
            }
        )
        return BacktestResult(empty, pl.DataFrame(), {}, cfg)

    dates = open_w["timestamp"]
    weights_daily = _weights_wide(weights, dates, assets)
    lag = max(0, cfg.execution_lag)
    effective = weights_daily.with_columns(
        [pl.col(a).shift(lag).fill_null(0.0).alias(a) for a in assets]
    )

    ret = open_w.select(["timestamp", *assets]).with_columns(
        [(pl.col(a).shift(-1) / pl.col(a) - 1.0).alias(a) for a in assets]
    )
    eff_np = np.nan_to_num(effective.select(assets).to_numpy(), nan=0.0, posinf=0.0, neginf=0.0)
    ret_np = np.nan_to_num(ret.select(assets).to_numpy(), nan=0.0, posinf=0.0, neginf=0.0)

    gross = np.sum(eff_np * ret_np, axis=1)
    gross_exposure = np.sum(np.abs(eff_np), axis=1)
    net_exposure = np.sum(eff_np, axis=1)
    cash_weight = np.clip(1.0 - net_exposure, 0.0, 1.0)
    gross = gross + cash_weight * (cfg.risk_free_rate / cfg.periods_per_year)

    delta = np.abs(np.diff(eff_np, axis=0, prepend=np.zeros((1, eff_np.shape[1]))))
    turnover = delta.sum(axis=1)
    cost = turnover * (cfg.cost_bps + cfg.slippage_bps) / 10_000.0
    net = gross - cost
    equity = cfg.initial_capital * np.cumprod(1.0 + net)

    daily = pl.DataFrame(
        {
            "timestamp": dates,
            "gross_return": gross,
            "cost": cost,
            "net_return": net,
            "equity": equity,
            "turnover": turnover,
            "gross_exposure": gross_exposure,
            "net_exposure": net_exposure,
        }
    )
    metrics = compute_metrics(
        daily["net_return"],
        periods_per_year=cfg.periods_per_year,
        turnover=daily["turnover"],
        gross_exposure=daily["gross_exposure"],
        net_exposure=daily["net_exposure"],
    )
    metrics["final_equity"] = float(equity[-1]) if equity.size else cfg.initial_capital
    return BacktestResult(
        daily=daily,
        effective_weights=long(effective, "weight"),
        metrics=metrics,
        config=cfg,
    )
