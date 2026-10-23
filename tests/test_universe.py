from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from tradingbot.data.universe import (
    apply_membership,
    apply_spans,
    audit_spans,
    load_membership,
    load_spans,
    save_membership,
    save_spans,
    spans_from_bars,
)


def _bars() -> pl.DataFrame:
    rows = []
    for timestamp, asset, close in [
        ("2024-01-01", "AAA", 10.0),
        ("2024-01-01", "BBB", 20.0),
        ("2024-01-02", "AAA", 11.0),
        ("2024-01-02", "BBB", 21.0),
        ("2024-01-03", "AAA", 12.0),
        ("2024-01-03", "BBB", 22.0),
        ("2024-01-03", "CCC", 30.0),
    ]:
        rows.append(
            {
                "timestamp": timestamp,
                "asset": asset,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1.0,
            }
        )
    return pl.DataFrame(rows).with_columns(pl.col("timestamp").str.to_date()).with_columns(
        pl.col("timestamp").cast(pl.Datetime("us")).dt.replace_time_zone("UTC")
    )


def test_spans_from_bars() -> None:
    spans = spans_from_bars(_bars(), open_ended=False)
    assert spans.height == 3
    row = spans.filter(pl.col("asset") == "CCC").row(0, named=True)
    assert row["start"] == date(2024, 1, 3)
    assert row["end"] == date(2024, 1, 3)
    assert row["observations"] == 1


def test_apply_spans_drops_bars_outside_active_span() -> None:
    spans = pl.DataFrame(
        {
            "asset": ["AAA", "BBB"],
            "start": [date(2024, 1, 1), date(2024, 1, 2)],
            "end": [date(2024, 1, 2), None],
        }
    )
    out = apply_spans(_bars(), spans)
    assert out.filter(pl.col("asset") == "AAA").height == 2
    assert out.filter(pl.col("asset") == "BBB").height == 2
    assert out.filter(pl.col("asset") == "CCC").height == 0


def test_span_roundtrip(tmp_path: Path) -> None:
    spans = spans_from_bars(_bars())
    path = save_spans(spans, tmp_path / "spans.csv")
    loaded = load_spans(path)
    assert loaded.height == 3
    assert set(loaded.columns) == {"asset", "start", "end"}


def test_membership_snapshot_roundtrip_and_application(tmp_path: Path) -> None:
    membership = pl.DataFrame(
        {
            "effective_date": [date(2024, 1, 1), date(2024, 2, 1)],
            "asset": ["AAA", "BBB"],
        }
    )
    path = save_membership(membership, tmp_path / "membership.csv")
    loaded = load_membership(path)
    assert loaded.height == 2

    bars = pl.DataFrame(
        {
            "timestamp": [
                "2024-01-01",
                "2024-01-01",
                "2024-02-01",
                "2024-02-01",
            ],
            "asset": ["AAA", "BBB", "AAA", "BBB"],
            "open": [1.0, 1.0, 1.0, 1.0],
            "high": [1.0, 1.0, 1.0, 1.0],
            "low": [1.0, 1.0, 1.0, 1.0],
            "close": [1.0, 1.0, 1.0, 1.0],
            "volume": [1.0, 1.0, 1.0, 1.0],
        }
    ).with_columns(pl.col("timestamp").str.to_date()).with_columns(
        pl.col("timestamp").cast(pl.Datetime("us")).dt.replace_time_zone("UTC")
    )
    out = apply_membership(bars, loaded)
    assert out.height == 2
    assert out.filter(pl.col("asset") == "AAA").height == 1
    assert out.filter(pl.col("asset") == "BBB").height == 1


def test_audit_spans() -> None:
    report = audit_spans(_bars())
    assert report["assets"] == 3
    assert len(report["spans"]) == 3
