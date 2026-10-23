"""Multi-asset time-series trend strategy."""

from __future__ import annotations

import math

import polars as pl

from tradingbot.config import TrendParams
from tradingbot.data.store import asset_columns, wide
from tradingbot.features.indicators import (
    cap_weights,
    rebalance_dates,
    returns,
    scale_to_target_vol,
)
from tradingbot.strategies.base import StrategyResult


class TrendStrategy:
    name = "trend"

    def __init__(self, params: TrendParams, periods_per_year: int = 365):
        self.params = params
        self.periods_per_year = periods_per_year

    def generate_weights(self, bars: pl.DataFrame) -> StrategyResult:
        p = self.params
        close = wide(bars, "close").sort("timestamp")
        assets = asset_columns(close)
        if not assets:
            return StrategyResult(self.name, pl.DataFrame(), p.model_dump())
        # Forward-fill holidays/gaps; a missing bar is not an exit signal.
        close = close.with_columns([pl.col(a).forward_fill() for a in assets])

        df = close
        for c in assets:
            df = df.with_columns(
                pl.col(c).rolling_mean(p.lookback).alias(f"{c}__sma"),
                (
                    pl.col(c).pct_change().rolling_std(p.vol_window)
                    * math.sqrt(self.periods_per_year)
                ).alias(f"{c}__vol"),
            )

        exprs: list[pl.Expr] = []
        for c in assets:
            above = pl.col(c) > pl.col(f"{c}__sma")
            below = pl.col(c) < pl.col(f"{c}__sma")
            if p.long_short:
                signal = pl.when(above).then(1.0).when(below).then(-1.0).otherwise(0.0)
            else:
                signal = pl.when(above).then(1.0).otherwise(0.0)
            weight = signal * p.target_vol / pl.col(f"{c}__vol").clip(0.01, 5.0)
            weight = weight.clip(-p.max_weight, p.max_weight)
            if not p.long_short:
                weight = weight.clip(lower_bound=0.0)
            exprs.append(weight.alias(c))

        raw = df.select(["timestamp", *exprs]).with_columns(
            [pl.col(c).fill_null(0.0) for c in assets]
        )
        dates = rebalance_dates(raw["timestamp"], p.rebalance)
        raw = raw.filter(pl.col("timestamp").is_in(dates))

        weights = raw.unpivot(index="timestamp", variable_name="asset", value_name="weight")
        weights = weights.drop_nulls("weight").sort(["timestamp", "asset"])

        if p.vol_target and not weights.is_empty():
            rets = returns(close)
            weights = scale_to_target_vol(
                weights,
                rets,
                target_vol=p.target_vol,
                window=max(p.vol_window, 20),
                periods_per_year=self.periods_per_year,
            )
        weights = cap_weights(weights, p.max_weight, p.max_gross)
        return StrategyResult(self.name, weights, p.model_dump())
