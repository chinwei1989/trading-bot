"""Replay one free Tardis Deribit options-chain day.

Inputs:
    data/normalized/options_tardis_2026-10-01.csv
    data/normalized/bars_30m_tardis_warmup.parquet  (Binance September warmup)

The chain is real exchange data.  The underlying signal is a deliberately
simple 200-bar SMA on real 30-minute closes; this is a data/plumbing test, not
an AI replay and not evidence of a profitable strategy.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl

from tradingbot.data.binance import fetch_window
from tradingbot.data.store import load_bars, save_bars
from tradingbot.options.backtest import replay_options
from tradingbot.options.historical import load_option_snapshots
from tradingbot.options.synthetic import sma_direction_signal

ROOT = Path(__file__).resolve().parents[1]
DAY = date(2026, 10, 1)
DAY_START = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
DAY_END = datetime(2026, 10, 1, 23, 59, 59, tzinfo=UTC)
CHAIN_PATH = ROOT / "data" / "normalized" / "options_tardis_2026-10-01.csv"
WARMUP_PATH = ROOT / "data" / "normalized" / "bars_30m_tardis_warmup.parquet"
DAY_BARS_PATH = ROOT / "data" / "normalized" / "bars_30m_binance_2026-10-01.parquet"
OUT = ROOT / "artifacts" / "options_tardis"


def _day_bars() -> pl.DataFrame:
    """Load or fetch real Binance 30m bars for the replay day."""
    if DAY_BARS_PATH.exists():
        return load_bars(DAY_BARS_PATH)
    frames = [
        fetch_window(
            symbol,
            "30m",
            start=DAY_START,
            end=DAY_END,
        )
        for symbol in ("BTCUSDT", "ETHUSDT")
    ]
    bars = pl.concat(frames).sort(["timestamp", "asset"])
    save_bars(bars, DAY_BARS_PATH)
    return bars


def _closed_signal_bars(
    warmup: pl.DataFrame,
    day_bars: pl.DataFrame,
) -> pl.DataFrame:
    """Shift bar open times to close times so a 00:30 decision uses 00:00-00:30."""
    bars = (
        pl.concat([warmup, day_bars])
        .unique(subset=["timestamp", "asset"], keep="last")
        .sort(["timestamp", "asset"])
    )
    return bars.with_columns(
        (pl.col("timestamp") + timedelta(minutes=30)).alias("timestamp")
    )


def main() -> int:
    if not CHAIN_PATH.exists():
        raise FileNotFoundError(CHAIN_PATH)
    if not WARMUP_PATH.exists():
        raise FileNotFoundError(WARMUP_PATH)

    all_snapshots = load_option_snapshots(CHAIN_PATH)
    snapshots = [item for item in all_snapshots if item.timestamp.date() == DAY]
    if len(snapshots) < 2:
        raise ValueError("not enough Tardis snapshots for the replay")

    warmup = load_bars(WARMUP_PATH)
    day_bars = _day_bars()
    bars = _closed_signal_bars(warmup, day_bars)
    signal = sma_direction_signal(bars, lookback=200)
    result = replay_options(
        snapshots,
        signal,
        initial_cash=10_000.0,
        fee_bps=3.0,
        max_contracts=1,
    )

    fills = [
        {
            "timestamp": cycle.timestamp.isoformat(),
            "instrument": fill.instrument,
            "side": fill.side,
            "contracts": fill.qty,
            "premium": fill.premium,
            "fee": fill.fee,
        }
        for cycle in result.cycles
        for fill in cycle.fills
    ]
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "engine": "real Tardis Deribit options_chain replay",
        "data_source": (
            "Tardis.dev free first-day-of-month Deribit options_chain CSV"
        ),
        "chain_date": DAY.isoformat(),
        "chain_file": str(CHAIN_PATH.relative_to(ROOT)),
        "signal_source": "Binance public 30m klines",
        "signal_timestamp": "bar close; 00:30 decision uses 00:00-00:30 bar",
        "snapshots": len(snapshots),
        "underlying_bars": bars.height,
        "initial_cash": 10_000.0,
        "final_equity": result.final_equity,
        "total_return": result.total_return,
        "max_drawdown": result.max_drawdown,
        "total_fills": result.total_fills,
        "total_fees": result.total_fees,
        "cycles_blocked": result.cycles_blocked,
        "fills": fills,
        "last_cycles": [
            {
                "timestamp": cycle.timestamp.isoformat(),
                "equity": cycle.equity,
                "cash": cycle.cash,
                "open_legs": cycle.open_legs,
                "alerts": cycle.alerts,
            }
            for cycle in result.cycles[-5:]
        ],
        "limitations": (
            "One free chain day only. Real bid/ask/Greeks/OI, but inverse "
            "premiums are converted to a USD approximation. The underlying "
            "signal is a simple SMA on Binance bars, not the AI squad. Long "
            "premium only; no expiry settlement occurs within a single day. "
            "This is a data and plumbing test, not evidence of edge."
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "tardis_replay_2026-10-01.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"tardis replay: snapshots={len(snapshots)} fills={result.total_fills} "
        f"equity=${result.final_equity:,.2f} return={result.total_return:.2%} "
        f"max_dd={result.max_drawdown:.2%} fees=${result.total_fees:,.2f}"
    )
    print(f"saved: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
