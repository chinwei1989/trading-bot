"""PIT universe v2: quote-volume ranking, quarterly hysteresis.

This is the next step after the archive-size proxy. It still uses the Binance
Vision monthly archive (the only source here that includes delisted pairs), but
it downloads candidate monthly 1-day ZIPs and ranks by actual quote volume.

Selection is lagged by one month: the membership for month M is based on month
M-1 quote volume. Membership is recalculated quarterly and uses entry/exit
hysteresis to reduce turnover.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import polars as pl
import yaml

from tradingbot.data.binance import download_symbol, parse_zip
from tradingbot.data.store import load_bars, save_bars
from tradingbot.data.universe import save_membership

ROOT = Path(__file__).resolve().parents[1]
S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
PREFIX = "data/spot/monthly/klines/"
CACHE = ROOT / "data/reference/binance_monthly_1d"
VOLUME_CACHE = ROOT / "data/reference/pit_v2_volume.json"
STABLES = {"USDC", "TUSD", "BUSD", "USDP", "DAI", "FDUSD", "USDD", "USDE", "USTC", "PAXG"}
EXCLUDE = {"WBTC", "WBETH", "XAUT", "LUNA", "COCOS"}
LEVERAGED = ("UP", "DOWN", "BULL", "BEAR", "3L", "3S")


def _eligible(symbol: str) -> bool:
    if not symbol.isascii() or not symbol.endswith("USDT") or len(symbol) <= 4:
        return False
    base = symbol[:-4]
    return not (
        base in STABLES
        or base in EXCLUDE
        or base.endswith(LEVERAGED)
    )


def _months(start: str, end: str) -> list[str]:
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y += 1
            m = 1
    return out


def _load_objects(symbol: str) -> dict[str, int]:
    path = CACHE / f"{symbol}.json"
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {month: size for month, size in rows}


def _month_path(symbol: str, month: str) -> Path:
    return (
        ROOT
        / "data/raw/spot"
        / symbol
        / "1d"
        / f"{symbol}-1d-{month}.zip"
    )


def _download_month(client: httpx.Client, symbol: str, month: str) -> float | None:
    path = _month_path(symbol, month)
    if path.exists() and path.stat().st_size > 0:
        content = path.read_bytes()
    else:
        url = (
            f"https://data.binance.vision/data/spot/monthly/klines/"
            f"{symbol}/1d/{symbol}-1d-{month}.zip"
        )
        response = client.get(url)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        content = response.content
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    try:
        frame = parse_zip(content, path.name)
        if frame.is_empty() or "quote_volume" not in frame.columns:
            return None
        return float(frame["quote_volume"].sum())
    except Exception:
        return None


def _membership(
    volumes: dict[str, dict[str, float]],
    size_by_symbol: dict[str, dict[str, int]],
    months: list[str],
    *,
    candidate_n: int,
    target_n: int,
    entry_rank: int,
    exit_rank: int,
    rebalance_months: int,
) -> tuple[pl.DataFrame, dict[str, list[str]]]:
    rows: list[dict[str, str]] = []
    current: set[str] = set()
    selected_by_month: dict[str, list[str]] = {}
    for idx, month in enumerate(months):
        previous = months[idx - 1] if idx > 0 else None
        if (idx - 1) % rebalance_months == 0 and previous is not None:
            candidates = sorted(
                (
                    (symbol, size_by_symbol.get(symbol, {}).get(previous, 0))
                    for symbol in size_by_symbol
                ),
                key=lambda item: item[1],
                reverse=True,
            )[:candidate_n]
            ranked = sorted(
                (
                    (symbol, volumes.get(symbol, {}).get(previous, 0.0))
                    for symbol, _ in candidates
                    if volumes.get(symbol, {}).get(previous, 0.0) > 0
                ),
                key=lambda item: item[1],
                reverse=True,
            )
            ranks = {symbol: i + 1 for i, (symbol, _) in enumerate(ranked)}
            keep = {
                symbol
                for symbol in current
                if ranks.get(symbol, 10**9) <= exit_rank
            }
            add = [
                symbol
                for symbol, _ in ranked[:entry_rank]
                if symbol not in keep
            ]
            current = set(list(keep)[:target_n] + add[: max(0, target_n - len(keep))])
            # If the keep set is larger than the target, retain the best ranks.
            current = set(
                sorted(current, key=lambda s: ranks.get(s, 10**9))[:target_n]
            )
        selected_by_month[month] = sorted(current)
        rows.extend(
            {"effective_date": f"{month}-01", "asset": symbol}
            for symbol in current
        )
    membership = pl.DataFrame(rows).with_columns(pl.col("effective_date").str.to_date())
    return membership, selected_by_month


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2020-01")
    parser.add_argument("--end", default="2026-09")
    parser.add_argument("--candidate-n", type=int, default=40)
    parser.add_argument("--target-n", type=int, default=20)
    parser.add_argument("--entry-rank", type=int, default=20)
    parser.add_argument("--exit-rank", type=int, default=30)
    parser.add_argument("--rebalance-months", type=int, default=3)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()

    months = _months("2019-12", args.end)
    symbols = [
        p.stem
        for p in CACHE.glob("*.json")
        if _eligible(p.stem)
    ]
    if not symbols:
        raise SystemExit("no cached symbol listings; run scripts/build_pit_full.py first")
    size_by_symbol = {symbol: _load_objects(symbol) for symbol in symbols}
    print(f"symbols with archive cache: {len(symbols)}")

    # Candidate symbols by size for any month in the range.
    candidate_symbols = sorted(
        {
            symbol
            for symbol, sizes in size_by_symbol.items()
            if any(month in sizes for month in months)
        }
    )
    print(f"candidate symbols: {len(candidate_symbols)}")

    volumes: dict[str, dict[str, float]] = {}
    if VOLUME_CACHE.exists():
        volumes = json.loads(VOLUME_CACHE.read_text(encoding="utf-8"))

    tasks = []
    for month in months:
        previous = months[months.index(month) - 1] if months.index(month) > 0 else None
        if previous is None:
            continue
        top = sorted(
            (
                (symbol, size_by_symbol[symbol].get(previous, 0))
                for symbol in candidate_symbols
            ),
            key=lambda item: item[1],
            reverse=True,
        )[: args.candidate_n]
        for symbol, _ in top:
            if previous not in volumes.get(symbol, {}):
                tasks.append((symbol, previous))

    print(f"volume rows to fetch: {len(tasks)}")
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        def load(task: tuple[str, str]) -> tuple[str, str, float | None]:
            symbol, month = task
            return symbol, month, _download_month(client, symbol, month)

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(load, task) for task in tasks]
            for i, future in enumerate(as_completed(futures), 1):
                symbol, month, volume = future.result()
                if volume is not None:
                    volumes.setdefault(symbol, {})[month] = volume
                if i % 100 == 0:
                    print(f"  volumes {i}/{len(tasks)}")

    VOLUME_CACHE.parent.mkdir(parents=True, exist_ok=True)
    VOLUME_CACHE.write_text(json.dumps(volumes), encoding="utf-8")
    print(f"volume symbols: {len(volumes)}")

    membership, selected = _membership(
        volumes,
        size_by_symbol,
        months,
        candidate_n=args.candidate_n,
        target_n=args.target_n,
        entry_rank=args.entry_rank,
        exit_rank=args.exit_rank,
        rebalance_months=args.rebalance_months,
    )
    membership = membership.filter(
        pl.col("effective_date") >= date.fromisoformat(f"{args.start}-01")
    )
    selected = {month: assets for month, assets in selected.items() if month >= args.start}
    membership_path = save_membership(membership, ROOT / "config/pit_universe_v2.csv")
    unique = sorted({s for symbols in selected.values() for s in symbols})
    print(f"months: {len(months)}, membership rows: {membership.height}, unique: {len(unique)}")
    print(membership_path)
    if args.skip_download:
        return 0

    existing_path = ROOT / "data/normalized/bars_pit_full.parquet"
    existing = load_bars(existing_path) if existing_path.exists() else pl.DataFrame()
    have = set(existing["asset"].unique().to_list()) if not existing.is_empty() else set()
    missing = [s for s in unique if s not in have]
    print(f"assets already cached: {len(unique) - len(missing)}, missing: {len(missing)}")
    frames = [existing] if not existing.is_empty() else []
    if missing:
        def download(symbol: str) -> pl.DataFrame:
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

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(download, s): s for s in missing}
            for i, future in enumerate(as_completed(futures), 1):
                print(f"  download {i}/{len(missing)} {futures[future]}")
                frames.append(future.result())
    bars = pl.concat(frames).unique(subset=["timestamp", "asset"], keep="last").sort(
        ["timestamp", "asset"]
    )
    bars = bars.filter(pl.col("timestamp").dt.date() < datetime.now(UTC).date())
    bars_path = save_bars(bars, ROOT / "data/normalized/bars_pit_v2.parquet")
    print(f"bars: {bars_path} ({bars.height:,} rows)")

    meta = yaml.safe_load((ROOT / "config/meta.yaml").read_text(encoding="utf-8"))
    meta["data"]["symbols"] = unique
    meta["data"]["start"] = "2017-08"
    meta["data"]["bars_path"] = "data/normalized/bars_pit_v2.parquet"
    meta["data"]["universe_path"] = "config/pit_universe_v2.csv"
    meta["backtest"]["output_dir"] = "artifacts/pit_v2"
    for key, value in {
        "state_path": "artifacts/pit_v2/paper_state.json",
        "journal_path": "artifacts/pit_v2/orders.sqlite",
        "order_state_path": "artifacts/pit_v2/order_state.sqlite",
        "performance_path": "artifacts/pit_v2/performance.jsonl",
        "heartbeat_path": "artifacts/pit_v2/heartbeat.json",
    }.items():
        meta["broker"][key] = value
    meta["risk"]["state_path"] = "artifacts/pit_v2/risk_state.json"
    meta["risk"]["kill_switch_file"] = "artifacts/pit_v2/KILL"
    cfg_path = ROOT / "config/pit_v2.yaml"
    cfg_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    print(f"config: {cfg_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
