"""Binance public data downloader (no API key)."""

from __future__ import annotations

import hashlib
import io
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import polars as pl

from tradingbot.config import DataConfig
from tradingbot.data.store import normalize_bars, save_bars

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
NUMERIC = [
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
        return (
            f"{BASE}/futures/um/monthly/klines/{symbol}/{interval}/"
            f"{symbol}-{interval}-{month}.zip"
        )
    raise ValueError(f"unknown market: {market}")


def verify_checksum(content: bytes, checksum_text: str) -> None:
    expected = checksum_text.strip().split()[0].lower()
    actual = hashlib.sha256(content).hexdigest().lower()
    if expected != actual:
        raise ValueError(f"checksum mismatch: expected {expected}, got {actual}")


def parse_zip(content: bytes, filename: str) -> pl.DataFrame:
    """Parse a Binance monthly kline ZIP into a normalized frame."""
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
        aliases = {
            "count": "trade_count",
            "taker_buy_volume": "taker_buy_base",
            "taker_buy_quote_volume": "taker_buy_quote",
        }
        df = df.rename(
            {c: aliases.get(c.strip().lower(), c.strip().lower()) for c in df.columns}
        )
        missing = [c for c in COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"missing columns: {missing}")

    return _normalize_kline_frame(df)


def _normalize_kline_frame(df: pl.DataFrame) -> pl.DataFrame:
    # Binance spot switched to microseconds on 2025-01-01.
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
    df = df.with_columns([pl.col(c).cast(pl.Float64, strict=False) for c in NUMERIC])
    return df.select(["timestamp", *NUMERIC]).sort("timestamp")


def parse_kline_rows(rows: list[list[object]]) -> pl.DataFrame:
    """Parse the JSON rows returned by the public kline endpoint."""
    if not rows:
        raise ValueError("empty kline response")
    df = pl.DataFrame(rows, schema=COLUMNS, orient="row")
    return _normalize_kline_frame(df)


def _interval_milliseconds(interval: str) -> int:
    multipliers = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}
    try:
        unit = interval[-1]
        value = int(interval[:-1])
        return value * multipliers[unit]
    except (KeyError, ValueError, IndexError) as exc:
        raise ValueError(f"unsupported interval: {interval}") from exc


