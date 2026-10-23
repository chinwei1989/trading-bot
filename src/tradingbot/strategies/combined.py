"""Combine trend and cross-sectional momentum sleeves.

Each sleeve is generated independently, forward-filled onto the same daily
grid, then blended by allocation weight. The combined weights are volatility
scaled and gross-capped.
"""

from __future__ import annotations

import polars as pl

from tradingbot.config import CombinedParams, StrategyConfig
from tradingbot.features.indicators import cap_weights, scale_to_target_vol
from tradingbot.strategies.base import StrategyResult
from tradingbot.strategies.trend import TrendStrategy
from tradingbot.strategies.xsmom import XsmomStrategy


def _daily_weights(
    weights: pl.DataFrame,
    dates: pl.Series,
    assets: list[str],
) -> pl.DataFrame:
    if weights.is_empty():
        return pl.DataFrame({"timestamp": dates}).with_columns(
            [pl.lit(0.0).alias(a) for a in assets]
        )
    w = (
        weights.select(["timestamp", "asset", "weight"])
        .pivot(index="timestamp", on="asset", values="weight")
        .sort("timestamp")
    )
    for asset in assets:
        if asset not in w.columns:
            w = w.with_columns(pl.lit(0.0).alias(asset))
    w = w.select(["timestamp", *assets])
    return (
        pl.DataFrame({"timestamp": dates})
        .join(w, on="timestamp", how="left")
        .sort("timestamp")
        .with_columns([pl.col(a).forward_fill().fill_null(0.0) for a in assets])
    )


class CombinedStrategy:
    name = "combined"

    def __init__(self, config: StrategyConfig, periods_per_year: int = 365):
        self.config = config
        self.params: CombinedParams = config.combined
        self.periods_per_year = periods_per_year
        self.trend = TrendStrategy(config.trend, periods_per_year)
        self.xsmom = XsmomStrategy(config.xsmom, periods_per_year)

    def generate_weights(self, bars: pl.DataFrame) -> StrategyResult:
        trend = self.trend.generate_weights(bars)
        xsmom = self.xsmom.generate_weights(bars)
        dates = bars["timestamp"].unique().sort()
        assets = sorted(bars["asset"].unique().to_list())
        if not assets:
            return StrategyResult(self.name, pl.DataFrame(), self.params.model_dump())

        trend_daily = _daily_weights(trend.weights, dates, assets)
        xsmom_daily = _daily_weights(xsmom.weights, dates, assets)
        date_cols = ["timestamp", *assets]
        trend_mat = trend_daily.select(date_cols)
        xsmom_mat = xsmom_daily.select(date_cols)

        combined = trend_mat.with_columns(
            [
                (
                    pl.col(a) * self.params.trend_weight
                    + xsmom_mat[a] * self.params.xsmom_weight
                ).alias(a)
                for a in assets
            ]
        )

        rebalance_dates = set()
        if not trend.weights.is_empty():
            rebalance_dates |= set(trend.weights["timestamp"].to_list())
        if not xsmom.weights.is_empty():
            rebalance_dates |= set(xsmom.weights["timestamp"].to_list())
        if not rebalance_dates:
            return StrategyResult(self.name, pl.DataFrame(), self.params.model_dump())
        combined = combined.filter(pl.col("timestamp").is_in(sorted(rebalance_dates)))

        weights = combined.unpivot(index="timestamp", variable_name="asset", value_name="weight")
        weights = weights.drop_nulls("weight").sort(["timestamp", "asset"])
        weights = scale_to_target_vol(
            weights,
            _returns_from_bars(bars),
            target_vol=self.params.target_vol,
            window=max(self.params.vol_window, 20),
            periods_per_year=self.periods_per_year,
        )
        weights = cap_weights(weights, 1.0, self.params.max_gross)
        return StrategyResult(self.name, weights, self.params.model_dump())


def _returns_from_bars(bars: pl.DataFrame) -> pl.DataFrame:
    close = bars.select(["timestamp", "asset", "close"]).pivot(
        index="timestamp", on="asset", values="close"
    ).sort("timestamp")
    cols = [c for c in close.columns if c != "timestamp"]
    return close.with_columns([pl.col(c).pct_change().alias(c) for c in cols])
