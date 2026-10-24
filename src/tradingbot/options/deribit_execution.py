"""Deribit options execution adapter for testnet and future live use.

Safety defaults:

- ``environment="testnet"`` is the default.
- Live order placement is disabled unless both ``allow_live=True`` and
  ``LIVE_TRADING=YES`` are present, and even then this module only exposes the
  primitive calls; it does not wire them into a strategy.
- Selling requires ``reduce_only=True`` so the adapter cannot open a naked short.
- The client never stores or logs API secrets.

Authentication uses Deribit's JSON-RPC ``public/auth`` with API-key client
credentials. Market-data-only callers can use :class:`DeribitPublicClient`
instead.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal

import httpx

from tradingbot.options.deribit import _instrument_parts

ENVIRONMENTS = {
    "testnet": "https://test.deribit.com/api/v2",
    "live": "https://www.deribit.com/api/v2",
}

Side = Literal["buy", "sell"]
OrderType = Literal["limit", "market"]


class DeribitAPIError(RuntimeError):
    """A JSON-RPC error returned by Deribit; never includes credentials."""

    def __init__(self, method: str, code: int | None, message: str):
        self.method = method
        self.code = code
        self.message = message
        super().__init__(f"Deribit {method} failed: {code}: {message}")


@dataclass(frozen=True)
class DeribitOrderRequest:
    instrument: str
    side: Side
    amount: int
    order_type: OrderType = "limit"
    price: float | None = None
    label: str = ""
    reduce_only: bool = False
    post_only: bool = False


@dataclass(frozen=True)
class DeribitOrderResult:
    order_id: str
    instrument: str
    side: str
    state: str
    amount: float
    filled_amount: float
    average_price: float | None
    price: float | None
    fee: float
    label: str


@dataclass(frozen=True)
class DeribitPosition:
    instrument: str
    size: float
    average_price: float | None
    mark_price: float | None
    delta: float | None
    kind: str


@dataclass(frozen=True)
class DeribitContract:
    instrument: str
    underlying: str
    expiry: date
    strike: float
    option_type: Literal["call", "put"]
    settlement: str = "inverse"


def parse_order(payload: dict[str, Any]) -> DeribitOrderResult:
    order = payload.get("order") if isinstance(payload.get("order"), dict) else payload
    if not isinstance(order, dict):
        raise DeribitAPIError("order", None, "missing order payload")
    return DeribitOrderResult(
        order_id=str(order.get("order_id", "")),
        instrument=str(order.get("instrument_name", "")),
        side=str(order.get("direction", "")),
        state=str(order.get("order_state", "")),
        amount=float(order.get("amount", 0.0) or 0.0),
        filled_amount=float(order.get("filled_amount", 0.0) or 0.0),
        average_price=(
            float(order["average_price"])
            if order.get("average_price") is not None
            else None
        ),
        price=float(order["price"]) if order.get("price") is not None else None,
        fee=float(order.get("commission", 0.0) or 0.0),
        label=str(order.get("label", "")),
    )


def parse_position(payload: dict[str, Any]) -> DeribitPosition:
    return DeribitPosition(
        instrument=str(payload.get("instrument_name", "")),
        size=float(payload.get("size", 0.0) or 0.0),
        average_price=(
            float(payload["average_price"])
            if payload.get("average_price") is not None
            else None
        ),
        mark_price=(
            float(payload["mark_price"])
            if payload.get("mark_price") is not None
            else None
        ),
        delta=float(payload["delta"]) if payload.get("delta") is not None else None,
        kind=str(payload.get("kind", "")),
    )


def parse_contract(instrument: str) -> DeribitContract | None:
    parts = _instrument_parts(instrument)
    if parts is None:
        return None
    underlying, expiry, strike, option_type = parts
    return DeribitContract(
        instrument=instrument,
        underlying=underlying,
        expiry=expiry,
        strike=strike,
        option_type=option_type,
    )


def inverse_intrinsic_coin(
    option_type: Literal["call", "put"],
    strike: float,
    settlement_price: float,
) -> float:
    """Intrinsic value of one inverse Deribit option contract, in coin.

    Deribit's BTC/ETH options settle in the underlying coin. The USD payoff is
    divided by the settlement index price, so a $10,000 payoff at an $110,000
    index is about 0.0909 BTC per contract.
    """
    if settlement_price <= 0 or strike <= 0:
        return 0.0
    if option_type == "call":
        return max(0.0, settlement_price - strike) / settlement_price
    return max(0.0, strike - settlement_price) / settlement_price


def reconcile_positions(
    local: dict[str, float],
    remote: list[DeribitPosition],
) -> dict[str, Any]:
    """Compare local instrument quantities with the venue's positions."""
    remote_map = {position.instrument: position.size for position in remote}
    instruments = sorted(set(local) | set(remote_map))
    differences = {
        instrument: {
            "local": local.get(instrument, 0.0),
            "remote": remote_map.get(instrument, 0.0),
            "delta": local.get(instrument, 0.0) - remote_map.get(instrument, 0.0),
        }
        for instrument in instruments
        if abs(local.get(instrument, 0.0) - remote_map.get(instrument, 0.0)) > 1e-9
    }
    return {
        "ok": not differences,
        "local_instruments": len(local),
        "remote_instruments": len(remote_map),
        "differences": differences,
    }


