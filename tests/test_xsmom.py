from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from tradingbot.config import XsmomParams
from tradingbot.strategies.xsmom import XsmomStrategy


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


def test_xsmom_ranks_winners_and_losers() -> None:
    rates = {"A": 0.012, "B": 0.010, "C": 0.008, "D": 0.006, "E": 0.004, "F": 0.002}
    prices = {a: [100.0 * ((1 + r) ** i) for i in range(120)] for a, r in rates.items()}
    strategy = XsmomStrategy(
        XsmomParams(
            lookback=20,
            skip=0,
            top_quantile=0.34,
            bottom_quantile=0.34,
            long_short=True,
            vol_target=False,
            min_assets=5,
            max_weight=0.5,
        )
    )
    result = strategy.generate_weights(_bars(prices))
    latest = result.weights.filter(pl.col("timestamp") == result.weights["timestamp"].max())
    weights = {r["asset"]: r["weight"] for r in latest.iter_rows(named=True)}
    assert weights["A"] > 0 and weights["B"] > 0
    assert weights["E"] < 0 and weights["F"] < 0
    assert abs(sum(weights.values())) < 1e-9


def test_xsmom_long_only() -> None:
    rates = {"A": 0.012, "B": 0.010, "C": 0.008, "D": 0.006, "E": 0.004, "F": 0.002}
    prices = {a: [100.0 * ((1 + r) ** i) for i in range(120)] for a, r in rates.items()}
    strategy = XsmomStrategy(
        XsmomParams(
            lookback=20,
            skip=0,
            top_quantile=0.34,
            bottom_quantile=0.34,
            long_short=False,
            vol_target=False,
            min_assets=5,
            max_weight=0.5,
        )
    )
    result = strategy.generate_weights(_bars(prices))
    assert (result.weights["weight"] >= 0).all()
    latest = result.weights.filter(pl.col("timestamp") == result.weights["timestamp"].max())
    assert latest.height == 6
