from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from tradingbot.config import TrendParams
from tradingbot.strategies.trend import TrendStrategy


def _bars(prices: dict[str, list[float]]) -> pl.DataFrame:
    start = datetime(2023, 1, 1, tzinfo=UTC)
    rows = []
    for asset, series in prices.items():
        for i, close in enumerate(series):
            rows.append(
                {
                    "timestamp": start + timedelta(days=i),
                    "asset": asset,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1.0,
                }
            )
    return pl.DataFrame(rows)


def test_trend_long_in_uptrend() -> None:
    prices = {a: [100.0 * (1.01**i) for i in range(120)] for a in ["A", "B"]}
    strategy = TrendStrategy(
        TrendParams(lookback=50, vol_window=20, target_vol=0.15, max_weight=0.5, vol_target=False)
    )
    result = strategy.generate_weights(_bars(prices))
    latest = result.weights.filter(pl.col("timestamp") == result.weights["timestamp"].max())
    assert latest.height == 2
    assert (latest["weight"] > 0).all()


def test_trend_long_only_flat_in_downtrend() -> None:
    prices = {a: [100.0 * (0.99**i) for i in range(120)] for a in ["A", "B"]}
    strategy = TrendStrategy(
        TrendParams(
            lookback=50,
            vol_window=20,
            target_vol=0.15,
            max_weight=0.5,
            long_short=False,
            vol_target=False,
        )
    )
    result = strategy.generate_weights(_bars(prices))
    assert result.weights["weight"].abs().max() == 0.0


def test_trend_short_in_downtrend() -> None:
    prices = {a: [100.0 * (0.99**i) for i in range(120)] for a in ["A", "B"]}
    strategy = TrendStrategy(
        TrendParams(
            lookback=50,
            vol_window=20,
            target_vol=0.15,
            max_weight=0.5,
            long_short=True,
            vol_target=False,
        )
    )
    result = strategy.generate_weights(_bars(prices))
    latest = result.weights.filter(pl.col("timestamp") == result.weights["timestamp"].max())
    assert (latest["weight"] < 0).all()


def test_trend_no_lookahead() -> None:
    n = 320
    prices = {a: [100.0 * (1.005**i) for i in range(n)] for a in ["A", "B", "C"]}
    bars = _bars(prices)
    strategy = TrendStrategy(
        TrendParams(lookback=50, vol_window=20, target_vol=0.15, max_weight=0.5, vol_target=True)
    )
    first = strategy.generate_weights(bars).weights
    cutoff = datetime(2023, 1, 1, tzinfo=UTC) + timedelta(days=250)
    future = bars.with_columns(
        pl.when(pl.col("timestamp") > cutoff)
        .then(pl.col("close") * 2.0)
        .otherwise(pl.col("close"))
        .alias("close")
    )
    second = strategy.generate_weights(future).weights
    a = first.filter(pl.col("timestamp") <= cutoff).sort(["timestamp", "asset"])
    b = second.filter(pl.col("timestamp") <= cutoff).sort(["timestamp", "asset"])
    assert a.equals(b)
