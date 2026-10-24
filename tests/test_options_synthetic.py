from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from tradingbot.options.backtest import replay_options
from tradingbot.options.synthetic import (
    SyntheticChainConfig,
    build_chain,
    build_snapshots,
    sma_direction_signal,
)


def _bars(n: int = 260) -> pl.DataFrame:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    rows = []
    for i in range(n):
        ts = start + timedelta(minutes=30 * i)
        for asset, base, rate in (
            ("BTCUSDT", 100_000.0, 0.00015),
            ("ETHUSDT", 3_800.0, 0.00020),
        ):
            close = base * (1.0 + rate * i)
            rows.append(
                {
                    "timestamp": ts,
                    "asset": asset,
                    "open": close * 0.999,
                    "high": close * 1.004,
                    "low": close * 0.996,
                    "close": close,
                    "volume": 1_000.0,
                }
            )
    return pl.DataFrame(rows)


def test_build_chain_has_calls_and_puts() -> None:
    now = datetime(2026, 10, 1, tzinfo=UTC)
    expiries = (now.date() + timedelta(days=7), now.date() + timedelta(days=14))
    chain = build_chain(
        "ETH",
        3_800.0,
        now=now,
        reference_price=3_800.0,
        expiries=expiries,
        config=SyntheticChainConfig(),
    )
    assert chain
    assert {candidate.option_type for candidate in chain} == {"call", "put"}
    assert all(candidate.bid <= candidate.ask for candidate in chain)
    assert all(candidate.expiry > now.date() for candidate in chain)


def test_build_snapshots_and_signal_replay() -> None:
    bars = _bars()
    snapshots = build_snapshots(bars)
    assert len(snapshots) == bars["timestamp"].n_unique()
    assert any("ETH" in snapshot.underlying_prices for snapshot in snapshots)
    signal = sma_direction_signal(bars, lookback=200)
    assert signal(snapshots[0]) == {"BTC": "flat", "ETH": "flat"}
    assert signal(snapshots[-1])["ETH"] == "long"

    result = replay_options(
        snapshots,
        signal,
        initial_cash=10_000.0,
        fee_bps=3.0,
        max_contracts=1,
    )
    assert result.cycles
    assert result.total_fills >= 1
    assert result.final_equity > 0
    assert result.max_drawdown <= 0.0
