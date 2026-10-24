"""Convert Tardis.dev Deribit ``options_chain`` CSV exports to snapshots.

Tardis publishes the first day of each month as free CSV datasets.  The
``options_chain`` export is tick-level and contains every option instrument for
the day, which is far too large and granular for the replay engine.  This
module streams it once, keeps only the configured inverse underlyings, and
writes the last known quote per instrument at each fixed interval.

The output is the venue-agnostic snapshot schema consumed by
:func:`tradingbot.options.historical.load_option_snapshots`.

This is research/paper infrastructure.  It does not fetch data, place orders,
or establish that an option strategy is profitable.
"""

from __future__ import annotations

import csv
import gzip
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_BUCKET_US = 30 * 60 * 1_000_000

# `underlying` -> symbol prefix.  The prefix check deliberately excludes the
# USDC-linear contracts (BTC_USDC-...) because their premiums are already USD.
_PREFIXES: dict[str, str] = {"BTC": "BTC-", "ETH": "ETH-"}

_COLUMNS = [
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
    "volume",
    "multiplier",
    "underlying_price",
]


@dataclass(frozen=True)
class TardisIngestResult:
    path: Path
    snapshots: int
    rows_read: int
    contracts_written: int
    underlyings: tuple[str, ...]


def _timestamp_us(value: str) -> int:
    return int(value)


def _as_float(value: str) -> float:
    if not value:
        return 0.0
    return float(value)


def _as_int(value: str) -> int:
    if not value:
        return 0
    return int(float(value))


def _underlying_for(symbol: str, prefixes: dict[str, str]) -> str | None:
    for underlying, prefix in prefixes.items():
        if symbol.startswith(prefix):
            return underlying
    return None


def _expiry_date(expiration_us: int) -> str:
    return datetime.fromtimestamp(expiration_us / 1_000_000, UTC).date().isoformat()


def ingest_tardis_options(
    source: str | Path,
    output: str | Path,
    *,
    underlyings: tuple[str, ...] = ("BTC", "ETH"),
    bucket_minutes: int = 30,
) -> TardisIngestResult:
    """Stream a Tardis ``options_chain`` CSV.gz into compact snapshots.

    Timestamps are bucketed by ``local_timestamp``, the arrival time recorded by
    Tardis.  A snapshot emitted at ``T`` contains only updates observed strictly
    before ``T``; this keeps the replay decision point causal.
    """
    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    if source_path.suffix.lower() != ".gz":
        raise ValueError("expected a Tardis .csv.gz export")
    if bucket_minutes <= 0:
        raise ValueError("bucket_minutes must be positive")
    selected = {underlying: _PREFIXES[underlying] for underlying in underlyings}
    if not selected:
        raise ValueError("at least one underlying is required")

    bucket_us = bucket_minutes * 60 * 1_000_000
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(output_path.name + ".tmp")

    rows_read = 0
    contracts_written = 0
    snapshots = 0
    next_bucket: int | None = None
    state: dict[str, list[str]] = {}
    last_underlying_price: dict[str, float] = {}

    def write_snapshot(writer: Any, bucket: int) -> None:
        nonlocal contracts_written, snapshots
        prices = {
            underlying: price
            for underlying, price in last_underlying_price.items()
            if underlying in selected and price > 0
        }
        if not state or not prices:
            return
        timestamp = datetime.fromtimestamp(bucket / 1_000_000, UTC).isoformat()
        wrote = 0
        for symbol, row in state.items():
            underlying = _underlying_for(symbol, selected)
            if underlying is None:
                continue
            underlying_price = prices.get(underlying)
            if underlying_price is None:
                continue
            try:
                strike = _as_float(row[5])
                expiration_us = int(row[6])
                expiry = _expiry_date(expiration_us)
                multiplier = 1.0
                # Deribit inverse option premiums are quoted in the base coin.
                # Convert them to a USD approximation for the paper broker.
                bid = _as_float(row[9]) * underlying_price
                ask = _as_float(row[12]) * underlying_price
                mark = _as_float(row[15]) * underlying_price
                writer.writerow(
                    [
                        timestamp,
                        underlying,
                        symbol,
                        row[4].lower(),
                        strike,
                        expiry,
                        bid,
                        ask,
                        mark,
                        _as_float(row[19]),
                        _as_float(row[20]),
                        _as_float(row[21]),
                        _as_float(row[22]),
                        _as_int(row[7]),
                        0,
                        multiplier,
                        underlying_price,
                    ]
                )
                wrote += 1
            except (ValueError, IndexError):
                # Skip malformed or non-numeric rows rather than fabricating a
                # quote.  The source file is large and exchange exports can
                # contain occasional empty fields.
                continue
        if wrote:
            snapshots += 1
            contracts_written += wrote

    try:
        with gzip.open(source_path, "rt", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if header is None:
                raise ValueError("empty Tardis export")
            required = {
                "symbol",
                "local_timestamp",
                "type",
                "strike_price",
                "expiration",
                "open_interest",
                "bid_price",
                "ask_price",
                "mark_price",
                "underlying_price",
                "delta",
                "gamma",
                "vega",
                "theta",
            }
            missing = required.difference(header)
            if missing:
                raise ValueError(f"Tardis export missing columns: {sorted(missing)}")

            with temp_path.open("w", encoding="utf-8", newline="") as target:
                writer = csv.writer(target, lineterminator="\n")
                writer.writerow(_COLUMNS)
                for row in reader:
                    rows_read += 1
                    if len(row) < 23:
                        continue
                    try:
                        observed_us = _timestamp_us(row[3])
                    except ValueError:
                        continue
                    if next_bucket is None:
                        next_bucket = (observed_us // bucket_us + 1) * bucket_us
                    while next_bucket is not None and observed_us >= next_bucket:
                        write_snapshot(writer, next_bucket)
                        next_bucket += bucket_us
                    symbol = row[1]
                    underlying = _underlying_for(symbol, selected)
                    if underlying is None:
                        continue
                    try:
                        last_underlying_price[underlying] = _as_float(row[18])
                    except ValueError:
                        continue
                    state[symbol] = row
                    if rows_read % 20_000_000 == 0:
                        print(
                            f"  tardis: rows={rows_read:,} "
                            f"contracts={contracts_written:,} snapshots={snapshots}",
                            flush=True,
                        )

                # Emit a final snapshot at the next boundary if the day ends
                # before it.  The replay is still strictly causal because all
                # captured rows are older than the bucket.
                if next_bucket is not None:
                    write_snapshot(writer, next_bucket)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    temp_path.replace(output_path)

    return TardisIngestResult(
        path=output_path,
        snapshots=snapshots,
        rows_read=rows_read,
        contracts_written=contracts_written,
        underlyings=underlyings,
    )
