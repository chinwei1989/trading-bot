from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from tradingbot.options.backtest import OptionSnapshot
from tradingbot.options.historical import load_option_snapshots
from tradingbot.options.synthetic import SyntheticChainConfig, build_chain


def _snapshots() -> list[OptionSnapshot]:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    expiries = (start.date() + timedelta(days=7), start.date() + timedelta(days=14))
    chain = build_chain(
        "ETH",
        3_800.0,
        now=start,
        reference_price=3_800.0,
        expiries=expiries,
        config=SyntheticChainConfig(expiry_days=(7, 14)),
    )
    return [
        OptionSnapshot(start, chain, {"ETH": 3_800.0}),
        OptionSnapshot(start + timedelta(minutes=30), chain, {"ETH": 3_810.0}),
    ]


def _rows(snapshots: list[OptionSnapshot]) -> list[dict]:
    rows = []
    for snapshot in snapshots:
        for candidate in snapshot.chain:
            rows.append(
                {
                    "timestamp": snapshot.timestamp,
                    "underlying": candidate.underlying,
                    "instrument": candidate.instrument,
                    "option_type": candidate.option_type,
                    "strike": candidate.strike,
                    "expiry": candidate.expiry,
                    "bid": candidate.bid,
                    "ask": candidate.ask,
                    "mark": candidate.mark,
                    "delta": candidate.delta,
                    "gamma": candidate.gamma,
                    "vega": candidate.vega,
                    "theta": candidate.theta,
                    "open_interest": candidate.open_interest,
                    "volume": candidate.volume,
                    "multiplier": candidate.multiplier,
                    "underlying_price": snapshot.underlying_prices[candidate.underlying],
                }
            )
    return rows


def test_load_snapshots_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "snapshots.csv"
    pl.DataFrame(_rows(_snapshots())).write_csv(path)
    loaded = load_option_snapshots(path)
    assert len(loaded) == 2
    assert loaded[0].underlying_prices == {"ETH": 3_800.0}
    assert loaded[1].chain


def test_load_parquet(tmp_path: Path) -> None:
    path = tmp_path / "snapshots.parquet"
    pl.DataFrame(_rows(_snapshots())).write_parquet(path)
    assert len(load_option_snapshots(path)) == 2


def test_missing_columns_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    pl.DataFrame([{"timestamp": "2026-10-01T00:00:00+00:00"}]).write_csv(path)
    with pytest.raises(ValueError, match="missing columns"):
        load_option_snapshots(path)


def test_duplicate_instrument_rejected(tmp_path: Path) -> None:
    rows = _rows(_snapshots())
    rows.append(dict(rows[0]))
    path = tmp_path / "dupe.csv"
    pl.DataFrame(rows).write_csv(path)
    with pytest.raises(ValueError, match="duplicate instrument"):
        load_option_snapshots(path)


def test_inconsistent_underlying_price_rejected(tmp_path: Path) -> None:
    rows = _rows(_snapshots())
    first = rows[0]
    second = dict(first)
    second["instrument"] = second["instrument"] + "-DUP"
    second["underlying_price"] = float(second["underlying_price"]) + 1.0
    rows.append(second)
    path = tmp_path / "price.csv"
    pl.DataFrame(rows).write_csv(path)
    with pytest.raises(ValueError, match="inconsistent underlying price"):
        load_option_snapshots(path)
