"""Binance USD-M perpetual funding-rate data.

Funding is paid every 8 hours on Binance USD-M perpetuals. This module only
downloads and summarizes public funding history; it does not place orders.

A funding carry sleeve needs two legs (spot long / perp short) and belongs in a
dedicated research/backtest path. Keeping the raw funding panel separate avoids
pretending a one-leg spot strategy is delta-neutral.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import polars as pl

BASE_URL = "https://fapi.binance.com"
FUNDING_COLUMNS = ["timestamp", "asset", "funding_rate"]
MAX_LIMIT = 1000


def parse_funding_rows(rows: list[dict[str, Any]], symbol: str) -> pl.DataFrame:
    """Normalize rows from Binance's /fapi/v1/fundingRate endpoint."""
    if not rows:
        return pl.DataFrame(
            schema={
                "timestamp": pl.Datetime("us", time_zone="UTC"),
                "asset": pl.Utf8,
                "funding_rate": pl.Float64,
            }
        )
    df = pl.DataFrame(rows)
    if "fundingTime" not in df.columns or "fundingRate" not in df.columns:
        raise ValueError("funding rows need fundingTime and fundingRate")
    return (
        df.select(
            pl.from_epoch(pl.col("fundingTime").cast(pl.Int64), time_unit="ms")
            .dt.replace_time_zone("UTC")
            .alias("timestamp"),
            pl.lit(symbol).alias("asset"),
            pl.col("fundingRate").cast(pl.Float64).alias("funding_rate"),
        )
        .unique(subset=["timestamp", "asset"], keep="last")
        .sort("timestamp")
    )


def fetch_funding_rates(
    symbol: str,
    start: datetime,
    end: datetime | None = None,
    *,
    client: httpx.Client | None = None,
    max_pages: int = 100,
) -> pl.DataFrame:
    """Fetch all 8-hour funding events in the requested window."""
    start = start.astimezone(UTC)
    end = (end or datetime.now(UTC)).astimezone(UTC)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    own_client = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=True)
    frames: list[pl.DataFrame] = []
    try:
        for _ in range(max_pages):
            response = client.get(
                f"{BASE_URL}/fapi/v1/fundingRate",
                params={
                    "symbol": symbol,
                    "startTime": start_ms,
                    "endTime": end_ms,
                    "limit": MAX_LIMIT,
                },
            )
            response.raise_for_status()
            rows = response.json()
            if not rows:
                break
            frame = parse_funding_rows(rows, symbol)
            frames.append(frame)
            if len(rows) < MAX_LIMIT:
                break
            last_ms = int(rows[-1]["fundingTime"])
            if last_ms <= start_ms:
                break
            start_ms = last_ms + 1
    finally:
        if own_client:
            client.close()
    if not frames:
        return parse_funding_rows([], symbol)
    return pl.concat(frames).unique(subset=["timestamp", "asset"], keep="last").sort("timestamp")


def download_funding(
    symbols: list[str],
    start: str,
    end: str | None,
    path: str | Path,
) -> pl.DataFrame:
    start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=UTC)
    end_dt = (
        datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=UTC)
        if end
        else datetime.now(UTC)
    )
    frames: list[pl.DataFrame] = []
    for symbol in symbols:
        frame = fetch_funding_rates(symbol, start_dt, end_dt)
        if not frame.is_empty():
            frames.append(frame)
            print(f"[funding] {symbol}: {frame.height} events")
        else:
            print(f"[funding] {symbol}: no events")
    if not frames:
        raise ValueError("no funding data returned")
    out = pl.concat(frames).sort(["timestamp", "asset"])
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(output)
    print(f"[ok] {out.height:,} funding rows -> {output}")
    return out


def load_funding(path: str | Path) -> pl.DataFrame:
    df = pl.read_parquet(path)
    missing = [c for c in FUNDING_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"funding file missing columns: {missing}")
    return df.select(FUNDING_COLUMNS).sort(["timestamp", "asset"])


def annualized_funding(rate: float, events_per_year: int = 3 * 365) -> float:
    return rate * events_per_year


def funding_summary(path: str | Path) -> pl.DataFrame:
    df = load_funding(path)
    return (
        df.group_by("asset")
        .agg(
            pl.col("timestamp").min().alias("start"),
            pl.col("timestamp").max().alias("end"),
            pl.len().alias("events"),
            pl.col("funding_rate").mean().alias("mean_rate"),
            (pl.col("funding_rate").mean() * 3 * 365).alias("mean_annualized"),
            pl.col("funding_rate").last().alias("latest_rate"),
            (pl.col("funding_rate").last() * 3 * 365).alias("latest_annualized"),
        )
        .sort("asset")
    )
