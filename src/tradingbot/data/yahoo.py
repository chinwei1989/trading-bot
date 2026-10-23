"""Yahoo Finance daily bars for long-history research.

Yahoo data is not exchange-grade. Use it for long-history research and
sanity checks, not for live execution or microstructure work.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from tradingbot.config import DataConfig
from tradingbot.data.store import normalize_bars, save_bars


def _to_date(value: str, *, end: bool = False) -> str:
    if len(value) == 7:
        value = value + "-01"
    if end:
        # yfinance treats end as exclusive; add a day to include it.
        return (datetime.fromisoformat(value) + timedelta(days=1)).date().isoformat()
    return value


def _one_symbol(raw, symbol: str) -> pl.DataFrame:
    df = raw.copy()
    if df.empty:
        raise ValueError(f"Yahoo returned no data for {symbol}")
    df = df.reset_index()
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "date" not in df.columns and "datetime" not in df.columns:
        raise ValueError(f"no date column for {symbol}: {df.columns}")
    date_col = "date" if "date" in df.columns else "datetime"
    keep = [date_col, "open", "high", "low", "close", "volume"]
    missing = [c for c in keep if c not in df.columns]
    if missing:
        raise ValueError(f"missing Yahoo columns for {symbol}: {missing}")
    out = pl.from_pandas(df[keep]).rename({date_col: "timestamp"})
    out = out.with_columns(
        pl.col("timestamp").cast(pl.Datetime("us")).dt.replace_time_zone("UTC"),
        pl.lit(symbol.replace("-", "")).alias("asset"),
    )
    out = out.drop_nulls(["open", "high", "low", "close"])
    return normalize_bars(out)


def download_yahoo(config: DataConfig, root: Path) -> pl.DataFrame:
    import yfinance as yf  # type: ignore[import-untyped]

    end = _to_date(config.end, end=True) if config.end else None
    start = _to_date(config.start)
    frames: list[pl.DataFrame] = []
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            raw = yf.download(
                config.symbols,
                start=start,
                end=end,
                interval=config.interval,
                auto_adjust=False,
                progress=False,
                group_by="ticker",
                threads=False,
            )
            if raw is None or raw.empty:
                raise RuntimeError("Yahoo returned an empty frame")
            for symbol in config.symbols:
                sub = raw[symbol] if len(config.symbols) > 1 else raw
                df = _one_symbol(sub, symbol)
                frames.append(df)
                print(f"  [ok] {symbol}: {df.height:,} rows")
            break
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2)
    if not frames:
        raise RuntimeError(f"Yahoo download failed: {last_error}")

    bars = (
        pl.concat(frames)
        .unique(subset=["timestamp", "asset"], keep="last")
        .sort(["timestamp", "asset"])
    )
    if config.interval == "1d":
        # Drop the still-forming current daily bar.
        bars = bars.filter(pl.col("timestamp").dt.date() < datetime.now(UTC).date())
    out = save_bars(bars, root / config.bars_path)
    print(f"[ok] {bars.height:,} rows, {bars['asset'].n_unique()} assets -> {out}")
    return bars
