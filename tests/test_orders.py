from __future__ import annotations

from datetime import UTC, datetime

import polars as pl

from tradingbot.execution.broker import Position
from tradingbot.execution.orders import plan_orders, reconcile


def _weights(rows: list[tuple[str, float]]) -> pl.DataFrame:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    return pl.DataFrame(
        {"timestamp": [ts] * len(rows), "asset": [r[0] for r in rows], "weight": [r[1] for r in rows]}
    )


def test_plan_orders_from_flat() -> None:
    weights = _weights([("BTC", 0.5), ("ETH", 0.0)])
    orders = plan_orders(
        weights, equity=1000.0, prices={"BTC": 100.0, "ETH": 50.0}, positions={}
    )
    assert len(orders) == 1
    assert orders[0].asset == "BTC"
    assert orders[0].side == "buy"
    assert orders[0].qty == 5.0


def test_plan_orders_respects_current_position() -> None:
    weights = _weights([("BTC", 0.5)])
    positions = {"BTC": Position("BTC", 2.0, 200.0, 100.0)}
    orders = plan_orders(
        weights, equity=1000.0, prices={"BTC": 100.0}, positions=positions
    )
    assert len(orders) == 1
    assert orders[0].qty == 3.0


def test_plan_orders_closes_orphan_position() -> None:
    weights = _weights([("BTC", 0.0)])
    positions = {"ETH": Position("ETH", 4.0, 200.0, 50.0)}
    orders = plan_orders(
        weights, equity=1000.0, prices={"BTC": 100.0, "ETH": 50.0}, positions=positions
    )
    assert len(orders) == 1
    assert orders[0].asset == "ETH"
    assert orders[0].side == "sell"
    assert orders[0].qty == 4.0


def test_plan_orders_min_notional() -> None:
    weights = _weights([("BTC", 0.001)])
    orders = plan_orders(
        weights, equity=1000.0, prices={"BTC": 100.0}, positions={}, min_notional=10.0
    )
    assert orders == []


def test_reconcile_drift() -> None:
    weights = _weights([("BTC", 0.5)])
    positions = {"BTC": Position("BTC", 2.0, 200.0, 100.0)}
    rec = reconcile(weights, equity=1000.0, prices={"BTC": 100.0}, positions=positions)
    row = rec.filter(pl.col("asset") == "BTC").row(0, named=True)
    assert row["target_value"] == 500.0
    assert row["current_value"] == 200.0
    assert row["drift_value"] == -300.0
