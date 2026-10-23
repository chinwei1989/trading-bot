"""Build the delisted-inclusive extended research universe.

This is deliberately bounded: the current eight majors plus three delisted
Binance spot pairs with normal price histories. COCOSUSDT is excluded because
its archive contains a huge redenomination-like price jump that would create a
false 1,000x return unless corporate actions are normalized.

The output is research data only. It is not used by the paper/live configs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from tradingbot.data.binance import download_symbol
from tradingbot.data.store import load_bars, save_bars
from tradingbot.data.universe import save_spans, spans_from_bars

ROOT = Path(__file__).resolve().parents[1]
CURRENT = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "LINKUSDT",
]
DELISTED = ["BUSDUSDT", "SRMUSDT", "TOMOUSDT"]


def main() -> int:
    base_path = ROOT / "data/normalized/bars_max_history.parquet"
    if base_path.exists():
        frames = [load_bars(base_path)]
    else:
        frames = [
            download_symbol(
                symbol,
                "spot",
                "1d",
                "2017-08",
                "2026-10",
                ROOT / "data/raw",
                use_cache=True,
                verify=True,
            )
            for symbol in CURRENT
        ]
    for symbol in DELISTED:
        print(f"[delisted] {symbol}")
        frames.append(
            download_symbol(
                symbol,
                "spot",
                "1d",
                "2017-08",
                "2026-10",
                ROOT / "data/raw",
                use_cache=True,
                verify=True,
            )
        )
    bars = (
        pl.concat(frames)
        .unique(subset=["timestamp", "asset"], keep="last")
        .sort(["timestamp", "asset"])
        .filter(pl.col("timestamp").dt.date() < datetime.now(UTC).date())
    )
    out = save_bars(bars, ROOT / "data/normalized/bars_pit_extended.parquet")
    spans = spans_from_bars(bars, open_ended=False).with_columns(
        pl.when(pl.col("asset").is_in(CURRENT))
        .then(None)
        .otherwise(pl.col("end"))
        .alias("end")
    )
    universe = save_spans(spans, ROOT / "config/pit_universe_crypto_extended.csv")
    print(f"bars: {out} ({bars.height:,} rows, {bars['asset'].n_unique()} assets)")
    print(f"universe: {universe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