def _as_utc(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def fetch_window(
    symbol: str,
    interval: str = "30m",
    *,
    start: datetime | str,
    end: datetime | str,
    market: str = "spot",
    client: httpx.Client | None = None,
) -> pl.DataFrame:
    """Fetch a bounded public kline window, paginating at Binance's 1000 limit.

    ``start`` and ``end`` are inclusive UTC timestamps. The function does not
    require an API key and never places an order.
    """
    if market == "spot":
        url = "https://data-api.binance.vision/api/v3/klines"
    elif market == "futures":
        url = "https://fapi.binance.com/fapi/v1/klines"
    else:
        raise ValueError(f"unknown market: {market}")

    start_dt = _as_utc(start)
    end_dt = _as_utc(end)
    if end_dt < start_dt:
        raise ValueError("end must be >= start")
    step_ms = _interval_milliseconds(interval)
    cursor = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    rows: list[list[Any]] = []
    owns_client = client is None
    http = client or httpx.Client(timeout=30, follow_redirects=True)
    try:
        while cursor <= end_ms:
            response = _get_with_retry(
                http,
                url,
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": end_ms,
                    "limit": 1000,
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or not payload:
                break
            rows.extend(payload)
            last_open = int(payload[-1][0])
            next_cursor = last_open + step_ms
            if next_cursor <= cursor:
                raise RuntimeError("Binance kline pagination made no progress")
            cursor = next_cursor
    finally:
        if owns_client:
            http.close()

    if not rows:
        raise ValueError(f"no Binance data for {symbol} {start}..{end}")
    frame = parse_kline_rows(rows)
    frame = frame.filter(
        (pl.col("timestamp") >= start_dt) & (pl.col("timestamp") <= end_dt)
    )
    if frame.is_empty():
        raise ValueError(f"no Binance bars for {symbol} {start}..{end}")
    return normalize_bars(frame.with_columns(pl.lit(symbol).alias("asset")))


def fetch_recent(
    symbol: str,
    interval: str = "1d",
    limit: int = 30,
    market: str = "spot",
) -> pl.DataFrame:
    """Fetch recent daily bars from Binance's public data API (no key)."""
    if market == "spot":
        url = "https://data-api.binance.vision/api/v3/klines"
    elif market == "futures":
        url = "https://fapi.binance.com/fapi/v1/klines"
    else:
        raise ValueError(f"unknown market: {market}")
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        response = _get_with_retry(
            client,
            url,
            params={"symbol": symbol, "interval": interval, "limit": limit},
        )
        response.raise_for_status()
    df = parse_kline_rows(response.json())
    return normalize_bars(df.with_columns(pl.lit(symbol).alias("asset")))


def _get_with_retry(
    client: httpx.Client,
    url: str,
    attempts: int = 3,
    params: dict[str, str | int | float | bool | None] | None = None,
) -> httpx.Response:
    last: Exception | None = None
    for i in range(attempts):
        try:
            response = client.get(url, params=params)
            if response.status_code == 404:
                return response
            response.raise_for_status()
            return response
        except Exception as exc:
            last = exc
            if i < attempts - 1:
                time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"failed to fetch {url}: {last}")


def download_symbol(
    symbol: str,
    market: str,
    interval: str,
    start: str,
    end: str,
    raw_dir: Path,
    *,
    use_cache: bool = True,
    verify: bool = True,
) -> pl.DataFrame:
    """Download one symbol and return a normalized long frame."""
    raw_dir = raw_dir / market / symbol / interval
    raw_dir.mkdir(parents=True, exist_ok=True)
    frames: list[pl.DataFrame] = []

    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for month in month_range(start, end):
            url = url_for(market, symbol, interval, month)
            path = raw_dir / f"{symbol}-{interval}-{month}.zip"

            if use_cache and path.exists() and path.stat().st_size > 0:
                content = path.read_bytes()
            else:
                response = _get_with_retry(client, url)
                if response.status_code == 404:
                    print(f"  [skip] {symbol} {month}")
                    continue
                content = response.content
                if verify:
                    checksum = _get_with_retry(client, url + ".CHECKSUM")
                    if checksum.status_code == 200:
                        verify_checksum(content, checksum.text)
                path.write_bytes(content)

            frames.append(parse_zip(content, path.name))

    if not frames:
        raise ValueError(f"no data for {symbol} {start}..{end}")
    out = pl.concat(frames).unique(subset=["timestamp"], keep="last").sort("timestamp")
    return normalize_bars(out.with_columns(pl.lit(symbol).alias("asset")))


def download_many(config: DataConfig, root: Path) -> pl.DataFrame:
    """Download every configured symbol and write the combined Parquet store."""
    end = config.end or datetime.now(UTC).strftime("%Y-%m")
    frames: list[pl.DataFrame] = []
    for symbol in config.symbols:
        print(f"[download] {symbol} {config.start}..{end}")
        frames.append(
            download_symbol(
                symbol=symbol,
                market=config.market,
                interval=config.interval,
                start=config.start,
                end=end,
                raw_dir=root / config.raw_dir,
                use_cache=config.use_cache,
                verify=config.verify_checksums,
            )
        )

    if config.include_recent and config.end is None:
        for symbol in config.symbols:
            try:
                recent = fetch_recent(
                    symbol,
                    interval=config.interval,
                    limit=config.recent_limit,
                    market=config.market,
                )
                frames.append(recent)
                print(f"  [recent] {symbol}: {recent.height} bars")
            except Exception as exc:
                print(f"  [warn] recent data failed for {symbol}: {exc}")

    bars = (
        pl.concat(frames)
        .unique(subset=["timestamp", "asset"], keep="last")
        .sort(["timestamp", "asset"])
    )
    if config.interval == "1d":
        # Drop the still-forming current daily bar from the public API.
        bars = bars.filter(pl.col("timestamp").dt.date() < datetime.now(UTC).date())
    out = save_bars(bars, root / config.bars_path)
    print(f"[ok] {bars.height:,} rows, {bars['asset'].n_unique()} assets -> {out}")
    return bars
