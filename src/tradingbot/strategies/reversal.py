"""Short-horizon mean-reversion strategy with a trend regime filter."""

from __future__ import annotations

import math

import polars as pl

from tradingbot.config import ReversalParams
from tradingbot.data.store import asset_columns, wide
from tradingbot.features.indicators import (
    cap_weights,
    rebalance_dates,
    returns,
    rsi,
    scale_to_target_vol,
    zscore,
)
from tradingbot.strategies.base import StrategyResult


class ReversalStrategy:
    name = "reversal"

    def __init__(self, params: ReversalParams, periods_per_year: int = 365):
        self.params = params
        self.periods_per_year = periods_per_year

    def generate_weights(self, bars: pl.DataFrame) -> StrategyResult:
        p = self.params
        close = wide(bars, "close").sort("timestamp")
        assets = asset_columns(close)
        if not assets:
            return StrategyResult(self.name, pl.DataFrame(), p.model_dump())
        close = close.with_columns([pl.col(a).forward_fill() for a in assets])

        z = zscore(close, p.lookback)
        rsi_values = rsi(close, p.rsi_window)
        regime = close.select(
            [pl.col(a).rolling_mean(p.regime_lookback).alias(a) for a in assets]
        )
        vol = (
            close.select(
                [
                    (
                        pl.col(a).pct_change().rolling_std(p.vol_window)
                        * math.sqrt(self.periods_per_year)
                    ).alias(a)
                    for a in assets
                ]
            )
            .with_columns([pl.col(a).forward_fill() for a in assets])
        )

        close_np = close.select(assets).to_numpy()
        z_np = z.select(assets).to_numpy()
        rsi_np = rsi_values.select(assets).to_numpy()
        regime_np = regime.select(assets).to_numpy()
        vol_np = vol.select(assets).to_numpy()

        count = len(close_np)
        state = [0] * len(assets)
        matrix: list[dict[str, float]] = []
        for i in range(count):
            row = {asset: 0.0 for asset in assets}
            for j, asset in enumerate(assets):
                price = close_np[i, j]
                z_value = z_np[i, j]
                rsi_value = rsi_np[i, j]
                if price is None or price <= 0:
                    continue
                above_regime = not p.regime_filter or (
                    regime_np[i, j] is not None and price > regime_np[i, j]
                )
                below_regime = not p.regime_filter or (
                    regime_np[i, j] is not None and price < regime_np[i, j]
                )
                long_signal = (
                    z_value is not None and z_value <= -p.entry_z
                ) or (rsi_value is not None and rsi_value <= p.rsi_entry)
                long_exit = (
                    z_value is None
                    or z_value >= p.exit_z
                    or rsi_value is None
                    or rsi_value >= p.rsi_exit
                )
                short_signal = p.long_short and (
                    (z_value is not None and z_value >= p.entry_z)
                    or (rsi_value is not None and rsi_value >= 100.0 - p.rsi_entry)
                )
                short_exit = (
                    z_value is None
                    or z_value <= -p.exit_z
                    or rsi_value is None
                    or rsi_value <= 100.0 - p.rsi_exit
                )

                if state[j] == 0:
                    if long_signal and above_regime:
                        state[j] = 1
                    elif short_signal and below_regime:
                        state[j] = -1
                elif (state[j] == 1 and (long_exit or not above_regime)) or (
                    state[j] == -1 and (short_exit or not below_regime)
                ):
                    state[j] = 0

                if state[j] == 0:
                    continue
                asset_vol = vol_np[i, j]
                if asset_vol is None or not math.isfinite(float(asset_vol)) or asset_vol <= 0:
                    weight = p.max_weight * 0.5
                else:
                    weight = min(p.max_weight, p.target_vol / float(asset_vol))
                row[asset] = weight if state[j] > 0 else -weight
            matrix.append(row)

        timestamps = close["timestamp"].to_list()
        raw = pl.DataFrame(
            {"timestamp": timestamps, **{a: [r[a] for r in matrix] for a in assets}}
        )
        dates = rebalance_dates(raw["timestamp"], p.rebalance)
        raw = raw.filter(pl.col("timestamp").is_in(dates))
        weights = raw.unpivot(index="timestamp", variable_name="asset", value_name="weight")
        weights = weights.drop_nulls("weight").sort(["timestamp", "asset"])
        if p.vol_target and not weights.is_empty():
            weights = scale_to_target_vol(
                weights,
                returns(close),
                target_vol=p.target_vol,
                window=max(p.vol_window, 10),
                periods_per_year=self.periods_per_year,
            )
        weights = cap_weights(weights, p.max_weight, p.max_gross)
        return StrategyResult(self.name, weights, p.model_dump())
