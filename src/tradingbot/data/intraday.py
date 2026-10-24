"""Intraday bar refresh helpers for the deterministic interval lane.

The daily campaign downloads historical bars once per day. The intraday lane
needs to append the latest *closed* bars before each hourly cycle. These helpers
keep that concern outside the strategy code.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from tradingbot.config import DataConfig
from tradingbot.data.binance import fetch_recent
from tradingbot.data.store import load_bars, normalize_bars, save_bars

_INTERVAL_MINUTES = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "6h": 360,
    "8h": 480,
    "12h": 720,
    "1d": 1440,
}


def interval_timedelta(interval: str) -> timedelta:
    try:
        return timedelta(minutes=_INTERVAL_MINUTES[interval])
    except KeyError as exc:
        raise ValueError(f"unsupported intraday interval: {interval}") from exc


def completed_bars(
    bars: pl.DataFrame,
    interval: str,
    *,
    now: datetime | None = None,
) -> pl.DataFrame:
    """Drop the still-forming bar for the configured interval."""
    if bars.is_empty():
        return bars
    frame = normalize_bars(bars)
    cutoff = (now or datetime.now(UTC)) - interval_timedelta(interval)
    return frame.filter(pl.col("timestamp") <= cutoff).sort(["timestamp", "asset"])


def refresh_recent_bars(
    config: DataConfig,
    root: Path,
    *,
    limit: int | None = None,
) -> pl.DataFrame:
    """Fetch recent bars and merge them into the configured parquet store.

    The function is intentionally best-effort per symbol: one unavailable symbol
    must not stop the rest of the universe. It fails closed only when there is
    no existing data and no fresh data.
    """
    path = root / config.bars_path
    existing = load_bars(path) if path.exists() else pl.DataFrame()
    frames: list[pl.DataFrame] = [existing] if not existing.is_empty() else []
    errors: list[str] = []
    fresh_frames = 0
    request_limit = limit or config.recent_limit

    for symbol in config.symbols:
        try:
            frame = fetch_recent(
                symbol,
                interval=config.interval,
                limit=request_limit,
                market=config.market,
            )
            frames.append(frame)
            fresh_frames += 1
        except Exception as exc:  # network, endpoint, or malformed response
            errors.append(f"{symbol}: {type(exc).__name__}: {exc}")

    if fresh_frames == 0:
        detail = "; ".join(errors) or "no symbols configured"
        raise RuntimeError(f"could not refresh intraday bars: {detail}")

    merged = (
        pl.concat(frames)
        .unique(subset=["timestamp", "asset"], keep="last")
        .sort(["timestamp", "asset"])
    )
    merged = completed_bars(merged, config.interval)
    if merged.is_empty():
        raise RuntimeError("refresh produced no completed bars")
    save_bars(merged, path)
    if errors:
        print(f"[warn] intraday refresh issues: {'; '.join(errors)}")
    return merged
