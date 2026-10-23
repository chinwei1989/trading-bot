"""Order state machine, idempotent submission, and startup reconciliation."""

from __future__ import annotations

import math
import time
from typing import Literal, cast

from tradingbot.execution.broker import Broker, OrderRequest, OrderResult
from tradingbot.execution.orders import OrderJournal
from tradingbot.execution.state import OPEN_STATUSES, OrderIntent, OrderStateStore


class ReconciliationError(RuntimeError):
    """Raised when broker/order state cannot be reconciled safely."""


class OrderManager:
    def __init__(
        self,
        broker: Broker,
        state: OrderStateStore,
        journal: OrderJournal | None = None,
        *,
        poll_attempts: int = 20,
        poll_interval: float = 0.5,
        complete_partials: bool = True,
        max_partial_retries: int = 2,
        max_child_notional: float | None = None,
        max_children: int = 5,
    ):
        self.broker = broker
        self.state = state
        self.journal = journal
        self.poll_attempts = poll_attempts
        self.poll_interval = poll_interval
        self.complete_partials = complete_partials
        self.max_partial_retries = max_partial_retries
        self.max_child_notional = max_child_notional
        self.max_children = max(1, max_children)

    def reconcile_startup(self) -> list[str]:
        """Resolve previously open intents and detect untracked open orders."""
        issues: list[str] = []
        for intent in self.state.open_intents():
            result = self.broker.get_order(intent.client_order_id, intent.asset)
            if result is not None:
                updated = self.state.apply_result(intent, result)
                if self.journal:
                    self.journal.record(
                        result, intent.client_order_id, intent.reference_price
                    )
                if updated.status in OPEN_STATUSES and updated.status not in (
                    "NEW",
                    "PARTIAL",
                ):
                    issues.append(
                        f"intent {intent.client_order_id} still {updated.status}"
                    )
            elif intent.status in ("SUBMITTED", "ACKNOWLEDGED", "PARTIAL", "UNKNOWN"):
                issues.append(
                    f"intent {intent.client_order_id} is {intent.status} but not found at broker"
                )

        tracked = {i.client_order_id for i in self.state.all()}
        for order in self.broker.list_open_orders():
            cid = order.client_order_id
            if not cid or cid not in tracked:
                issues.append(
                    f"untracked open broker order {order.order_id} {order.asset}"
                )
        return issues

    def assert_reconciled(self) -> None:
        issues = self.reconcile_startup()
        if issues:
            raise ReconciliationError("; ".join(issues))
        self.complete_open_partials()

    def complete_open_partials(self) -> list[OrderResult]:
        """Complete terminal partial fills whose broker order is no longer open."""
        if not self.complete_partials:
            return []
        open_ids = {
            order.client_order_id
            for order in self.broker.list_open_orders()
            if order.client_order_id
        }
        results: list[OrderResult] = []
        for intent in self.state.open_intents():
            if intent.status != "PARTIAL" or intent.client_order_id in open_ids:
                continue
            result = self.broker.get_order(intent.client_order_id, intent.asset)
            if result is not None:
                intent = self.state.apply_result(intent, result)
            if intent.status == "PARTIAL":
                results.extend(self._complete_remaining(intent))
        return results

    def _slice_order(self, order: OrderRequest) -> list[OrderRequest]:
        if not self.max_child_notional or not order.client_order_id:
            return [order]
        price = order.limit_price or order.reference_price
        if not price or price <= 0:
            return [order]
        notional = order.qty * price
        if notional <= self.max_child_notional:
            return [order]
        count = min(
            self.max_children,
            max(2, math.ceil(notional / self.max_child_notional)),
        )
        child_qty = order.qty / count
        children: list[OrderRequest] = []
        remaining = order.qty
        for index in range(count):
            qty = child_qty if index < count - 1 else remaining
            remaining -= qty
            children.append(
                OrderRequest(
                    asset=order.asset,
                    side=order.side,
                    qty=qty,
                    order_type=order.order_type,
                    limit_price=order.limit_price,
                    client_order_id=f"{order.client_order_id}-s{index + 1}",
                    reference_price=order.reference_price,
                )
            )
        return children

    def _complete_remaining(self, intent: OrderIntent) -> list[OrderResult]:
        open_ids = {
            order.client_order_id
            for order in self.broker.list_open_orders()
            if order.client_order_id
        }
        if intent.client_order_id in open_ids:
            return []
        remaining = float(intent.qty) - float(intent.filled_qty)
        if remaining <= 1e-9:
            return []
        suffix = "-r"
        retries = intent.client_order_id.count(suffix)
        if retries >= self.max_partial_retries:
            self.state.update(
                intent.client_order_id,
                last_error="partial remainder not completed: retry limit reached",
            )
            return []
        child_id = f"{intent.client_order_id}{suffix}{retries + 1}"
        child = OrderRequest(
            asset=intent.asset,
            side="buy" if intent.side == "buy" else "sell",
            qty=remaining,
            order_type=cast(Literal["market", "limit"], intent.order_type),
            limit_price=intent.limit_price,
            client_order_id=child_id,
            reference_price=intent.reference_price,
        )
        return self.execute([child])

    def execute(self, orders: list[OrderRequest]) -> list[OrderResult]:
        results: list[OrderResult] = []
        sliced: list[OrderRequest] = []
        for order in orders:
            sliced.extend(self._slice_order(order))
        for order in sliced:
            cid = order.client_order_id
            if not cid:
                raise ValueError("orders must have client_order_id")
            intent = self.state.get(cid)
            if intent is None:
                intent = self.state.create(order)
            if intent.status == "FILLED":
                continue
            if intent.status in ("CANCELED", "REJECTED"):
                continue
            if intent.status in ("SUBMITTED", "ACKNOWLEDGED", "PARTIAL", "UNKNOWN"):
                existing = self.broker.get_order(cid, order.asset)
                if existing is None:
                    raise ReconciliationError(
                        f"open intent {cid} not found; refusing to resubmit"
                    )
                updated = self.state.apply_result(intent, existing)
                if self.journal:
                    self.journal.record(existing, cid, intent.reference_price)
                results.append(existing)
                if updated.status == "PARTIAL":
                    results.extend(self._complete_remaining(updated))
                    continue
                if updated.status in ("SUBMITTED", "ACKNOWLEDGED"):
                    continue
                if updated.status in ("FILLED", "REJECTED", "CANCELED"):
                    continue

            self.state.update(
                cid,
                status="SUBMITTED",
                attempts=intent.attempts + 1,
                last_error=None,
            )
            try:
                result = self.broker.submit_order(order)
            except Exception as exc:
                self.state.update(cid, status="UNKNOWN", last_error=f"{type(exc).__name__}: {exc}")
                raise
            result = self._poll(cid, order.asset, result)
            updated = self.state.apply_result(intent, result)
            if self.journal:
                self.journal.record(result, cid, intent.reference_price)
            results.append(result)
            if updated.status == "PARTIAL":
                results.extend(self._complete_remaining(updated))
            if updated.status == "REJECTED":
                continue
        return results

    def _poll(self, client_order_id: str, asset: str, result: OrderResult) -> OrderResult:
        if any(word in result.status.lower() for word in ("filled", "reject", "cancel")):
            return result
        for _ in range(self.poll_attempts):
            time.sleep(self.poll_interval)
            latest = self.broker.get_order(client_order_id, asset)
            if latest is None:
                return result
            result = latest
            if any(
                word in result.status.lower()
                for word in ("filled", "reject", "cancel", "partial")
            ):
                break
        return result
