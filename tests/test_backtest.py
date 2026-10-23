from __future__ import annotations

from datetime import UTC, datetime

import polars as pl

from tradingbot.backtest.engine import run_backtest
from tradingbot.config import BacktestConfig


def _bars(opens: list[float]) -> pl.DataFrame:
    dates = [datetime(2024, 1, d, tzinfo=UTC) for d in range(1, len(opens) + 1)]
    return pl.DataFrame(
        {
            "timestamp": dates,
            "asset": ["A"] * len(opens),
            "open": opens,
            "high": opens,
            "low": opens,
            "close": opens,
            "volume": [1.0] * len(opens),
        }
    )


def _weights(ts: datetime, weight: float = 1.0) -> pl.DataFrame:
    return pl.DataFrame({"timestamp": [ts], "asset": ["A"], "weight": [weight]})


def test_next_open_execution_and_no_cost() -> None:
    bars = _bars([100.0, 110.0, 121.0])
    weights = _weights(datetime(2024, 1, 1, tzinfo=UTC))
    cfg = BacktestConfig(initial_capital=1000, cost_bps=0, slippage_bps=0, execution_lag=1)
    result = run_backtest(bars, weights, cfg)
    assert abs(result.metrics["total_return"] - 0.10) < 1e-9
    assert abs(result.metrics["final_equity"] - 1100.0) < 1e-6


def test_costs_reduce_return() -> None:
    bars = _bars([100.0, 110.0, 121.0])
    weights = _weights(datetime(2024, 1, 1, tzinfo=UTC))
    cfg = BacktestConfig(initial_capital=1000, cost_bps=100, slippage_bps=0, execution_lag=1)
    result = run_backtest(bars, weights, cfg)
    assert abs(result.metrics["total_return"] - 0.09) < 1e-9


def test_weights_forward_fill() -> None:
    bars = _bars([100.0, 110.0, 121.0, 133.1])
    weights = _weights(datetime(2024, 1, 1, tzinfo=UTC), 0.5)
    cfg = BacktestConfig(initial_capital=1000, cost_bps=0, slippage_bps=0, execution_lag=1)
    result = run_backtest(bars, weights, cfg)
    # 50% invested from day 2 onward: 1.05 * 1.05 = 1.1025 (last day has no next open)
    assert abs(result.metrics["final_equity"] - 1102.5) < 1e-6


def test_empty_weights_is_cash() -> None:
    bars = _bars([100.0, 110.0])
    result = run_backtest(bars, pl.DataFrame(), BacktestConfig(initial_capital=1000))
    assert result.metrics["final_equity"] == 1000.0
