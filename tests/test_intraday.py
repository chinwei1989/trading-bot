from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from tradingbot.config import DataConfig
from tradingbot.data.intraday import completed_bars, refresh_recent_bars
from tradingbot.features.indicators import rebalance_dates


def _hourly_bars(now: datetime) -> pl.DataFrame:
    complete = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    forming = complete + timedelta(hours=1)
    rows = []
    for ts, close in ((complete, 100.0), (forming, 101.0)):
        rows.append(
            {
                "timestamp": ts,
                "asset": "BTCUSDT",
                "open": close - 1,
                "high": close + 1,
                "low": close - 2,
                "close": close,
                "volume": 10.0,
            }
        )
    return pl.DataFrame(rows)


def test_completed_bars_drops_the_current_hour() -> None:
    now = datetime(2026, 10, 24, 10, 15, tzinfo=UTC)
    bars = _hourly_bars(now)
    result = completed_bars(bars, "1h", now=now)
    assert result.height == 1
    assert result["timestamp"][0] == datetime(2026, 10, 24, 9, 0, tzinfo=UTC)


def test_rebalance_h_returns_every_bar() -> None:
    dates = pl.Series(
        "timestamp",
        [
            datetime(2026, 10, 24, 8, 0, tzinfo=UTC),
            datetime(2026, 10, 24, 9, 0, tzinfo=UTC),
            datetime(2026, 10, 24, 10, 0, tzinfo=UTC),
        ],
    )
    assert len(rebalance_dates(dates, "H")) == 3


def test_refresh_merges_and_drops_forming_bar(tmp_path: Path, monkeypatch) -> None:
    now = datetime.now(UTC)
    config = DataConfig(
        symbols=["BTCUSDT"],
        interval="1h",
        bars_path=Path("data/bars_1h.parquet"),
        recent_limit=10,
    )
    fresh = _hourly_bars(now)

    def fake_fetch_recent(*args, **kwargs) -> pl.DataFrame:
        return fresh

    monkeypatch.setattr(
        "tradingbot.data.intraday.fetch_recent",
        fake_fetch_recent,
    )
    bars = refresh_recent_bars(config, tmp_path, limit=10)
    assert bars.height == 1
    saved = pl.read_parquet(tmp_path / config.bars_path)
    assert saved.height == 1
    assert saved["timestamp"].max() < now.replace(minute=0, second=0, microsecond=0)
