from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from tradingbot.config import BreakoutParams, MetaParams, ReversalParams
from tradingbot.portfolio.allocator import combine_sleeves
from tradingbot.strategies.breakout import BreakoutStrategy
from tradingbot.strategies.reversal import ReversalStrategy


def _bars(prices: list[float], asset: str = "A") -> pl.DataFrame:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    rows = []
    for i, close in enumerate(prices):
        rows.append(
            {
                "timestamp": start + timedelta(days=i),
                "asset": asset,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 100.0,
            }
        )
    return pl.DataFrame(rows)


def test_breakout_enters_and_exits() -> None:
    prices = [100.0] * 30 + [101.0, 103.0, 107.0, 110.0, 104.0, 95.0, 90.0]
    bars = _bars(prices)
    params = BreakoutParams(
        lookback=10,
        exit_lookback=5,
        atr_window=5,
        volume_filter=False,
        vol_target=False,
        rebalance="D",
        max_weight=0.2,
    )
    result = BreakoutStrategy(params).generate_weights(bars)
    assert not result.weights.is_empty()
    assert result.weights["weight"].max() <= 0.2 + 1e-9
    assert result.weights["weight"].min() >= -1e-9
    assert result.weights["weight"].max() > 0


def test_reversal_enters_on_drop() -> None:
    prices = [100.0] * 30 + [95.0, 90.0, 85.0, 80.0, 90.0, 95.0]
    bars = _bars(prices)
    params = ReversalParams(
        lookback=10,
        entry_z=1.0,
        exit_z=0.0,
        rsi_window=2,
        rsi_entry=20.0,
        rsi_exit=80.0,
        regime_filter=False,
        vol_target=False,
        rebalance="D",
        max_weight=0.1,
    )
    result = ReversalStrategy(params).generate_weights(bars)
    assert not result.weights.is_empty()
    assert result.weights["weight"].max() <= 0.1 + 1e-9
    assert result.weights["weight"].max() > 0


def test_allocator_caps_and_normalizes() -> None:
    bars = _bars([100.0, 101.0, 102.0, 103.0, 104.0])
    bars = pl.concat(
        [
            bars,
            bars.with_columns(pl.lit("B").alias("asset")),
        ]
    ).sort(["timestamp", "asset"])
    dates = bars["timestamp"].unique().sort()
    sleeve_a = pl.DataFrame(
        {
            "timestamp": [dates[-1]] * 2,
            "asset": ["A", "B"],
            "weight": [0.5, 0.5],
        }
    )
    sleeve_b = pl.DataFrame(
        {
            "timestamp": [dates[-1]] * 2,
            "asset": ["A", "B"],
            "weight": [0.2, 0.0],
        }
    )
    params = MetaParams(
        sleeves={"trend": 0.5, "breakout": 0.5},
        lookback=3,
        min_history=2,
        rebalance="W",
        max_gross=0.8,
        max_asset_weight=0.5,
        vol_target=False,
        correlation_penalty=False,
    )
    allocation = combine_sleeves(
        bars,
        {"trend": sleeve_a, "breakout": sleeve_b},
        params,
    )
    assert not allocation.weights.is_empty()
    assert abs(sum(allocation.budgets.values()) - 1.0) < 1e-9
    gross = allocation.weights.group_by("timestamp").agg(
        pl.col("weight").abs().sum().alias("gross")
    )
    assert gross["gross"].max() <= 0.8 + 1e-9
