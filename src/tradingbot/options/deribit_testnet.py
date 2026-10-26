"""Persistent, restart-safe Deribit testnet execution state.

This module sits on top of :class:`DeribitExecutionClient`. It is deliberately
testnet-only and does not provide a live order path.

The key properties are:

- an order intent is written before submission;
- idempotency keys prevent duplicate submissions;
- a canary guard limits contract count, premium, open orders, and daily orders;
- remote order state is persisted as orders and aggregate fills;
- startup reconciliation adopts open orders by label and compares positions.

Aggregate fills are recorded when the venue reports a higher ``filled_amount``.
Individual exchange trade records are not fetched here.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from tradingbot.options.deribit import _instrument_parts
from tradingbot.options.deribit_execution import (
    DeribitExecutionClient,
    DeribitOrderRequest,
    DeribitOrderResult,
    DeribitPosition,
    reconcile_positions,
)

OrderStatus = Literal[
    "NEW",
    "SUBMITTED",
    "OPEN",
    "PARTIAL",
    "FILLED",
    "CANCELLED",
    "REJECTED",
    "UNKNOWN",
]
OPEN_STATUSES: tuple[str, ...] = (
    "NEW",
    "SUBMITTED",
    "OPEN",
    "PARTIAL",
    "UNKNOWN",
)
TERMINAL_STATUSES: tuple[str, ...] = ("FILLED", "CANCELLED", "REJECTED")


@dataclass(frozen=True)
class StoredOrder:
    client_order_id: str
    idempotency_key: str
    environment: str
    instrument: str
    underlying: str
    side: str
    amount: float
    order_type: str
    price: float | None
    reduce_only: bool
    label: str
    status: str
    filled_amount: float
    average_price: float | None
    fee: float
    venue_order_id: str | None
    last_error: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class FillRecord:
    client_order_id: str
    instrument: str
    side: str
    amount: float
    average_price: float | None
    recorded_at: str


@dataclass(frozen=True)
class CanaryLimits:
    max_contracts: float = 1.0
    max_premium_coin: float = 0.01
    max_open_orders: int = 1
    max_orders_per_day: int = 10
    allowed_underlyings: tuple[str, ...] = ("BTC", "ETH")
    min_dte: int = 1
    max_dte: int = 365


@dataclass(frozen=True)
class CanaryDecision:
    allowed: bool
    reasons: tuple[str, ...] = ()
    summary: str = ""


@dataclass(frozen=True)
class ExecutionReport:
    order: StoredOrder
    duplicate: bool
    decision: CanaryDecision
    remote: DeribitOrderResult | None = None


@dataclass(frozen=True)
class ReconciliationReport:
    ok: bool
    issues: tuple[str, ...]
    resolved: tuple[StoredOrder, ...]
    open_orders: tuple[StoredOrder, ...]
    local_positions: dict[str, float]
    remote_positions: tuple[DeribitPosition, ...]
    position_differences: dict[str, dict[str, float]]


class CanaryRejected(RuntimeError):
    """Raised when a testnet order violates the canary policy."""

    def __init__(self, decision: CanaryDecision):
        self.decision = decision
        super().__init__("; ".join(decision.reasons) or "canary rejected order")


class TestnetExecutionError(RuntimeError):
    """Operational error in the persistent testnet execution layer."""


def make_idempotency_key(request: DeribitOrderRequest) -> str:
    """Build a deterministic key for an order request."""
    raw = "|".join(
        [
            request.instrument,
            request.side,
            str(request.amount),
            request.order_type,
            str(request.price),
            str(request.reduce_only),
        ]
    )
    return "tb-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def make_client_order_id(idempotency_key: str) -> str:
    return "tb-" + hashlib.sha1(idempotency_key.encode("utf-8")).hexdigest()[:24]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _map_remote_status(remote: DeribitOrderResult) -> str:
    state = remote.state.lower()
    if remote.filled_amount > 0 and state != "filled":
        return "PARTIAL"
    if state == "filled" or (
        remote.amount > 0 and remote.filled_amount >= remote.amount - 1e-9
    ):
        return "FILLED"
    if state in {"cancelled", "canceled"}:
        return "CANCELLED"
    if state == "rejected":
        return "REJECTED"
    if state in {"open", "new", "triggered"}:
        return "OPEN"
    return "UNKNOWN"


class TestnetOrderStore:
    """SQLite-backed order, event, fill, and position state for testnet."""

    __test__ = False

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS testnet_orders (
                client_order_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                environment TEXT NOT NULL,
                instrument TEXT NOT NULL,
                underlying TEXT NOT NULL,
                side TEXT NOT NULL,
                amount REAL NOT NULL,
                order_type TEXT NOT NULL,
                price REAL,
                reduce_only INTEGER NOT NULL,
                label TEXT NOT NULL,
                status TEXT NOT NULL,
                filled_amount REAL NOT NULL DEFAULT 0,
                average_price REAL,
                fee REAL NOT NULL DEFAULT 0,
                venue_order_id TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS testnet_order_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_order_id TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                status TEXT NOT NULL,
                filled_amount REAL NOT NULL,
                average_price REAL,
                detail TEXT
            );

            CREATE TABLE IF NOT EXISTS testnet_fills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_order_id TEXT NOT NULL,
                instrument TEXT NOT NULL,
                side TEXT NOT NULL,
                amount REAL NOT NULL,
                average_price REAL,
                recorded_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_testnet_orders_status
                ON testnet_orders(status);
            CREATE INDEX IF NOT EXISTS idx_testnet_orders_created
                ON testnet_orders(created_at);
            """
        )
        self.conn.commit()

    def create_order(
        self,
        request: DeribitOrderRequest,
        *,
        client_order_id: str,
        idempotency_key: str,
        environment: str,
    ) -> StoredOrder:
        parsed = _instrument_parts(request.instrument)
        if parsed is None:
            raise ValueError(f"invalid option instrument: {request.instrument}")
        underlying = parsed[0]
        now = _now_iso()
        try:
            self.conn.execute(
                """
                INSERT INTO testnet_orders
                (client_order_id, idempotency_key, environment, instrument,
                 underlying, side, amount, order_type, price, reduce_only,
                 label, status, filled_amount, average_price, fee,
                 venue_order_id, last_error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'NEW', 0, NULL, 0,
                        NULL, NULL, ?, ?)
                """,
                (
                    client_order_id,
                    idempotency_key,
                    environment,
                    request.instrument,
                    underlying,
                    request.side,
                    float(request.amount),
                    request.order_type,
                    request.price,
                    int(request.reduce_only),
                    request.label or client_order_id,
                    now,
                    now,
                ),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            existing = self.get_by_idempotency(idempotency_key)
            if existing is not None:
                return existing
            raise
        self._record_event(
            client_order_id,
            status="NEW",
            filled_amount=0.0,
            average_price=None,
            detail="intent persisted before submission",
        )
        order = self.get(client_order_id)
        if order is None:
            raise TestnetExecutionError("order was not persisted")
        return order

    def get(self, client_order_id: str) -> StoredOrder | None:
        row = self.conn.execute(
            "SELECT * FROM testnet_orders WHERE client_order_id = ?",
            (client_order_id,),
        ).fetchone()
        return self._from_row(row) if row else None

    def get_by_idempotency(self, idempotency_key: str) -> StoredOrder | None:
        row = self.conn.execute(
            "SELECT * FROM testnet_orders WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        return self._from_row(row) if row else None

    def update_order(
        self,
        client_order_id: str,
        *,
        status: str | None = None,
        filled_amount: float | None = None,
        average_price: float | None = None,
        fee: float | None = None,
        venue_order_id: str | None = None,
        last_error: str | None = None,
    ) -> StoredOrder:
        current = self.get(client_order_id)
        if current is None:
            raise KeyError(client_order_id)
        new_filled = (
            float(filled_amount) if filled_amount is not None else current.filled_amount
        )
        if new_filled < current.filled_amount - 1e-9:
            raise TestnetExecutionError(
                f"filled amount moved backwards for {client_order_id}: "
                f"{current.filled_amount} -> {new_filled}"
            )
        changes: dict[str, Any] = {
            "updated_at": _now_iso(),
            "last_error": last_error,
        }
        if status is not None:
            changes["status"] = status
        if filled_amount is not None:
            changes["filled_amount"] = new_filled
        if average_price is not None:
            changes["average_price"] = average_price
        if fee is not None:
            changes["fee"] = fee
        if venue_order_id is not None:
            changes["venue_order_id"] = venue_order_id
        assignments = ", ".join(f"{key} = ?" for key in changes)
        self.conn.execute(
            f"UPDATE testnet_orders SET {assignments} WHERE client_order_id = ?",
            (*changes.values(), client_order_id),
        )
        fill_delta = new_filled - current.filled_amount
        if fill_delta > 1e-9:
            self.conn.execute(
                """
                INSERT INTO testnet_fills
                (client_order_id, instrument, side, amount, average_price,
                 recorded_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    client_order_id,
                    current.instrument,
                    current.side,
                    fill_delta,
                    average_price if average_price is not None else current.average_price,
                    _now_iso(),
                ),
            )
        self.conn.commit()
        updated = self.get(client_order_id)
        if updated is None:
            raise TestnetExecutionError("order disappeared after update")
        self._record_event(
            client_order_id,
            status=updated.status,
            filled_amount=updated.filled_amount,
            average_price=updated.average_price,
            detail=last_error or "remote state update",
        )
        return updated

    def update_from_remote(
        self,
        client_order_id: str,
        remote: DeribitOrderResult,
    ) -> StoredOrder:
        current = self.get(client_order_id)
        if current is None:
            raise KeyError(client_order_id)
        return self.update_order(
            client_order_id,
            status=_map_remote_status(remote),
            filled_amount=remote.filled_amount,
            average_price=(
                remote.average_price
                if remote.average_price is not None
                else current.average_price
            ),
            fee=remote.fee,
            venue_order_id=remote.order_id or current.venue_order_id,
            last_error=None,
        )

    def mark_unknown(self, client_order_id: str, message: str) -> StoredOrder:
        return self.update_order(
            client_order_id,
            status="UNKNOWN",
            last_error=message[:500],
        )

    def open_orders(self) -> list[StoredOrder]:
        placeholders = ", ".join("?" for _ in OPEN_STATUSES)
        rows = self.conn.execute(
            f"SELECT * FROM testnet_orders WHERE status IN ({placeholders}) "
            "ORDER BY created_at",
            OPEN_STATUSES,
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def all(self) -> list[StoredOrder]:
        rows = self.conn.execute(
            "SELECT * FROM testnet_orders ORDER BY created_at"
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def positions(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for order in self.all():
            if abs(order.filled_amount) <= 1e-9:
                continue
            sign = 1.0 if order.side == "buy" else -1.0
            totals[order.instrument] = (
                totals.get(order.instrument, 0.0) + sign * order.filled_amount
            )
        return {
            instrument: amount
            for instrument, amount in totals.items()
            if abs(amount) > 1e-9
        }

    def count_created_on(self, day: date) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM testnet_orders WHERE created_at LIKE ?",
            (f"{day.isoformat()}%",),
        ).fetchone()
        return int(row[0]) if row else 0

    def events(self, client_order_id: str | None = None) -> list[dict[str, Any]]:
        if client_order_id is None:
            rows = self.conn.execute(
                "SELECT * FROM testnet_order_events ORDER BY id"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM testnet_order_events WHERE client_order_id = ? "
                "ORDER BY id",
                (client_order_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def fills(self) -> list[FillRecord]:
        rows = self.conn.execute(
            "SELECT * FROM testnet_fills ORDER BY id"
        ).fetchall()
        return [
            FillRecord(
                client_order_id=str(row["client_order_id"]),
                instrument=str(row["instrument"]),
                side=str(row["side"]),
                amount=float(row["amount"]),
                average_price=(
                    float(row["average_price"])
                    if row["average_price"] is not None
                    else None
                ),
                recorded_at=str(row["recorded_at"]),
            )
            for row in rows
        ]

    def close(self) -> None:
        self.conn.close()

    def _record_event(
        self,
        client_order_id: str,
        *,
        status: str,
        filled_amount: float,
        average_price: float | None,
        detail: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO testnet_order_events
            (client_order_id, recorded_at, status, filled_amount,
             average_price, detail)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                client_order_id,
                _now_iso(),
                status,
                filled_amount,
                average_price,
                detail,
            ),
        )
        self.conn.commit()

    @staticmethod
    def _from_row(row: sqlite3.Row) -> StoredOrder:
        return StoredOrder(
            client_order_id=str(row["client_order_id"]),
            idempotency_key=str(row["idempotency_key"]),
            environment=str(row["environment"]),
            instrument=str(row["instrument"]),
            underlying=str(row["underlying"]),
            side=str(row["side"]),
            amount=float(row["amount"]),
            order_type=str(row["order_type"]),
            price=float(row["price"]) if row["price"] is not None else None,
            reduce_only=bool(row["reduce_only"]),
            label=str(row["label"]),
            status=str(row["status"]),
            filled_amount=float(row["filled_amount"]),
            average_price=(
                float(row["average_price"])
                if row["average_price"] is not None
                else None
            ),
            fee=float(row["fee"]),
            venue_order_id=(
                str(row["venue_order_id"])
                if row["venue_order_id"] is not None
                else None
            ),
            last_error=(
                str(row["last_error"]) if row["last_error"] is not None else None
            ),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


class CanaryGuard:
    """Strict testnet-only canary policy checked before submission."""

    def __init__(
        self,
        limits: CanaryLimits | None = None,
        *,
        kill_switch_path: str | Path | None = None,
    ):
        self.limits = limits or CanaryLimits()
        self.kill_switch_path = (
            Path(kill_switch_path) if kill_switch_path is not None else None
        )

    def check(
        self,
        request: DeribitOrderRequest,
        *,
        store: TestnetOrderStore,
        environment: str,
        now: datetime | None = None,
    ) -> CanaryDecision:
        limits = self.limits
        now = now or datetime.now(UTC)
        reasons: list[str] = []
        is_close = request.side == "sell" and request.reduce_only
        parsed = _instrument_parts(request.instrument)
        if environment != "testnet":
            reasons.append("canary is testnet-only")
        if parsed is None:
            reasons.append("invalid option instrument")
            return CanaryDecision(False, tuple(reasons), "blocked")
        underlying, expiry, _strike, _option_type = parsed
        if underlying not in limits.allowed_underlyings:
            reasons.append(f"underlying {underlying} is not allowed")
        dte = (expiry - now.date()).days
        if dte < limits.min_dte:
            reasons.append(f"DTE {dte} below canary minimum {limits.min_dte}")
        if dte > limits.max_dte:
            reasons.append(f"DTE {dte} above canary maximum {limits.max_dte}")
        if request.amount <= 0:
            reasons.append("amount must be positive")
        if request.amount > limits.max_contracts:
            reasons.append(
                f"amount {request.amount} above canary maximum {limits.max_contracts}"
            )
        if request.order_type != "limit":
            reasons.append("canary only permits limit orders")
        if request.price is None or request.price <= 0:
            reasons.append("a positive limit price is required")
        elif not is_close and request.price * request.amount > limits.max_premium_coin:
            reasons.append(
                f"premium {request.price * request.amount:.6f} above canary "
                f"maximum {limits.max_premium_coin:.6f}"
            )
        if request.side == "sell" and not request.reduce_only:
            reasons.append("sell orders must be reduce_only")
        if request.side not in {"buy", "sell"}:
            reasons.append("side must be buy or sell")
        if self.kill_switch_path and self.kill_switch_path.exists():
            reasons.append(f"kill switch is active: {self.kill_switch_path}")
        # Closing an existing long is risk-reducing, so premium/open/daily caps
        # must not prevent an exit. The adapter still requires reduce_only.
        if not is_close:
            open_orders = store.open_orders()
            if len(open_orders) >= limits.max_open_orders:
                reasons.append(
                    f"max open orders reached "
                    f"({len(open_orders)}/{limits.max_open_orders})"
                )
            if any(order.instrument == request.instrument for order in open_orders):
                reasons.append(f"active order already exists for {request.instrument}")
            daily_orders = store.count_created_on(now.date())
            if daily_orders >= limits.max_orders_per_day:
                reasons.append(
                    f"daily order limit reached "
                    f"({daily_orders}/{limits.max_orders_per_day})"
                )
        return CanaryDecision(
            allowed=not reasons,
            reasons=tuple(reasons),
            summary="allowed" if not reasons else "blocked by canary guard",
        )


class TestnetExecutor:
    """Persistent canary executor for Deribit testnet options."""

    __test__ = False

    def __init__(
        self,
        client: DeribitExecutionClient,
        store: TestnetOrderStore,
        guard: CanaryGuard | None = None,
        *,
        poll_attempts: int = 10,
        poll_interval: float = 0.35,
    ):
        if client.environment != "testnet":
            raise PermissionError("TestnetExecutor refuses non-testnet clients")
        self.client = client
        self.store = store
        self.guard = guard or CanaryGuard()
        self.poll_attempts = poll_attempts
        self.poll_interval = poll_interval

    def submit(
        self,
        request: DeribitOrderRequest,
        *,
        idempotency_key: str | None = None,
        client_order_id: str | None = None,
        wait: bool = True,
    ) -> ExecutionReport:
        key = idempotency_key or make_idempotency_key(request)
        existing = self.store.get_by_idempotency(key)
        if existing is not None:
            return ExecutionReport(
                order=existing,
                duplicate=True,
                decision=CanaryDecision(True, ("idempotent replay",), "replay"),
            )
        decision = self.guard.check(
            request,
            store=self.store,
            environment=self.client.environment,
        )
        if not decision.allowed:
            raise CanaryRejected(decision)

        cid = client_order_id or make_client_order_id(key)
        if self.store.get(cid) is not None:
            raise TestnetExecutionError(f"client order id already exists: {cid}")
        labelled = replace(request, label=cid)
        self.store.create_order(
            labelled,
            client_order_id=cid,
            idempotency_key=key,
            environment=self.client.environment,
        )
        try:
            remote = self.client.place_order(labelled)
        except Exception as exc:
            self.store.mark_unknown(cid, f"{type(exc).__name__}: {exc}")
            raise
        order = self.store.update_from_remote(cid, remote)
        if wait and order.status not in TERMINAL_STATUSES:
            order = self._poll(cid)
        return ExecutionReport(
            order=order,
            duplicate=False,
            decision=decision,
            remote=remote,
        )

    def refresh(self, client_order_id: str) -> StoredOrder:
        order = self.store.get(client_order_id)
        if order is None:
            raise KeyError(client_order_id)
        if not order.venue_order_id:
            raise TestnetExecutionError("order has no venue order id")
        remote = self.client.order_state(order.venue_order_id)
        return self.store.update_from_remote(client_order_id, remote)

    def cancel(self, client_order_id: str) -> StoredOrder:
        order = self.store.get(client_order_id)
        if order is None:
            raise KeyError(client_order_id)
        if not order.venue_order_id:
            raise TestnetExecutionError("order has no venue order id")
        self.client.cancel_order(order.venue_order_id)
        remote = self.client.order_state(order.venue_order_id)
        return self.store.update_from_remote(client_order_id, remote)

    def reconcile_startup(
        self,
        currencies: tuple[str, ...] = ("BTC", "ETH"),
    ) -> ReconciliationReport:
        issues: list[str] = []
        resolved: list[StoredOrder] = []
        all_local = self.store.all()
        tracked_labels = {order.client_order_id for order in all_local}
        tracked_labels.update(order.label for order in all_local if order.label)
        tracked_venues = {
            order.venue_order_id for order in all_local if order.venue_order_id
        }

        remote_open: list[dict[str, Any]] = []
        for currency in self._currencies(currencies):
            try:
                remote_open.extend(self.client.open_orders(currency))
            except Exception as exc:
                issues.append(f"open-order lookup failed for {currency}: {exc}")
        remote_labels = {
            str(raw.get("label")): raw
            for raw in remote_open
            if raw.get("label")
        }

        for local in self.store.open_orders():
            if not local.venue_order_id:
                raw = remote_labels.get(local.client_order_id) or remote_labels.get(
                    local.label
                )
                if raw is None:
                    issues.append(
                        f"local order {local.client_order_id} has no venue id and "
                        "is not open at the venue"
                    )
                    continue
                venue_id = str(raw.get("order_id") or "")
                if not venue_id:
                    issues.append(
                        f"local order {local.client_order_id} matched an open order "
                        "without an order id"
                    )
                    continue
                local = self.store.update_order(
                    local.client_order_id,
                    venue_order_id=venue_id,
                    status="OPEN",
                    last_error=None,
                )
            try:
                remote = self.client.order_state(str(local.venue_order_id))
            except Exception as exc:
                issues.append(
                    f"could not refresh {local.client_order_id}: "
                    f"{type(exc).__name__}: {exc}"
                )
                continue
            resolved.append(self.store.update_from_remote(local.client_order_id, remote))

        for raw in remote_open:
            label = str(raw.get("label") or "")
            if not label or label not in tracked_labels:
                oid = str(raw.get("order_id") or "unknown")
                issues.append(f"untracked venue order {oid} label={label or '(none)'}")
            elif str(raw.get("order_id") or "") not in tracked_venues:
                tracked_venues.add(str(raw.get("order_id") or ""))

        local_positions = self.store.positions()
        remote_positions: list[DeribitPosition] = []
        for currency in self._currencies(currencies):
            try:
                remote_positions.extend(self.client.positions(currency))
            except Exception as exc:
                issues.append(f"position lookup failed for {currency}: {exc}")
        remote_positions = [
            position for position in remote_positions if abs(position.size) > 1e-9
        ]
        comparison = reconcile_positions(local_positions, remote_positions)
        if not comparison["ok"]:
            issues.append("local and remote option positions differ")

        return ReconciliationReport(
            ok=not issues,
            issues=tuple(issues),
            resolved=tuple(resolved),
            open_orders=tuple(self.store.open_orders()),
            local_positions=local_positions,
            remote_positions=tuple(remote_positions),
            position_differences=comparison["differences"],
        )

    def _poll(self, client_order_id: str) -> StoredOrder:
        order = self.store.get(client_order_id)
        if order is None:
            raise KeyError(client_order_id)
        for _ in range(self.poll_attempts):
            if order.status in TERMINAL_STATUSES:
                return order
            time.sleep(self.poll_interval)
            remote = self.client.order_state(str(order.venue_order_id))
            order = self.store.update_from_remote(client_order_id, remote)
        return order

    def _currencies(self, preferred: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            sorted({order.underlying for order in self.store.all()} | set(preferred))
        )


__all__ = [
    "OPEN_STATUSES",
    "TERMINAL_STATUSES",
    "CanaryDecision",
    "CanaryGuard",
    "CanaryLimits",
    "CanaryRejected",
    "ExecutionReport",
    "FillRecord",
    "ReconciliationReport",
    "StoredOrder",
    "TestnetExecutionError",
    "TestnetExecutor",
    "TestnetOrderStore",
    "make_client_order_id",
    "make_idempotency_key",
]
