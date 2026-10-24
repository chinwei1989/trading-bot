"""Ingest a free Tardis Deribit options_chain day into replay snapshots.

Usage:
    uv run python scripts/ingest_tardis_options.py \
        data/raw/tardis/deribit_options_chain_2026-10-01.csv.gz \
        data/normalized/options_tardis_2026-10-01.csv

Tardis makes the first day of each month available without an API key.  The
input is tick-level; the output keeps the last quote per instrument at each
30-minute boundary.  No purchase or API key is required.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from tradingbot.options.tardis import ingest_tardis_options


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--bucket-minutes", type=int, default=30)
    parser.add_argument(
        "--underlyings",
        nargs="+",
        default=["BTC", "ETH"],
        help="inverse underlyings to keep",
    )
    args = parser.parse_args()
    started = time.monotonic()
    result = ingest_tardis_options(
        args.source,
        args.output,
        underlyings=tuple(args.underlyings),
        bucket_minutes=args.bucket_minutes,
    )
    elapsed = time.monotonic() - started
    print(
        f"tardis ingest: rows={result.rows_read:,} "
        f"snapshots={result.snapshots} contracts={result.contracts_written:,} "
        f"elapsed={elapsed:.1f}s"
    )
    print(f"snapshots: {result.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
