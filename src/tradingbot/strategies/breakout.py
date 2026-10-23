"""Donchian/ATR breakout strategy."""

from __future__ import annotations

import polars as pl

from tradingbot.config import BreakoutParams
from tradingbot.data.store import asset_columns, wide
from tradingbot.features.indicators import (
    atr,
    cap_weights,
    rebalance_dates,
    returns,
    scale_to_target_vol,
)
from tradingbot.strategies.base import StrategyResult


class BreakoutStrategy:
    name = "breakout"

    def __init__(self, params: BreakoutParams, periods_per_year: int = 365):
        self.params = params
        self.periods_per_year = periods_per_year

    def generate_weights(self, bars: pl.DataFrame) -> StrategyResult:
        p = self.params
        close = wide(bars, "close").sort("timestamp")
        assets = asset_columns(close)
        if not assets:
            return StrategyResult(self.name, pl.DataFrame(), p.model_dump())
        close = close.with_columns([pl.col(a).forward_fill() for a in assets])

        high = wide(bars, "high").sort("timestamp").with_columns(
            [pl.col(a).forward_fill() for a in assets]
        )
        low = wide(bars, "low").sort("timestamp").with_columns(
            [pl.col(a).forward_fill() for a in assets]
        )
        volume = wide(bars, "volume").sort("timestamp").with_columns(
            [pl.col(a).forward_fill().fill_null(0.0) for a in assets]
        )
        atr_wide = (
            atr(bars, p.atr_window)
            .pivot(index="timestamp", on="asset", values="atr")
            .sort("timestamp")
        )
        for asset in assets:
            if asset not in atr_wide.columns:
                atr_wide = atr_wide.with_columns(pl.lit(None).alias(asset))
        atr_wide = atr_wide.select(["timestamp", *assets]).with_columns(
            [pl.col(a).forward_fill() for a in assets]
        )

        upper_entry = high.select(
            [pl.col(a).rolling_max(p.lookback).shift(1).alias(a) for a in assets]
        )
        lower_entry = low.select(
            [pl.col(a).rolling_min(p.lookback).shift(1).alias(a) for a in assets]
        )
        lower_exit = low.select(
            [pl.col(a).rolling_min(p.exit_lookback).shift(1).alias(a) for a in assets]
        )
        upper_exit = high.select(
            [pl.col(a).rolling_max(p.exit_lookback).shift(1).alias(a) for a in assets]
        )
        volume_ok = volume.select(
            [
                (
                    pl.col(a)
                    > pl.col(a).rolling_mean(p.volume_window).shift(1)
                    * p.volume_multiplier
                ).alias(a)
                for a in assets
            ]
        )
        if not p.volume_filter:
            volume_ok = volume.with_columns(
                [pl.lit(True).alias(a) for a in assets]
            ).select(assets)

        close_np = close.select(assets).to_numpy()
        upper_entry_np = upper_entry.select(assets).to_numpy()
        lower_entry_np = lower_entry.select(assets).to_numpy()
        lower_exit_np = lower_exit.select(assets).to_numpy()
        upper_exit_np = upper_exit.select(assets).to_numpy()
        volume_np = volume_ok.select(assets).to_numpy()
        atr_np = atr_wide.select(assets).to_numpy()

        timestamps = close["timestamp"].to_list()
        state = [0] * len(assets)
        matrix: list[dict[str, float]] = []
        for i in range(len(close_np)):
            row = {asset: 0.0 for asset in assets}
            for j, asset in enumerate(assets):
                price = close_np[i, j]
                atr_value = atr_np[i, j]
                if price is None or not (price > 0):
                    continue
                if state[j] == 0:
                    if (
                        upper_entry_np[i, j] is not None
                        and price > upper_entry_np[i, j]
                        and (volume_np[i, j] is None or bool(volume_np[i, j]))
                    ):
                        state[j] = 1
                    elif (
                        p.long_short
                        and lower_entry_np[i, j] is not None
                        and price < lower_entry_np[i, j]
                        and (volume_np[i, j] is None or bool(volume_np[i, j]))
                    ):
                        state[j] = -1
                elif (
                    state[j] == 1
                    and lower_exit_np[i, j] is not None
                    and price < lower_exit_np[i, j]
                ) or (
                    state[j] == -1
                    and upper_exit_np[i, j] is not None
                    and price > upper_exit_np[i, j]
                ):
                    state[j] = 0
                if state[j] == 0:
                    continue
                stop_distance = (
                    p.atr_stop * float(atr_value) / float(price)
                    if atr_value is not None and atr_value > 0
                    else 0.10
                )
                weight = min(p.max_weight, p.risk_per_trade / max(stop_distance, 0.005))
                row[asset] = weight if state[j] > 0 else -weight
            matrix.append(row)

        raw = pl.DataFrame({"timestamp": timestamps, **{a: [r[a] for r in matrix] for a in assets}})
        dates = rebalance_dates(raw["timestamp"], p.rebalance)
        raw = raw.filter(pl.col("timestamp").is_in(dates))
        weights = raw.unpivot(index="timestamp", variable_name="asset", value_name="weight")
        weights = weights.drop_nulls("weight").sort(["timestamp", "asset"])
        if p.vol_target and not weights.is_empty():
            weights = scale_to_target_vol(
                weights,
                returns(close),
                target_vol=p.target_vol,
                window=max(p.vol_window, 20),
                periods_per_year=self.periods_per_year,
            )
        weights = cap_weights(weights, p.max_weight, p.max_gross)
        return StrategyResult(self.name, weights, p.model_dump())
