"""Meta allocator across strategy sleeves.

The allocator is deliberately simple and causal:

- each sleeve's weights are forward-filled onto the daily grid;
- sleeve return proxies use yesterday's weights against today's asset returns;
- trailing volatility and correlation are measured only through the decision date;
- fixed sleeve budgets are adjusted by inverse volatility and a positive-
  correlation penalty, capped per sleeve, then gross/vol capped.

It is not a performance guarantee. It is a capital-allocation layer that makes
multiple sleeves share one risk budget instead of running as independent bots.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl

from tradingbot.config import MetaParams
from tradingbot.data.store import asset_columns, wide
from tradingbot.features.indicators import (
    cap_weights,
    rebalance_dates,
    returns,
    scale_to_target_vol,
)


@dataclass
class MetaAllocation:
    weights: pl.DataFrame
    budgets: dict[str, float]
    budgets_by_date: list[dict[str, Any]]


def _daily_weights(
    weights: pl.DataFrame,
    dates: pl.Series,
    assets: list[str],
) -> pl.DataFrame:
    if weights.is_empty():
        return pl.DataFrame({"timestamp": dates}).with_columns(
            [pl.lit(0.0).alias(asset) for asset in assets]
        )
    frame = (
        weights.select(["timestamp", "asset", "weight"])
        .pivot(index="timestamp", on="asset", values="weight")
        .sort("timestamp")
    )
    for asset in assets:
        if asset not in frame.columns:
            frame = frame.with_columns(pl.lit(0.0).alias(asset))
    frame = frame.select(["timestamp", *assets])
    return (
        pl.DataFrame({"timestamp": dates})
        .join(frame, on="timestamp", how="left")
        .sort("timestamp")
        .with_columns([pl.col(asset).forward_fill().fill_null(0.0) for asset in assets])
    )


def _normalize_budgets(
    base: dict[str, float],
    vol: dict[str, float],
    corr: np.ndarray,
    names: list[str],
    params: MetaParams,
) -> dict[str, float]:
    raw: dict[str, float] = {}
    for i, name in enumerate(names):
        v = max(vol.get(name, 0.0), 1e-6)
        penalty = 1.0
        if params.correlation_penalty and len(names) > 1:
            others = [corr[i, j] for j in range(len(names)) if j != i]
            positives = [max(0.0, value) for value in others if np.isfinite(value)]
            if positives:
                penalty = 1.0 / (1.0 + float(np.mean(positives)))
        raw[name] = max(0.0, base.get(name, 0.0)) / v * penalty
    total = sum(raw.values())
    if total <= 1e-12:
        raw = {name: 1.0 for name in names}
        total = float(len(names))
    budgets = {name: value / total for name, value in raw.items()}
    budgets = {
        name: min(params.max_sleeve_weight, value) for name, value in budgets.items()
    }
    total = sum(budgets.values())
    if total <= 1e-12:
        return {name: 1.0 / len(names) for name in names}
    return {name: value / total for name, value in budgets.items()}


def combine_sleeves(
    bars: pl.DataFrame,
    sleeve_weights: dict[str, pl.DataFrame],
    params: MetaParams,
    periods_per_year: int = 365,
) -> MetaAllocation:
    close = wide(bars, "close").sort("timestamp")
    assets = asset_columns(close)
    if not assets:
        return MetaAllocation(pl.DataFrame(), {}, [])
    close = close.with_columns([pl.col(asset).forward_fill() for asset in assets])
    dates = close["timestamp"]
    names = sorted(sleeve_weights)
    if not names:
        return MetaAllocation(pl.DataFrame(), {}, [])

    daily = {
        name: _daily_weights(sleeve_weights[name], dates, assets) for name in names
    }
    rets = returns(close)
    ret_np = rets.select(assets).to_numpy()
    sleeve_return_matrix: dict[str, np.ndarray] = {}
    for name in names:
        w = daily[name].select(assets).to_numpy()
        # Weights are decided at close t and earn the next day's return.
        shifted = np.vstack([np.zeros((1, len(assets))), w[:-1]])
        sleeve_return_matrix[name] = np.nansum(shifted * ret_np, axis=1)

    rebalance = rebalance_dates(dates, params.rebalance)
    date_to_index = {ts: i for i, ts in enumerate(dates.to_list())}
    base_total = sum(max(0.0, params.sleeves.get(name, 0.0)) for name in names)
    base = {
        name: max(0.0, params.sleeves.get(name, 0.0)) / base_total
        if base_total > 0
        else 1.0 / len(names)
        for name in names
    }

    rows: list[dict[str, Any]] = []
    budgets_by_date: list[dict[str, Any]] = []
    last_budgets = base
    last_combined = np.zeros(len(assets))
    for ts in rebalance:
        i = date_to_index.get(ts)
        if i is None:
            continue
        budgets = base
        if i >= params.min_history:
            hist = np.vstack(
                [sleeve_return_matrix[name][max(0, i - params.lookback + 1) : i + 1] for name in names]
            ).T
            hist = hist[np.isfinite(hist).all(axis=1)]
            if hist.shape[0] >= params.min_history:
                vol = {
                    name: float(np.std(hist[:, j], ddof=1))
                    for j, name in enumerate(names)
                }
                with np.errstate(invalid="ignore", divide="ignore"):
                    corr = np.corrcoef(hist, rowvar=False)
                corr = np.nan_to_num(np.atleast_2d(corr), nan=0.0)
                budgets = _normalize_budgets(base, vol, corr, names, params)
        last_budgets = budgets
        combined = np.zeros(len(assets))
        for name in names:
            combined += budgets[name] * daily[name].select(assets).to_numpy()[i]

        if params.max_asset_vol is not None:
            hist = ret_np[max(0, i - max(params.vol_window, 20) + 1) : i + 1]
            # Early bars can be all-NaN. Computing nanstd there emits a
            # degrees-of-freedom warning and provides no useful vol estimate.
            valid = hist[np.isfinite(hist).all(axis=1)]
            if valid.shape[0] >= 2:
                asset_vol = np.nanstd(valid, axis=0) * np.sqrt(periods_per_year)
                combined = np.where(asset_vol > params.max_asset_vol, 0.0, combined)

        if params.no_trade_band > 0:
            change = np.abs(combined - last_combined)
            keep = (change < params.no_trade_band) & (combined != 0.0)
            combined = np.where(keep, last_combined, combined)
        last_combined = combined

        for j, asset in enumerate(assets):
            rows.append({"timestamp": ts, "asset": asset, "weight": float(combined[j])})
        budgets_by_date.append({"timestamp": ts, **budgets})

    if not rows:
        return MetaAllocation(pl.DataFrame(), last_budgets, [])
    weights = pl.DataFrame(rows).sort(["timestamp", "asset"])
    if params.vol_target:
        weights = scale_to_target_vol(
            weights,
            returns(close),
            target_vol=float(params.target_vol),
            window=max(params.vol_window, 20),
            periods_per_year=periods_per_year,
        )
    weights = cap_weights(weights, params.max_asset_weight, params.max_gross)
    return MetaAllocation(weights, last_budgets, budgets_by_date)