class DeribitExecutionClient:
    """Minimal authenticated Deribit options client.

    This is an execution primitive, not a strategy runner. It is testnet by
    default and refuses live orders by default.
    """

    def __init__(
        self,
        *,
        environment: str = "testnet",
        client_id: str | None = None,
        client_secret: str | None = None,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
        allow_live: bool = False,
    ):
        if environment not in ENVIRONMENTS:
            raise ValueError(f"unknown Deribit environment: {environment}")
        if environment == "live" and not (
            allow_live and os.getenv("LIVE_TRADING") == "YES"
        ):
            raise PermissionError(
                "live Deribit orders require allow_live=True and LIVE_TRADING=YES"
            )
        self.environment = environment
        self.base_url = ENVIRONMENTS[environment]
        self.client_id = client_id or os.getenv("DERIBIT_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("DERIBIT_CLIENT_SECRET")
        self.timeout = timeout
        self._client = client
        self._owns_client = client is None
        self._token: str | None = None
        self._request_id = 0

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()

    def __enter__(self) -> DeribitExecutionClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _rpc(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        auth: bool = False,
    ) -> Any:
        if auth and not self._token:
            self.authenticate()
        self._request_id += 1
        headers: dict[str, str] = {}
        if auth:
            headers["Authorization"] = f"Bearer {self._token}"
        response = self.client.post(
            self.base_url,
            json={
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": params or {},
            },
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise DeribitAPIError(method, None, "non-object response")
        error = payload.get("error")
        if isinstance(error, dict):
            raise DeribitAPIError(
                method,
                int(error.get("code") or 0),
                str(error.get("message") or "unknown error"),
            )
        if "result" not in payload:
            raise DeribitAPIError(method, None, "missing result")
        return payload["result"]

    def authenticate(self) -> str:
        if not self.client_id or not self.client_secret:
            raise PermissionError(
                "Deribit credentials missing; set DERIBIT_CLIENT_ID and "
                "DERIBIT_CLIENT_SECRET"
            )
        result = self._rpc(
            "public/auth",
            {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        token = result.get("access_token") if isinstance(result, dict) else None
        if not token:
            raise DeribitAPIError("public/auth", None, "missing access_token")
        self._token = str(token)
        return self._token

    def account_summary(self, currency: str = "BTC") -> dict[str, Any]:
        result = self._rpc(
            "private/get_account_summary",
            {"currency": currency, "extended": True},
            auth=True,
        )
        return result if isinstance(result, dict) else {}

    def positions(self, currency: str = "BTC") -> list[DeribitPosition]:
        result = self._rpc(
            "private/get_positions",
            {"currency": currency, "kind": "option"},
            auth=True,
        )
        if not isinstance(result, list):
            raise DeribitAPIError("private/get_positions", None, "missing list")
        return [parse_position(item) for item in result if isinstance(item, dict)]

    def open_orders(self, currency: str = "BTC") -> list[dict[str, Any]]:
        result = self._rpc(
            "private/get_open_orders_by_currency",
            {"currency": currency, "kind": "option"},
            auth=True,
        )
        return result if isinstance(result, list) else []

    def order_state(self, order_id: str) -> DeribitOrderResult:
        result = self._rpc(
            "private/get_order_state",
            {"order_id": order_id},
            auth=True,
        )
        if not isinstance(result, dict):
            raise DeribitAPIError("private/get_order_state", None, "missing order")
        return parse_order(result)

    def place_order(self, request: DeribitOrderRequest) -> DeribitOrderResult:
        if self.environment != "testnet":
            raise PermissionError(
                "live order submission is disabled in this adapter; use a "
                "separate, reviewed live execution layer"
            )
        if request.amount <= 0:
            raise ValueError("amount must be positive")
        if request.side == "sell" and not request.reduce_only:
            raise PermissionError("sell orders must be reduce_only")
        if request.order_type == "limit" and request.price is None:
            raise ValueError("limit orders require price")
        method = "private/buy" if request.side == "buy" else "private/sell"
        params: dict[str, Any] = {
            "instrument_name": request.instrument,
            "amount": request.amount,
            "type": request.order_type,
        }
        if request.price is not None:
            params["price"] = request.price
        if request.label:
            params["label"] = request.label
        if request.post_only:
            params["post_only"] = True
        if request.reduce_only:
            params["reduce_only"] = True
        result = self._rpc(method, params, auth=True)
        if not isinstance(result, dict):
            raise DeribitAPIError(method, None, "missing order result")
        return parse_order(result)

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        result = self._rpc(
            "private/cancel",
            {"order_id": order_id},
            auth=True,
        )
        return result if isinstance(result, dict) else {}


def utc_now() -> datetime:
    return datetime.now(UTC)
