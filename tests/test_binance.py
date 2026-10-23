from __future__ import annotations

import io
import zipfile

from tradingbot.data.binance import parse_kline_rows, parse_zip


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


def test_parse_header_variant() -> None:
    csv = (
        "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
        "taker_buy_volume,taker_buy_quote_volume,ignore\n"
        "1704067200000,100,110,90,105,1000,1704153599999,105000,10,500,52500,0\n"
    )
    df = parse_zip(_zip(csv), "BTCUSDT-1d-2024-01.csv")
    assert df.height == 1
    assert df["open"][0] == 100.0
