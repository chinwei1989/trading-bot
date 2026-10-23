"""Build a monthly, delisted-inclusive Binance spot universe.

The ranking uses the compressed size of the monthly 1-day archive as an
observable activity proxy. This is not quote volume, but it lets us include
delisted symbols that the current exchange API no longer returns. Selected
symbols are then downloaded from the Binance Vision archive.

The output is a research universe. It is not used by the live/paper campaign
until its walk-forward is reviewed.
"""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import polars as pl
import yaml

from tradingbot.data.binance import download_symbol
from tradingbot.data.store import save_bars
from tradingbot.data.universe import save_membership

ROOT = Path(__file__).resolve().parents[1]
S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
PREFIX = "data/spot/monthly/klines/"
EXCLUDE_BASES = {"WBTC", "WBETH", "XAUT", "LUNA"}
STABLES = {
    "USDC",
    "TUSD",
    "BUSD",
    "USDP",
    "DAI",
    "FDUSD",
    "USDD",
    "USDE",
    "USTC",
    "PAXG",
}
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR", "3L", "3S")


def _parse_keys(text: str) -> list[tuple[str, int]]:
    root = ET.fromstring(text)
    out: list[tuple[str, int]] = []
    for content in root.iter():
        if not content.tag.endswith("Contents"):
            continue
        key = None
        size = 0
        for child in content:
            if child.tag.endswith("Key"):
                key = child.text or ""
            elif child.tag.endswith("Size"):
                size = int(child.text or 0)
        if key:
            out.append((key, size))
    return out


def _get(client: httpx.Client, params: dict[str, Any]) -> str:
    response = client.get(S3, params=params)
    response.raise_for_status()
    return response.text


def list_symbols(client: httpx.Client) -> list[str]:
    prefixes: list[str] = []
    token: str | None = None
    while True:
        params: dict[str, Any] = {
            "list-type": 2,
            "prefix": PREFIX,
            "delimiter": "/",
            "max-keys": 1000,
        }
        if token:
            params["continuation-token"] = token
        text = _get(client, params)
        root = ET.fromstring(text)
        for common in root.iter():
            if not common.tag.endswith("CommonPrefixes"):
                continue
            for prefix in common:
                if prefix.tag.endswith("Prefix") and prefix.text:
                    prefixes.append(prefix.text)
        token = next(
            (e.text for e in root.iter() if e.tag.endswith("NextContinuationToken")),
            None,
        )
        if not token:
            break
    return sorted({p.rstrip("/").split("/")[-1] for p in prefixes})


def eligible(symbol: str) -> bool:
    if not symbol.isascii() or not symbol.endswith("USDT") or len(symbol) <= 4:
        return False
    base = symbol[:-4]
    return not (
        base in STABLES
        or base in EXCLUDE_BASES
        or base.endswith(LEVERAGED_SUFFIXES)
    )


def monthly_objects(client: httpx.Client, symbol: str, cache: Path) -> list[list[Any]]:
    path = cache / f"{symbol}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    prefix = f"{PREFIX}{symbol}/1d/"
    text = _get(
        client,
        {"list-type": 2, "prefix": prefix, "max-keys": 1000},
    )
    rows: list[list[Any]] = []
    for key, size in _parse_keys(text):
        if not key.endswith(".zip"):
            continue
        match = re.search(r"-(\d{4}-\d{2})\.zip$", key)
        if match:
            rows.append([match.group(1), size])
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--start", default="2020-01")
    parser.add_argument("--end", default="2026-09")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()

    cache = ROOT / "data/reference/binance_monthly_1d"
    cache.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        symbols = [s for s in list_symbols(client) if eligible(s)]
        print(f"eligible USDT symbols: {len(symbols)}")
        rows: dict[str, list[list[Any]]] = {}

        def load_one(symbol: str) -> tuple[str, list[list[Any]]]:
            return symbol, monthly_objects(client, symbol, cache)

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(load_one, s): s for s in symbols}
            for i, future in enumerate(as_completed(futures), 1):
                symbol, objects = future.result()
                rows[symbol] = objects
                if i % 50 == 0:
                    print(f"  listed {i}/{len(symbols)} symbols")

    months: list[str] = []
    y, m = map(int, args.start.split("-"))
    ey, em = map(int, args.end.split("-"))
    while (y, m) <= (ey, em):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y += 1
            m = 1

    sizes: dict[str, dict[str, int]] = {}
    for symbol, objects in rows.items():
        sizes[symbol] = {month: size for month, size in objects if month in months}

    selected: dict[str, list[str]] = {}
    for month in months:
        ranked = sorted(
            ((symbol, monthly[month]) for symbol, monthly in sizes.items() if month in monthly),
            key=lambda item: item[1],
            reverse=True,
        )
        selected[month] = [symbol for symbol, _ in ranked[: args.top_n]]

    membership_rows = [
        {"effective_date": f"{month}-01", "asset": symbol}
        for month, symbols in selected.items()
        for symbol in symbols
    ]
    membership = pl.DataFrame(membership_rows).with_columns(
        pl.col("effective_date").str.to_date()
    )
    membership_path = save_membership(membership, ROOT / "config/pit_universe_full.csv")
    unique = sorted({s for ss in selected.values() for s in ss})
    print(f"months: {len(months)}, selected rows: {membership.height}, unique assets: {len(unique)}")
    print(membership_path)

    if args.skip_download:
        return 0

    def download_one(symbol: str) -> pl.DataFrame:
        return download_symbol(
            symbol,
            "spot",
            "1d",
            "2017-08",
            args.end,
            ROOT / "data/raw",
            use_cache=True,
            verify=True,
        )

    frames = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(download_one, s): s for s in unique}
        for i, future in enumerate(as_completed(futures), 1):
            symbol = futures[future]
            print(f"[{i}/{len(unique)}] downloaded {symbol}")
            frames.append(future.result())
    bars = (
        pl.concat(frames)
        .unique(subset=["timestamp", "asset"], keep="last")
        .sort(["timestamp", "asset"])
        .filter(pl.col("timestamp").dt.date() < datetime.now(UTC).date())
    )
    bars_path = save_bars(bars, ROOT / "data/normalized/bars_pit_full.parquet")
    print(f"bars: {bars_path} ({bars.height:,} rows, {bars['asset'].n_unique()} assets)")

    meta = yaml.safe_load((ROOT / "config/meta.yaml").read_text(encoding="utf-8"))
    meta["data"]["symbols"] = unique
    meta["data"]["start"] = "2017-08"
    meta["data"]["bars_path"] = "data/normalized/bars_pit_full.parquet"
    meta["data"]["universe_path"] = "config/pit_universe_full.csv"
    meta["backtest"]["output_dir"] = "artifacts/pit_full"
    meta["broker"]["state_path"] = "artifacts/pit_full/paper_state.json"
    meta["broker"]["journal_path"] = "artifacts/pit_full/orders.sqlite"
    meta["broker"]["order_state_path"] = "artifacts/pit_full/order_state.sqlite"
    meta["broker"]["performance_path"] = "artifacts/pit_full/performance.jsonl"
    meta["broker"]["heartbeat_path"] = "artifacts/pit_full/heartbeat.json"
    meta["risk"]["state_path"] = "artifacts/pit_full/risk_state.json"
    meta["risk"]["kill_switch_file"] = "artifacts/pit_full/KILL"
    config_path = ROOT / "config/pit_full.yaml"
    config_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    print(f"config: {config_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
