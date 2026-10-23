from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from tradingbot.data.funding import (
    annualized_funding,
    load_funding,
    parse_funding_rows,
)


def test_parse_funding_rows() -> None:
    rows = [
        {"fundingTime": 1710000000000, "fundingRate": "0.0001"},
        {"fundingTime": 1710028800000, "fundingRate": "-0.0002"},
    ]
    frame = parse_funding_rows(rows, "BTCUSDT")
    assert frame.height == 2
    assert frame["asset"].to_list() == ["BTCUSDT", "BTCUSDT"]
    assert frame["funding_rate"].to_list() == [0.0001, -0.0002]
    assert frame["timestamp"].dtype == pl.Datetime("us", time_zone="UTC")


def test_parse_empty_funding_rows() -> None:
    frame = parse_funding_rows([], "BTCUSDT")
    assert frame.is_empty()
    assert frame.columns == ["timestamp", "asset", "funding_rate"]


def test_annualized_funding() -> None:
    assert annualized_funding(0.0001) == pytest.approx(0.0001 * 3 * 365)


def test_load_funding_roundtrip(tmp_path) -> None:
    frame = parse_funding_rows(
        [{"fundingTime": 1710000000000, "fundingRate": 0.0001}], "BTCUSDT"
    )
    path = tmp_path / "funding.parquet"
    frame.write_parquet(path)
    loaded = load_funding(path)
    assert loaded.height == 1
    assert loaded["timestamp"][0] == datetime(2024, 3, 9, 16, 0, tzinfo=UTC)
    assert loaded.columns == ["timestamp", "asset", "funding_rate"]
