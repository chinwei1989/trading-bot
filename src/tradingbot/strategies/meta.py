"""Meta portfolio that allocates across trend, breakout, reversal, and XSMOM."""

from __future__ import annotations

import polars as pl

from tradingbot.config import MetaParams, StrategyConfig
from tradingbot.portfolio.allocator import combine_sleeves
from tradingbot.strategies.base import Strategy, StrategyResult
from tradingbot.strategies.breakout import BreakoutStrategy
from tradingbot.strategies.reversal import ReversalStrategy
from tradingbot.strategies.trend import TrendStrategy
from tradingbot.strategies.xsmom import XsmomStrategy


class MetaStrategy:
    name = "meta"

    def __init__(self, config: StrategyConfig, periods_per_year: int = 365):
        self.config = config
        self.params: MetaParams = config.meta
        self.periods_per_year = periods_per_year
        self.sleeves: dict[str, Strategy] = {
            "trend": TrendStrategy(config.trend, periods_per_year),
            "breakout": BreakoutStrategy(config.breakout, periods_per_year),
            "reversal": ReversalStrategy(config.reversal, periods_per_year),
            "xsmom": XsmomStrategy(config.xsmom, periods_per_year),
        }

    def generate_weights(self, bars: pl.DataFrame) -> StrategyResult:
        weights: dict[str, pl.DataFrame] = {}
        for name, strategy in self.sleeves.items():
            if name not in self.params.sleeves:
                continue
            result = strategy.generate_weights(bars)
            if not result.weights.is_empty():
                weights[name] = result.weights
        allocation = combine_sleeves(
            bars,
            weights,
            self.params,
            periods_per_year=self.periods_per_year,
        )
        params = self.params.model_dump()
        params["last_budgets"] = allocation.budgets
        return StrategyResult(self.name, allocation.weights, params)
