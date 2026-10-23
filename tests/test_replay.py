from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from tradingbot.backtest.replay import paper_replay
from tradingbot.config import (
    AppConfig,
    BacktestConfig,
    BrokerConfig,
    DataConfig,
    RiskConfig,
    StrategyConfig,
    TrendParams,
)


def _bars() -> pl.DataFrame:
    rows = []
    start = datetime(2023, 1, 1, tzinfo=UTC)
    for asset, rate in {"A": 0.004, "B": 0.002}.items():
        for i in range(180):
            close = 100.0 * ((1 + rate) ** i)
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


def _config() -> AppConfig:
    return AppConfig(
        data=DataConfig(symbols=["A", "B"], include_recent=False),
        strategy=StrategyConfig(
            name="trend",
            trend=TrendParams(
                lookback=20,
                vol_window=10,
                target_vol=0.15,
                max_weight=0.5,
                vol_target=False,
                rebalance="W",
            ),
        ),
        backtest=BacktestConfig(
            initial_capital=10_000,
            cost_bps=0,
            slippage_bps=0,
            periods_per_year=365,
        ),
        risk=RiskConfig(max_drawdown=0.9),
        broker=BrokerConfig(name="paper", min_notional=1, state_path=Path("artifacts/state.json")),
    )


def test_paper_replay_runs() -> None:
    result = paper_replay(_config(), _bars())
    assert result.daily.height > 100
    assert result.fills > 0
    assert result.metrics["final_equity"] > 0
    assert result.backtest.metrics["final_equity"] > 0
