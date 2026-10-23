from __future__ import annotations

from datetime import UTC, datetime

import polars as pl

from tradingbot.data.store import long, normalize_bars, validate_bars, wide


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "timestamp": [datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC)] * 2,
            "asset": ["A", "A", "B", "B"],
            "open": [100.0, 101.0, 50.0, 49.0],
            "high": [102.0, 103.0, 51.0, 50.0],
            "low": [99.0, 100.0, 48.0, 48.0],
            "close": [101.0, 102.0, 49.0, 49.5],
            "volume": [10.0, 11.0, 20.0, 21.0],
        }
    )


def test_normalize_and_wide_long() -> None:
    df = normalize_bars(_frame())
    w = wide(df, "close")
    assert w.columns == ["timestamp", "A", "B"]
    assert w.height == 2
    back = long(w, "close")
    assert back.height == 4
    assert set(back["asset"].to_list()) == {"A", "B"}


def test_validate_flags_bad_ohlc() -> None:
    df = _frame().with_columns(
        pl.when(pl.col("asset") == "A").then(pl.lit(90.0)).otherwise(pl.col("high")).alias("high")
    )
    report = validate_bars(df)
    assert report["ohlc_violations"] >= 1


def test_normalize_drops_duplicates() -> None:
    df = pl.concat([_frame(), _frame().head(1)])
    out = normalize_bars(df)
    assert out.height == 4
