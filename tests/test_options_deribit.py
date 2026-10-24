from __future__ import annotations

from datetime import UTC, date, datetime

import httpx

from tradingbot.options.deribit import (
    DeribitPublicClient,
    parse_summary,
)


def _row(instrument: str = "ETH-25OCT26-2340-P") -> dict:
    return {
        "instrument_name": instrument,
        "base_currency": "ETH",
        "quote_currency": "ETH",
        "underlying_price": 2357.37,
        "bid_price": 0.0037,
        "ask_price": 0.0040,
        "mark_price": 0.003827,
        "mark_iv": 34.31,
        "open_interest": 817.0,
        "volume": 946.0,
    }


def test_parse_summary_converts_inverse_premium_to_usd() -> None:
    candidate = parse_summary(
        _row(),
        today=date(2026, 10, 24),
    )
    assert candidate is not None
    assert candidate.underlying == "ETH"
    assert candidate.option_type == "put"
    assert candidate.strike == 2340.0
    assert candidate.expiry == date(2026, 10, 25)
    assert candidate.bid == 0.0037 * 2357.37
    assert candidate.ask == 0.0040 * 2357.37
    assert candidate.open_interest == 817
    assert candidate.delta < 0


def test_parse_summary_rejects_expired_or_bad_rows() -> None:
    assert parse_summary(_row(), today=date(2026, 10, 26)) is None
    assert parse_summary({"instrument_name": "bad"}, today=date(2026, 10, 24)) is None
    bad_name = _row(instrument="ETH-25OCT26-2340-X")
    assert parse_summary(bad_name, today=date(2026, 10, 24)) is None


def test_client_fetches_both_currencies() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        currency = params.get("currency")
        row = _row(
            instrument=f"{currency}-25OCT26-2340-P" if currency else "ETH-25OCT26-2340-P"
        )
        row["base_currency"] = currency
        return httpx.Response(200, json={"result": [row]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetched = DeribitPublicClient(client=client).fetch_chain(
        ("BTC", "ETH"),
        now=datetime(2026, 10, 24, tzinfo=UTC),
    )
    assert {candidate.underlying for candidate in fetched} == {"BTC", "ETH"}
    assert len(fetched) == 2


def test_client_raises_on_invalid_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"not_result": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        DeribitPublicClient(client=client).fetch_chain(
            ("ETH",),
            now=datetime(2026, 10, 24, tzinfo=UTC),
        )
    except ValueError as exc:
        assert "no result" in str(exc)
    else:
        raise AssertionError("expected ValueError")
