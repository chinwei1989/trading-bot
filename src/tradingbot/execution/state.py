"""Persistent order-intent state."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from tradingbot.execution.broker import OrderRequest, OrderResult

Status = Literal[
    "NEW",
    "SUBMITTED",
    "ACKNOWLEDGED",
    "PARTIAL",
    "FILLED",
    "CANCELED",
    "REJECTED",
    "UNKNOWN",
]
OPEN_STATUSES = ("NEW", "SUBMITTED", "ACKNOWLEDGED", "PARTIAL", "UNKNOWN")
TERMINAL = ("FILLED", "CANCELED", "REJECTED")


@dataclass
class OrderIntent:
    client_order_id: str
    asset: str
    side: str
    qty: float
    order_type: str
    limit_price: float | None
    reference_price: float | None
    status: str
    filled_qty: float = 0.0
    avg_price: float | None = None
    broker_order_id: str | None = None
    attempts: int = 0
    last_error: str | None = None
    created_at: str = ""
    updated_at: str = ""


class OrderStateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS order_intents (
                client_order_id TEXT PRIMARY KEY,
                asset TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL NOT NULL,
                order_type TEXT NOT NULL,
                limit_price REAL,
                reference_price REAL,
                status TEXT NOT NULL,
                filled_qty REAL NOT NULL DEFAULT 0,
                avg_price REAL,
                broker_order_id TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def create(self, order: OrderRequest) -> OrderIntent:
        cid = order.client_order_id or ""
        if not cid:
            raise ValueError("order.client_order_id is required for persistent state")
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO order_intents
            (client_order_id, asset, side, qty, order_type, limit_price,
             reference_price, status, filled_qty, avg_price, broker_order_id,
             attempts, last_error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'NEW', 0, NULL, NULL, 0, NULL, ?, ?)
            """,
            (
                cid,
                order.asset,
                order.side,
                order.qty,
                order.order_type,
                order.limit_price,
                order.reference_price,
                now,
                now,
            ),
        )
        self.conn.commit()
        intent = self.get(cid)
        if intent is None:
            raise RuntimeError(f"failed to create order intent {cid}")
        return intent

    def get(self, client_order_id: str) -> OrderIntent | None:
        row = self.conn.execute(
            "SELECT * FROM order_intents WHERE client_order_id = ?", (client_order_id,)
        ).fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self.conn.execute("SELECT * FROM order_intents LIMIT 0").description]
        return OrderIntent(**dict(zip(cols, row, strict=True)))

    def update(self, client_order_id: str, **fields: object) -> OrderIntent:
        allowed = {
            "status",
            "filled_qty",
            "avg_price",
            "broker_order_id",
            "attempts",
            "last_error",
        }
        clean = {k: v for k, v in fields.items() if k in allowed}
        if clean:
            clean["updated_at"] = datetime.now(UTC).isoformat()
            assignments = ", ".join(f"{k} = ?" for k in clean)
            self.conn.execute(
                f"UPDATE order_intents SET {assignments} WHERE client_order_id = ?",
                (*clean.values(), client_order_id),
            )
            self.conn.commit()
        intent = self.get(client_order_id)
        if intent is None:
            raise KeyError(client_order_id)
        return intent

    def open_intents(self) -> list[OrderIntent]:
        rows = self.conn.execute(
            f"SELECT * FROM order_intents WHERE status IN ({','.join('?' * len(OPEN_STATUSES))})",
            OPEN_STATUSES,
        ).fetchall()
        cols = [d[0] for d in self.conn.execute("SELECT * FROM order_intents LIMIT 0").description]
        return [OrderIntent(**dict(zip(cols, row, strict=True))) for row in rows]

    def all(self) -> list[OrderIntent]:
        rows = self.conn.execute("SELECT * FROM order_intents ORDER BY created_at").fetchall()
        cols = [d[0] for d in self.conn.execute("SELECT * FROM order_intents LIMIT 0").description]
        return [OrderIntent(**dict(zip(cols, row, strict=True))) for row in rows]

    def apply_result(self, intent: OrderIntent, result: OrderResult) -> OrderIntent:
        status = _map_status(result.status, result.filled_qty, intent.qty)
        return self.update(
            intent.client_order_id,
            status=status,
            filled_qty=result.filled_qty,
            avg_price=result.avg_price,
            broker_order_id=result.order_id or intent.broker_order_id,
            last_error=result.message or None,
        )

    def close(self) -> None:
        self.conn.close()


def _map_status(status: str, filled_qty: float, qty: float) -> str:
    s = status.lower()
    if "filled" in s:
        return "FILLED" if filled_qty >= qty - 1e-9 else "PARTIAL"
    if "partial" in s or (0 < filled_qty < qty):
        return "PARTIAL"
    if "reject" in s or "cancel" in s or "expired" in s:
        return "REJECTED" if "reject" in s else "CANCELED"
    if "accept" in s or "new" in s or "open" in s or "submitted" in s:
        return "ACKNOWLEDGED"
    return "UNKNOWN"
