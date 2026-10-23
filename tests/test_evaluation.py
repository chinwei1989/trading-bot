from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl

from tradingbot.ops.evaluation import compute_tca, live_vs_backtest, order_health, rolling_metrics


def _journal() -> pl.DataFrame:
    now = datetime.now(UTC)
    return pl.DataFrame(
        {
            "ts": [now, now - timedelta(days=1)],
            "asset": ["A", "A"],
            "side": ["buy", "sell"],
            "qty": [1.0, 1.0],
            "status": ["filled", "rejected"],
            "filled_qty": [1.0, 0.0],
            "avg_price": [101.0, None],
            "reference_price": [100.0, 100.0],
        }
    )


def test_compute_tca() -> None:
    tca = compute_tca(_journal(), pl.DataFrame())
    assert tca["fills"] == 1.0
    assert tca["weighted_slip_bps"] == 100.0
    assert tca["notional"] == 101.0


def test_order_health() -> None:
    health = order_health(_journal(), days=7)
    assert health["total"] == 2.0
    assert health["filled"] == 1.0
    assert health["rejected"] == 1.0
    assert health["reject_rate"] == 0.5


def test_live_vs_backtest_identical() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    dates = [start + timedelta(days=i) for i in range(20)]
    eq = list(np.linspace(10000, 11000, 20))
    perf = pl.DataFrame({"timestamp": dates, "equity": eq})
    bt = pl.DataFrame({"timestamp": dates, "equity": eq})
    result = live_vs_backtest(perf, bt, 365)
    assert result["observations"] == 20.0
    assert abs(result["tracking_difference"]) < 1e-9
    assert abs(result["correlation"] - 1.0) < 1e-6


def test_rolling_metrics() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    eq = [10000 + i * 10 for i in range(100)]
    perf = pl.DataFrame(
        {"timestamp": [start + timedelta(days=i) for i in range(100)], "equity": eq}
    )
    result = rolling_metrics(perf, 365)
    assert "60" in result["windows"]
    assert result["current_drawdown"] <= 0
