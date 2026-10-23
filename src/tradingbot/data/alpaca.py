"""Alpaca US equity/ETF daily bar downloader (requires API keys)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import polars as pl

from tradingbot.config import DataConfig
from tradingbot.data.store import normalize_bars, save_bars


def _as_date(value: str) -> datetime:
    if len(value) == 7:
        value = value + "-01"
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def download_alpaca(
    config: DataConfig,
    root: Path,
    api_key: str | None = None,
    secret_key: str | None = None,
) -> pl.DataFrame:
    """Download adjusted daily bars for the configured US symbols."""
    api_key = api_key or os.getenv("ALPACA_API_KEY")
    secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        raise RuntimeError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required")

    from alpaca.data.enums import Adjustment
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = StockHistoricalDataClient(api_key, secret_key)
    end = _as_date(config.end) if config.end else datetime.now(UTC)
    request = StockBarsRequest(
        symbol_or_symbols=config.symbols,
        timeframe=TimeFrame.Day,
        start=_as_date(config.start),
        end=end,
        adjustment=Adjustment.ALL,
    )
    bars = cast(Any, client.get_stock_bars(request)).df
    if bars is None or bars.empty:
        raise RuntimeError("Alpaca returned no bars")

    bars = bars.reset_index()
    rename = {"symbol": "asset"}
    bars = bars.rename(columns=rename)
    keep = ["timestamp", "asset", "open", "high", "low", "close", "volume"]
    missing = [c for c in keep if c not in bars.columns]
    if missing:
        raise RuntimeError(f"unexpected Alpaca columns: missing {missing}")

    out = normalize_bars(pl.from_pandas(bars[keep]))
    path = save_bars(out, root / config.bars_path)
    print(f"[ok] {out.height:,} rows, {out['asset'].n_unique()} assets -> {path}")
    return out
