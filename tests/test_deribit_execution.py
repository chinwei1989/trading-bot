from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
import pytest

from tradingbot.options.deribit_execution import (
    DeribitAPIError,
    DeribitExecutionClient,
    DeribitOrderRequest,
    DeribitPosition,
    inverse_intrinsic_coin,
    parse_contract,
    reconcile_positions,
)


def _handler(calls: list[tuple[dict[str, Any], str | None]]):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append((payload, request.headers.get("authorization")))
        method = payload["method"]
        if method == "public/auth":
            result: Any = {"access_token": "test-token", "expires_in": 900}
        elif method == "private/get_account_summary":
            result = {"currency": "BTC", "equity": 1.5}
        elif method == "private/get_positions":
            result = [
                {
                    "instrument_name": "BTC-30OCT26-100000-C",
                    "size": 1,
                    "average_price": 0.05,
                    "mark_price": 0.06,
                    "delta": 0.4,
                    "kind": "option",
                }
            ]
        elif method in {"private/buy", "private/sell"}:
            result = {
                "order": {
                    "order_id": "order-1",
                    "instrument_name": payload["params"]["instrument_name"],
                    "direction": "buy" if method == "private/buy" else "sell",
                    "order_state": "open",
                    "amount": payload["params"]["amount"],
                    "filled_amount": 0,
                    "average_price": None,
                    "price": payload["params"].get("price"),
                    "commission": 0,
                    "label": payload["params"].get("label", ""),
                }
            }
        else:
            result = {}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": result})

    return handler


def test_authenticated_client_and_order_round_trip() -> None:
    calls: list[tuple[dict[str, Any], str | None]] = []
    transport = httpx.MockTransport(_handler(calls))
    http = httpx.Client(transport=transport)
    client = DeribitExecutionClient(
        client_id="client-id",
        client_secret="client-secret",
        client=http,
    )
    try:
        summary = client.account_summary("BTC")
        assert summary["equity"] == 1.5
        assert calls[0][0]["method"] == "public/auth"
        assert calls[1][1] == "Bearer test-token"

        positions = client.positions("BTC")
        assert positions[0].instrument == "BTC-30OCT26-100000-C"
        assert positions[0].size == 1

        order = client.place_order(
            DeribitOrderRequest(
                instrument="BTC-30OCT26-100000-C",
                side="buy",
                amount=1,
                price=0.05,
                label="test",
            )
        )
        assert order.order_id == "order-1"
        assert order.side == "buy"
        assert order.state == "open"
        assert calls[-1][0]["method"] == "private/buy"
        assert calls[-1][0]["params"]["amount"] == 1
    finally:
        client.close()
        http.close()


def test_sell_must_be_reduce_only_and_live_is_blocked() -> None:
    calls: list[tuple[dict[str, Any], str | None]] = []
    http = httpx.Client(transport=httpx.MockTransport(_handler(calls)))
    client = DeribitExecutionClient(client_id="id", client_secret="secret", client=http)
    try:
        with pytest.raises(PermissionError, match="reduce_only"):
            client.place_order(
                DeribitOrderRequest(
                    instrument="BTC-30OCT26-100000-C",
                    side="sell",
                    amount=1,
                    price=0.05,
                )
            )
    finally:
        client.close()
        http.close()

    with pytest.raises(PermissionError, match="LIVE_TRADING"):
        DeribitExecutionClient(environment="live", client_id="id", client_secret="secret")


def test_missing_credentials_fail_closed() -> None:
    calls: list[tuple[dict[str, Any], str | None]] = []
    http = httpx.Client(transport=httpx.MockTransport(_handler(calls)))
    client = DeribitExecutionClient(client=http)
    try:
        with pytest.raises(PermissionError, match="DERIBIT_CLIENT_ID"):
            client.account_summary()
    finally:
        client.close()
        http.close()


def test_contract_parser_and_position_reconciliation() -> None:
    contract = parse_contract("ETH-30OCT26-3000-P")
    assert contract is not None
    assert contract.underlying == "ETH"
    assert contract.expiry == date(2026, 10, 30)
    assert contract.option_type == "put"
    assert parse_contract("bad") is None
    assert inverse_intrinsic_coin("call", 100_000, 110_000) == pytest.approx(
        10_000 / 110_000
    )
    assert inverse_intrinsic_coin("put", 110_000, 100_000) == pytest.approx(
        10_000 / 100_000
    )
    assert inverse_intrinsic_coin("call", 100_000, 90_000) == 0.0

    remote = [DeribitPosition("BTC-30OCT26-100000-C", 1, 0.05, 0.06, 0.4, "option")]
    assert reconcile_positions({"BTC-30OCT26-100000-C": 1}, remote)["ok"]
    mismatch = reconcile_positions({"BTC-30OCT26-100000-C": 2}, remote)
    assert not mismatch["ok"]
    assert mismatch["differences"]["BTC-30OCT26-100000-C"]["delta"] == 1


def test_api_error_is_redacted() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": json.loads(request.content)["id"],
                "error": {"code": 10001, "message": "invalid credentials"},
            },
        )
    )
    http = httpx.Client(transport=transport)
    client = DeribitExecutionClient(client_id="id", client_secret="secret", client=http)
    try:
        with pytest.raises(DeribitAPIError, match="10001"):
            client.account_summary()
        assert "secret" not in str(DeribitAPIError("x", 1, "invalid credentials"))
    finally:
        client.close()
        http.close()
