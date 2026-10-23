"""Deterministic in-memory paper broker for simulation and tests."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Literal

from tradingbot.execution.broker import Account, OrderRequest, OrderResult, Position


class PaperBroker:
    def __init__(
        self,
        cash: float = 10_000.0,
        prices: dict[str, float] | None = None,
        *,
        commission_bps: float = 0.0,
        slippage_bps: float = 0.0,
        allow_short: bool = False,
    ):
        self.cash = float(cash)
        self.initial_cash = float(cash)
        self.prices = dict(prices or {})
        self.commission_bps = commission_bps
        self.slippage_bps = slippage_bps
        self.allow_short = allow_short
        self.positions: dict[str, Position] = {}
        self.fills: list[OrderResult] = []
        self.order_results: dict[str, OrderResult] = {}

    def set_prices(self, prices: dict[str, float]) -> None:
        self.prices.update({k: float(v) for k, v in prices.items() if v and v > 0})

    def get_account(self) -> Account:
        equity = self.cash + sum(
            pos.qty * self.prices.get(asset, pos.avg_entry_price)
            for asset, pos in self.positions.items()
        )
        return Account(equity=equity, cash=self.cash, buying_power=self.cash)

    def get_positions(self) -> dict[str, Position]:
        out: dict[str, Position] = {}
        for asset, pos in self.positions.items():
            price = self.prices.get(asset, pos.avg_entry_price)
            out[asset] = replace(pos, market_value=pos.qty * price)
        return out

    def get_prices(self, assets: list[str]) -> dict[str, float]:
        return {a: self.prices[a] for a in assets if a in self.prices}

    def _exec_price(self, price: float, side: str) -> float:
        slip = self.slippage_bps / 10_000.0
        return price * (1.0 + slip) if side == "buy" else price * (1.0 - slip)

    def submit_order(self, order: OrderRequest) -> OrderResult:
        if order.qty <= 0:
            return OrderResult(
                uuid.uuid4().hex[:12], order.asset, order.side, order.qty, "rejected",
                message="qty must be positive",
            )
        price = self.prices.get(order.asset)
        if price is None or price <= 0:
            return OrderResult(
                uuid.uuid4().hex[:12], order.asset, order.side, order.qty, "rejected",
                message=f"no price for {order.asset}",
            )
        exec_price = self._exec_price(float(price), order.side)
        commission = self.commission_bps / 10_000.0

        if order.side == "buy":
            cost = order.qty * exec_price * (1.0 + commission)
            if cost > self.cash + 1e-9:
                return OrderResult(
                    uuid.uuid4().hex[:12], order.asset, order.side, order.qty, "rejected",
                    message=f"insufficient cash: need {cost:.2f}, have {self.cash:.2f}",
                )
            self.cash -= cost
            current = self.positions.get(order.asset)
            if current:
                new_qty = current.qty + order.qty
                avg = (
                    (current.qty * current.avg_entry_price + order.qty * exec_price) / new_qty
                    if new_qty > 0
                    else 0.0
                )
                self.positions[order.asset] = Position(order.asset, new_qty, new_qty * price, avg)
            else:
                self.positions[order.asset] = Position(
                    order.asset, order.qty, order.qty * price, exec_price
                )
        else:
            current = self.positions.get(order.asset)
            held = current.qty if current else 0.0
            if order.qty > held + 1e-9 and not self.allow_short:
                return OrderResult(
                    uuid.uuid4().hex[:12], order.asset, order.side, order.qty, "rejected",
                    message=f"insufficient position: sell {order.qty}, held {held}",
                )
            self.cash += order.qty * exec_price * (1.0 - commission)
            new_qty = held - order.qty
            if current:
                if abs(new_qty) < 1e-12:
                    self.positions.pop(order.asset, None)
                else:
                    self.positions[order.asset] = Position(
                        order.asset, new_qty, new_qty * price, current.avg_entry_price
                    )
            else:
                self.positions[order.asset] = Position(
                    order.asset, -order.qty, -order.qty * price, exec_price
                )

        result = OrderResult(
            order_id=uuid.uuid4().hex[:12],
            asset=order.asset,
            side=order.side,
            qty=order.qty,
            status="filled",
            filled_qty=order.qty,
            avg_price=exec_price,
            client_order_id=order.client_order_id,
        )
        self.fills.append(result)
        if order.client_order_id:
            self.order_results[order.client_order_id] = result
        self.order_results[result.order_id] = result
        return result

    def get_order(
        self, client_order_id: str, asset: str | None = None
    ) -> OrderResult | None:
        return self.order_results.get(client_order_id)

    def list_open_orders(self) -> list[OrderResult]:
        return []

    def save_state(self, path: str | Path) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cash": self.cash,
            "initial_cash": self.initial_cash,
            "positions": {
                asset: {"qty": pos.qty, "avg_entry_price": pos.avg_entry_price}
                for asset, pos in self.positions.items()
            },
        }
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return out

    def load_state(self, path: str | Path) -> bool:
        state_path = Path(path)
        if not state_path.exists():
            return False
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        self.cash = float(payload["cash"])
        self.initial_cash = float(payload.get("initial_cash", self.cash))
        self.positions = {
            asset: Position(
                asset=asset,
                qty=float(pos["qty"]),
                market_value=0.0,
                avg_entry_price=float(pos["avg_entry_price"]),
            )
            for asset, pos in payload.get("positions", {}).items()
        }
        return True

    def cancel_all(self) -> None:
        return None

    def flatten(self) -> None:
        for asset, pos in list(self.positions.items()):
            side: Literal["buy", "sell"] = "sell" if pos.qty > 0 else "buy"
            self.submit_order(OrderRequest(asset, side, abs(pos.qty)))
