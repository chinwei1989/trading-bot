"""Exchange calendar helpers."""

from __future__ import annotations

from datetime import date

import exchange_calendars as xcals  # type: ignore[import-untyped]
import pandas as pd  # type: ignore[import-untyped]


def is_us_trading_day(day: date | None = None) -> bool:
    day = day or pd.Timestamp.now(tz="UTC").date()
    cal = xcals.get_calendar("XNYS")
    return bool(cal.is_session(pd.Timestamp(day)))
