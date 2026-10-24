"""Read-only Deribit public option-chain adapter.

Deribit options are inverse contracts quoted in the underlying coin. This
adapter converts the premium and Greeks into a USD-marked approximation for the
generic paper broker. It does not implement inverse settlement or place orders.

The adapter is for data ingestion and fixture-based research only.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime
from statistics import NormalDist
from typing import Any

import httpx

from tradingbot.options.account import OptionCandidate, OptionType

DEFAULT_URL = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"
_NORMAL = NormalDist()


def _parse_expiry(text: str) -> date | None:
    try:
        return datetime.strptime(text.upper(), "%d%b%y").date()
    except ValueError:
        return None


def _instrument_parts(name: str) -> tuple[str, date, float, OptionType] | None:
    parts = name.split("-")
    if len(parts) != 4:
        return None
    underlying, expiry_text, strike_text, option_type = parts
    expiry = _parse_expiry(expiry_text)
    if expiry is None:
        return None
    if option_type not in {"C", "P"}:
        return None
    try:
        strike = float(strike_text)
    except ValueError:
        return None
    return underlying, expiry, strike, "call" if option_type == "C" else "put"


def _black_scholes(
    *,
    spot: float,
    strike: float,
    sigma: float,
    dte: int,
    option_type: OptionType,
) -> tuple[float, float, float, float, float]:
    """USD Black-Scholes price and Greeks.

    Returns price, delta, gamma, vega (per 1 vol point), and theta (per day).
    This is an approximation for inverse Deribit contracts.
    """
    if spot <= 0 or strike <= 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    t = max(dte, 1) / 365.0
    vol = max(sigma, 1e-6)
    root_t = math.sqrt(t)
    d1 = (math.log(spot / strike) + 0.5 * vol * vol * t) / (vol * root_t)
    d2 = d1 - vol * root_t
    if option_type == "call":
        price = spot * _NORMAL.cdf(d1) - strike * _NORMAL.cdf(d2)
        delta = _NORMAL.cdf(d1)
    else:
        price = strike * _NORMAL.cdf(-d2) - spot * _NORMAL.cdf(-d1)
        delta = _NORMAL.cdf(d1) - 1.0
    gamma = _NORMAL.pdf(d1) / max(spot * vol * root_t, 1e-12)
    vega = spot * _NORMAL.pdf(d1) * root_t / 100.0
    theta = (
        -spot * _NORMAL.pdf(d1) * vol / (2.0 * root_t)
        - 0.0 * strike * _NORMAL.cdf(d2)
    ) / 365.0
    return max(0.0, price), delta, gamma, max(0.0, vega), min(0.0, theta)


def parse_summary(row: dict[str, Any], *, today: date | None = None) -> OptionCandidate | None:
    """Convert one Deribit book-summary row to a USD-marked candidate."""
    today = today or datetime.now(UTC).date()
    name = str(row.get("instrument_name", ""))
    parts = _instrument_parts(name)
    if parts is None:
        return None
    underlying, expiry, strike, option_type = parts
    if expiry <= today:
        return None
    try:
        spot = float(row["underlying_price"])
        bid_coin = float(row.get("bid_price") or 0.0)
        ask_coin = float(row.get("ask_price") or 0.0)
        mark_coin = float(row.get("mark_price") or 0.0)
        iv = float(row.get("mark_iv") or 0.0)
        oi = int(float(row.get("open_interest") or 0))
        volume = int(float(row.get("volume") or 0))
    except (KeyError, TypeError, ValueError):
        return None
    if spot <= 0 or iv <= 0:
        return None
    dte = (expiry - today).days
    _, delta, gamma, vega, theta = _black_scholes(
        spot=spot,
        strike=strike,
        sigma=iv / 100.0,
        dte=dte,
        option_type=option_type,
    )
    return OptionCandidate(
        instrument=name,
        underlying=underlying,
        option_type=option_type,
        strike=strike,
        expiry=expiry,
        bid=max(0.0, bid_coin * spot),
        ask=max(0.0, ask_coin * spot),
        mark=max(0.0, mark_coin * spot),
        delta=delta,
        gamma=gamma,
        vega=vega,
        theta=theta,
        open_interest=oi,
        volume=volume,
        multiplier=1.0,
    )


class DeribitPublicClient:
    """Small, read-only client for Deribit's public option summaries."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_URL,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ):
        self.base_url = base_url
        self.timeout = timeout
        self.client = client

    def fetch_chain(
        self,
        currencies: tuple[str, ...] = ("BTC", "ETH"),
        *,
        now: datetime | None = None,
    ) -> list[OptionCandidate]:
        today = (now or datetime.now(UTC)).date()
        client = self.client or httpx.Client(timeout=self.timeout)
        close_client = self.client is None
        rows: list[dict[str, Any]] = []
        try:
            for currency in currencies:
                response = client.get(
                    self.base_url,
                    params={"currency": currency, "kind": "option"},
                )
                response.raise_for_status()
                payload = response.json()
                result = payload.get("result") if isinstance(payload, dict) else None
                if not isinstance(result, list):
                    raise ValueError(f"Deribit returned no result for {currency}")
                rows.extend(item for item in result if isinstance(item, dict))
        finally:
            if close_client:
                client.close()
        candidates = [parse_summary(row, today=today) for row in rows]
        return [candidate for candidate in candidates if candidate is not None]
