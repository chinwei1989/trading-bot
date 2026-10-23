"""Broker abstractions shared by paper and live execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass
class Account:
    equity: float
    cash: float
    buying_power: float


@dataclass
class Position:
    asset: str
    qty: float
    market_value: float
    avg_entry_price: float


@dataclass
class OrderRequest:
    asset: str
    side: Literal["buy", "sell"]
    qty: float
    order_type: Literal["market", "limit"] = "market"
    limit_price: float | None = None
    client_order_id: str | None = None
    reference_price: float | None = None


@dataclass
class OrderResult:
    order_id: str
    asset: str
    side: str
    qty: float
    status: str
    filled_qty: float = 0.0
    avg_price: float | None = None
    message: str = ""
    client_order_id: str | None = None


class Broker(Protocol):
    def get_account(self) -> Account: ...
    def get_positions(self) -> dict[str, Position]: ...
    def get_prices(self, assets: list[str]) -> dict[str, float]: ...
    def submit_order(self, order: OrderRequest) -> OrderResult: ...
    def get_order(self, client_order_id: str, asset: str | None = None) -> OrderResult | None: ...
    def list_open_orders(self) -> list[OrderResult]: ...
    def cancel_all(self) -> None: ...
    def flatten(self) -> None: ...
