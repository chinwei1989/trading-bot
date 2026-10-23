from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from tradingbot.backtest.carry import CarryParams, run_carry


def _bars(asset: str, days: int, start_price: float = 100.0) -> pl.DataFrame:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(days):
        price = start_price * (1.0 + 0.0005 * i)
        rows.append(
            {
                "timestamp": start + timedelta(days=i),
                "asset": asset,
                "open": price,
                "high": price * 1.01,
                "low": price * 0.99,
                "close": price,
                "volume": 1000.0,
            }
        )
    return pl.DataFrame(rows)


def _funding(asset: str, days: int, rate: float) -> pl.DataFrame:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(days):
        for hour in (0, 8, 16):
            rows.append(
                {
                    "timestamp": start + timedelta(days=i, hours=hour),
                    "asset": asset,
                    "funding_rate": rate,
                }
            )
    return pl.DataFrame(rows)


def _inputs(rate: float = 0.0001, days: int = 60) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    spot = pl.concat([_bars("AAA", days), _bars("BBB", days, 200.0)])
    perp = spot.with_columns((pl.col("close") * 1.001).alias("close"))
    funding = pl.concat([_funding("AAA", days, rate), _funding("BBB", days, rate)])
    return spot, perp, funding


def test_carry_opens_positive_funding_and_is_delta_neutral() -> None:
    spot, perp, funding = _inputs()
    result = run_carry(
        spot,
        perp,
        funding,
        CarryParams(
            lookback_days=5,
            rebalance_days=5,
            min_funding_apr=0.05,
            top_n=2,
            max_weight=0.25,
            max_gross=0.80,
            spot_cost_bps=0,
            perp_cost_bps=0,
        ),
    )
    assert not result.weights.is_empty()
    assert set(result.weights["asset"].unique().to_list()) == {"AAA", "BBB"}
    assert result.daily["funding_return"].sum() > 0
    assert result.metrics["gross_exposure_avg"] <= 0.80 + 1e-9
    assert result.metrics["net_exposure_avg"] == 0.0


def test_negative_funding_has_no_position() -> None:
    spot, perp, funding = _inputs(rate=-0.0001)
    result = run_carry(
        spot,
        perp,
        funding,
        CarryParams(lookback_days=5, rebalance_days=5, min_funding_apr=0.05),
    )
    assert result.weights.is_empty()
    assert result.daily["funding_return"].sum() == 0.0
    assert result.daily["equity"].tail(1)[0] == 10_000.0


def test_carry_costs_are_charged_on_rebalance() -> None:
    spot, perp, funding = _inputs()
    result = run_carry(
        spot,
        perp,
        funding,
        CarryParams(lookback_days=5, rebalance_days=5, spot_cost_bps=10, perp_cost_bps=10),
    )
    assert result.daily["cost"].sum() > 0
    assert result.daily["turnover"].sum() > 0
