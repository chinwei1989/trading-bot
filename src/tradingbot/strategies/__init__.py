"""Strategy implementations."""

from __future__ import annotations

from tradingbot.config import StrategyConfig
from tradingbot.strategies.base import Strategy, StrategyResult
from tradingbot.strategies.breakout import BreakoutStrategy
from tradingbot.strategies.combined import CombinedStrategy
from tradingbot.strategies.meta import MetaStrategy
from tradingbot.strategies.reversal import ReversalStrategy
from tradingbot.strategies.trend import TrendStrategy
from tradingbot.strategies.xsmom import XsmomStrategy


def build_strategy(config: StrategyConfig, periods_per_year: int = 365) -> Strategy:
    if config.name == "trend":
        return TrendStrategy(config.trend, periods_per_year)
    if config.name == "xsmom":
        return XsmomStrategy(config.xsmom, periods_per_year)
    if config.name == "breakout":
        return BreakoutStrategy(config.breakout, periods_per_year)
    if config.name == "reversal":
        return ReversalStrategy(config.reversal, periods_per_year)
    if config.name == "meta":
        return MetaStrategy(config, periods_per_year)
    if config.name == "combined":
        return CombinedStrategy(config, periods_per_year)
    raise ValueError(f"unknown strategy: {config.name}")


__all__ = [
    "BreakoutStrategy",
    "CombinedStrategy",
    "MetaStrategy",
    "ReversalStrategy",
    "Strategy",
    "StrategyResult",
    "TrendStrategy",
    "XsmomStrategy",
    "build_strategy",
]
