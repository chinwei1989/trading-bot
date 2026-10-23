from __future__ import annotations

from datetime import date

from tradingbot.ops.calendar import is_us_trading_day


def test_us_trading_day() -> None:
    assert is_us_trading_day(date(2024, 1, 8)) is True
    assert is_us_trading_day(date(2024, 1, 6)) is False  # Saturday
    assert is_us_trading_day(date(2024, 1, 1)) is False  # New Year's Day
