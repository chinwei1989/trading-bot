from __future__ import annotations

import csv
import gzip
from datetime import UTC, datetime
from pathlib import Path

from tradingbot.options.historical import load_option_snapshots
from tradingbot.options.tardis import ingest_tardis_options

HEADER = [
    "exchange",
    "symbol",
    "timestamp",
    "local_timestamp",
    "type",
    "strike_price",
    "expiration",
    "open_interest",
    "last_price",
    "bid_price",
    "bid_amount",
    "bid_iv",
    "ask_price",
    "ask_amount",
    "ask_iv",
    "mark_price",
    "mark_iv",
    "underlying_index",
    "underlying_price",
    "delta",
    "gamma",
    "vega",
    "theta",
    "rho",
]


def _us(value: datetime) -> str:
    return str(int(value.timestamp() * 1_000_000))


def _row(
    symbol: str,
    *,
    ts: datetime,
    option_type: str,
    strike: str,
    expiry: datetime,
    underlying: float,
    bid: str,
    ask: str,
    mark: str,
) -> list[str]:
    return [
        "deribit",
        symbol,
        _us(ts),
        _us(ts),
        option_type,
        strike,
        _us(expiry),
        "250",
        "0",
        bid,
        "100",
        "50",
        ask,
        "100",
        "51",
        mark,
        "52",
        symbol.split("-")[0],
        str(underlying),
        "0.4",
        "0.00001",
        "12.0",
        "-3.0",
        "0.0",
    ]


def test_ingest_tardis_options_filters_and_converts_inverse_premium(
    tmp_path: Path,
) -> None:
    source = tmp_path / "options.csv.gz"
    output = tmp_path / "snapshots.csv"
    start = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    expiry = datetime(2026, 10, 9, 8, 0, tzinfo=UTC)
    with gzip.open(source, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(HEADER)
        writer.writerow(
            _row(
                "BTC-9OCT26-100000-C",
                ts=start,
                option_type="call",
                strike="100000",
                expiry=expiry,
                underlying=100_000.0,
                bid="0.05",
                ask="0.06",
                mark="0.055",
            )
        )
        writer.writerow(
            _row(
                "ETH-9OCT26-4000-P",
                ts=start,
                option_type="put",
                strike="4000",
                expiry=expiry,
                underlying=4_000.0,
                bid="0.02",
                ask="0.03",
                mark="0.025",
            )
        )
        writer.writerow(
            _row(
                "XRP_USDC-9OCT26-2-C",
                ts=start,
                option_type="call",
                strike="2",
                expiry=expiry,
                underlying=2.0,
                bid="0.1",
                ask="0.2",
                mark="0.15",
            )
        )

    result = ingest_tardis_options(source, output, bucket_minutes=30)
    assert result.snapshots == 1
    assert result.contracts_written == 2

    snapshots = load_option_snapshots(output)
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.underlying_prices == {"BTC": 100_000.0, "ETH": 4_000.0}
    by_symbol = {item.instrument: item for item in snapshot.chain}
    assert set(by_symbol) == {"BTC-9OCT26-100000-C", "ETH-9OCT26-4000-P"}
    assert by_symbol["BTC-9OCT26-100000-C"].bid == 5_000.0
    assert by_symbol["BTC-9OCT26-100000-C"].ask == 6_000.0
    assert by_symbol["BTC-9OCT26-100000-C"].mark == 5_500.0
    assert by_symbol["ETH-9OCT26-4000-P"].bid == 80.0
    assert by_symbol["ETH-9OCT26-4000-P"].ask == 120.0
    assert by_symbol["ETH-9OCT26-4000-P"].open_interest == 250
