"""FRED macro data downloader (free API key)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import polars as pl

DEFAULT_SERIES = [
    "DFF",
    "DGS2",
    "DGS10",
    "T10Y2Y",
    "VIXCLS",
    "BAMLH0A0HYM2",
    "DTWEXBGS",
    "CPIAUCSL",
    "UNRATE",
    "PAYEMS",
    "WALCL",
]


def download_macro(
    series: list[str] | None = None,
    start: str = "2000-01-01",
    path: str | Path = "data/normalized/macro.parquet",
    api_key: str | None = None,
) -> pl.DataFrame:
    key = api_key or os.getenv("FRED_API_KEY")
    if not key:
        raise RuntimeError("FRED_API_KEY is required")
    series = series or DEFAULT_SERIES
    rows: list[dict[str, object]] = []
    with httpx.Client(timeout=30) as client:
        for sid in series:
            response = client.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={
                    "series_id": sid,
                    "api_key": key,
                    "file_type": "json",
                    "observation_start": start,
                    "realtime_start": datetime.now(UTC).date().isoformat(),
                },
            )
            response.raise_for_status()
            for obs in response.json().get("observations", []):
                value = obs.get("value")
                if value in (None, "."):
                    continue
                rows.append(
                    {
                        "timestamp": obs["date"],
                        "series": sid,
                        "value": float(value),
                    }
                )
    if not rows:
        raise RuntimeError("FRED returned no observations")
    df = (
        pl.DataFrame(rows)
        .with_columns(pl.col("timestamp").str.to_datetime("%Y-%m-%d").dt.replace_time_zone("UTC"))
        .sort(["timestamp", "series"])
    )
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out)
    print(f"[ok] {df.height:,} macro rows, {df['series'].n_unique()} series -> {out}")
    return df
