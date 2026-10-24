"""Load recorded option-chain snapshots for event replay.

This loader is venue-agnostic. The CSV/Parquet schema is intentionally explicit
so a vendor export can be validated before replay.

Required columns:
    timestamp, underlying, instrument, option_type, strike, expiry,
    bid, ask, mark, delta, gamma, vega, theta, open_interest,
    underlying_price
Optional:
    volume, multiplier
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from tradingbot.options.account import OptionCandidate
from tradingbot.options.backtest import OptionSnapshot

REQUIRED = [
    "timestamp",
    "underlying",
    "instrument",
    "option_type",
    "strike",
    "expiry",
    "bid",
    "ask",
    "mark",
    "delta",
    "gamma",
    "vega",
    "theta",
    "open_interest",
    "underlying_price",
]


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, date):
        ts = datetime.combine(value, datetime.min.time())
    else:
        ts = datetime.fromisoformat(str(value))
    return ts.astimezone(UTC) if ts.tzinfo else ts.replace(tzinfo=UTC)


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def load_option_snapshots(path: str | Path) -> list[OptionSnapshot]:
    """Load and validate a snapshot export.

    Every timestamp must contain one underlying price per underlying. Duplicate
    instrument rows at the same timestamp are rejected.
    """
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(source)
    if source.suffix.lower() == ".parquet":
        frame = pl.read_parquet(source)
    elif source.suffix.lower() == ".csv":
        frame = pl.read_csv(source, try_parse_dates=True)
    else:
        raise ValueError("option snapshots must be CSV or Parquet")
    missing = [column for column in REQUIRED if column not in frame.columns]
    if missing:
        raise ValueError(f"snapshot missing columns: {missing}")
    if frame.is_empty():
        raise ValueError("snapshot file is empty")

    by_ts: dict[datetime, tuple[dict[str, float], list[OptionCandidate]]] = {}
    seen_instruments: dict[datetime, set[str]] = {}
    for row in frame.sort("timestamp").iter_rows(named=True):
        ts = _as_datetime(row["timestamp"])
        underlying = str(row["underlying"])
        instrument = str(row["instrument"])
        seen = seen_instruments.setdefault(ts, set())
        if instrument in seen:
            raise ValueError(f"duplicate instrument {instrument} at {ts}")
        seen.add(instrument)
        price = float(row["underlying_price"])
        if price <= 0:
            raise ValueError(f"invalid underlying price for {instrument}")
        candidate = OptionCandidate(
            instrument=instrument,
            underlying=underlying,
            option_type=str(row["option_type"]),  # type: ignore[arg-type]
            strike=float(row["strike"]),
            expiry=_as_date(row["expiry"]),
            bid=float(row["bid"]),
            ask=float(row["ask"]),
            mark=float(row["mark"]),
            delta=float(row["delta"]),
            gamma=float(row["gamma"]),
            vega=float(row["vega"]),
            theta=float(row["theta"]),
            open_interest=int(row["open_interest"]),
            volume=int(row.get("volume") or 0),
            multiplier=float(row.get("multiplier") or 1.0),
        )
        prices, chain = by_ts.setdefault(ts, ({}, []))
        existing = prices.get(underlying)
        if existing is not None and abs(existing - price) > 1e-9:
            raise ValueError(
                f"inconsistent underlying price for {underlying} at {ts}"
            )
        prices[underlying] = price
        chain.append(candidate)

    snapshots = [
        OptionSnapshot(timestamp=ts, chain=chain, underlying_prices=prices)
        for ts, (prices, chain) in sorted(by_ts.items())
    ]
    for snapshot in snapshots:
        if not snapshot.chain or not snapshot.underlying_prices:
            raise ValueError(f"incomplete snapshot at {snapshot.timestamp}")
    return snapshots
