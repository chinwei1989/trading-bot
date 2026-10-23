"""Download Binance public klines (monthly ZIPs) and normalize to Parquet.

Examples
--------
    uv run python scripts/download_binance_klines.py --symbol BTCUSDT --start 2020-01 --end 2026-09
    uv run python scripts/download_binance_klines.py --symbol ETHUSDT --market futures --start 2021-01

Data source: https://data.binance.vision/
No API key required. Respect Binance's terms of use.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
import polars as pl

BASE = "https://data.binance.vision/data"
COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trade_count",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
]


def month_range(start: str, end: str) -> list[str]:
    start_dt = datetime.strptime(start, "%Y-%m").replace(tzinfo=UTC)
    end_dt = datetime.strptime(end, "%Y-%m").replace(tzinfo=UTC)
    if end_dt < start_dt:
        raise ValueError("end must be >= start")
    months: list[str] = []
    y, m = start_dt.year, start_dt.month
    while (y, m) <= (end_dt.year, end_dt.month):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y += 1
            m = 1
    return months


def url_for(market: str, symbol: str, interval: str, month: str) -> str:
    if market == "spot":
        return f"{BASE}/spot/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{month}.zip"
    if market == "futures":
        return f"{BASE}/futures/um/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{month}.zip"
    raise ValueError(f"unknown market: {market}")


def verify_checksum(content: bytes, checksum_text: str) -> None:
    expected = checksum_text.strip().split()[0].lower()
    actual = hashlib.sha256(content).hexdigest().lower()
    if expected != actual:
        raise ValueError(f"checksum mismatch: expected {expected}, got {actual}")


def parse_zip(content: bytes, filename: str) -> pl.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = [n for n in zf.namelist() if n.endswith(".csv")]
        if not names:
            raise ValueError(f"no CSV in {filename}")
        raw = zf.read(names[0])

    first_line = raw.split(b"\n", 1)[0].decode("utf-8", errors="ignore")
    has_header = first_line.lower().startswith("open_time")
    df = pl.read_csv(
        io.BytesIO(raw),
        has_header=has_header,
        infer_schema_length=10_000,
        null_values=["", "NULL"],
    )

    if not has_header:
        if df.width < len(COLUMNS):
            raise ValueError(f"unexpected column count: {df.width}")
        df = df.select(df.columns[: len(COLUMNS)]).rename(
            {old: new for old, new in zip(df.columns[: len(COLUMNS)], COLUMNS, strict=True)}
        )
    else:
        df = df.rename({c: c.strip().lower() for c in df.columns})
        missing = [c for c in COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"missing columns: {missing}")

    # Binance spot switched to microseconds on 2025-01-01. Normalize to UTC datetime.
    ts = df["open_time"].cast(pl.Int64)
    seconds = (
        pl.when(ts > 10**15)
        .then(ts // 1_000_000)
        .when(ts > 10**12)
        .then(ts // 1_000)
        .otherwise(ts)
    )
    df = df.with_columns(
        pl.from_epoch(seconds, time_unit="s").dt.replace_time_zone("UTC").alias("timestamp")
    )

    numeric = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "trade_count",
        "taker_buy_base",
        "taker_buy_quote",
    ]
    df = df.with_columns([pl.col(c).cast(pl.Float64, strict=False) for c in numeric])
    return df.select(["timestamp", *numeric]).sort("timestamp")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--market", choices=["spot", "futures"], default="spot")
    parser.add_argument("--start", required=True, help="YYYY-MM")
    parser.add_argument("--end", required=True, help="YYYY-MM")
    parser.add_argument("--out", default=None)
    parser.add_argument("--no-checksum", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    raw_dir = root / "data" / "raw" / "binance" / args.market / args.symbol / args.interval
    raw_dir.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else (
        root / "data" / "normalized" / f"{args.market}_{args.symbol}_{args.interval}.parquet"
    )
    out.parent.mkdir(parents=True, exist_ok=True)

    frames: list[pl.DataFrame] = []
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for month in month_range(args.start, args.end):
            url = url_for(args.market, args.symbol, args.interval, month)
            path = raw_dir / f"{args.symbol}-{args.interval}-{month}.zip"
            if path.exists() and path.stat().st_size > 0:
                content = path.read_bytes()
                print(f"  [cache] {month}")
            else:
                resp = client.get(url)
                if resp.status_code == 404:
                    print(f"  [skip] {month} (not published)")
                    continue
                resp.raise_for_status()
                content = resp.content

                if not args.no_checksum:
                    cr = client.get(url + ".CHECKSUM")
                    if cr.status_code == 200:
                        verify_checksum(content, cr.text)
                    else:
                        print(f"  [warn] no checksum for {month}")

                path.write_bytes(content)

            df = parse_zip(content, path.name)
            frames.append(df)
            print(f"  [ok] {month}: {df.height} rows")

    if not frames:
        print("No data downloaded.")
        return 1

    data = pl.concat(frames).unique(subset=["timestamp"], keep="last").sort("timestamp")
    data.write_parquet(out)
    print(f"\nWrote {data.height:,} rows -> {out}")
    print("First rows:", data.head(3).to_dicts())
    print("Last rows: ", data.tail(3).to_dicts())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
