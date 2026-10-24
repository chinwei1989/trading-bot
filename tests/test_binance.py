from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from typing import Any

import httpx

from tradingbot.data.binance import fetch_window, parse_kline_rows, parse_zip


def _zip(csv: str, name: str = "BTCUSDT-1d-2024-01.csv") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, csv)
    return buf.getvalue()


def test_parse_millisecond_timestamps() -> None:
    csv = (
        "1704067200000,100,110,90,105,1000,1704153599999,105000,10,500,52500,0\n"
        "1704153600000,105,115,100,110,1100,1704239999999,121000,11,550,60500,0\n"
    )
    df = parse_zip(_zip(csv), "BTCUSDT-1d-2024-01.csv")
    assert df.height == 2
    assert df["timestamp"][0].year == 2024
    assert df["timestamp"].dtype.time_zone == "UTC"
    assert df["close"][1] == 110.0


def test_parse_microsecond_timestamps() -> None:
    csv = (
        "1704067200000000,100,110,90,105,1000,1704153599999999,105000,10,500,52500,0\n"
    )
    df = parse_zip(_zip(csv), "BTCUSDT-1d-2024-01.csv")
    assert df.height == 1
    assert df["timestamp"][0].year == 2024


def test_parse_recent_json_rows() -> None:
    rows = [
        [
            1704067200000,
            "100",
            "110",
            "90",
            "105",
            "1000",
            1704153599999,
            "105000",
            10,
            "500",
            "52500",
            "0",
        ]
    ]
    df = parse_kline_rows(rows)
    assert df.height == 1
    assert df["close"][0] == 105.0


def _kline(open_ms: int, close: str = "105") -> list[Any]:
    return [
        open_ms,
        "100",
        "110",
        "90",
        close,
        "1000",
        open_ms + 1_799_999,
        "105000",
        10,
        "500",
        "52500",
        "0",
    ]


def test_fetch_window_paginates() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        start = int(request.url.params["startTime"])
        calls.append(start)
        if start == 1704067200000:
            return httpx.Response(
                200,
                json=[_kline(start), _kline(start + 1_800_000)],
            )
        if start == 1704070800000:
            return httpx.Response(200, json=[_kline(start)])
        return httpx.Response(200, json=[])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        frame = fetch_window(
            "BTCUSDT",
            "30m",
            start=datetime(2024, 1, 1, 0, 0, tzinfo=UTC),
            end=datetime(2024, 1, 1, 1, 30, tzinfo=UTC),
            client=client,
        )
    finally:
        client.close()

    assert calls == [1704067200000, 1704070800000, 1704072600000]
    assert frame.height == 3
    assert frame["asset"].to_list() == ["BTCUSDT", "BTCUSDT", "BTCUSDT"]
    assert frame["timestamp"][0] == datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    assert frame["close"][2] == 105.0


def test_parse_header_variant() -> None:
    csv = (
        "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
        "taker_buy_volume,taker_buy_quote_volume,ignore\n"
        "1704067200000,100,110,90,105,1000,1704153599999,105000,10,500,52500,0\n"
    )
    df = parse_zip(_zip(csv), "BTCUSDT-1d-2024-01.csv")
    assert df.height == 1
    assert df["open"][0] == 100.0
