"""Order planning, execution, journaling, and reconciliation."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import polars as pl

from tradingbot.execution.broker import Broker, OrderRequest, OrderResult, Position


def latest_weights(weights: pl.DataFrame) -> pl.DataFrame:
    if weights.is_empty():
        return weights
    ts = weights["timestamp"].max()
    return (
        weights.filter(pl.col("timestamp") == ts)
        .group_by("asset")
        .agg(pl.col("weight").sum())
        .with_columns(pl.lit(ts).alias("timestamp"))
        .select(["timestamp", "asset", "weight"])
    )


def _client_id(date: str, asset: str, side: str, qty: float) -> str:
    raw = f"{date}|{asset}|{side}|{qty:.10f}".encode()
    return "tb-" + hashlib.sha1(raw).hexdigest()[:16]


def plan_orders(
    target_weights: pl.DataFrame,
    equity: float,
    prices: dict[str, float],
    positions: dict[str, Position],
    *,
    min_notional: float = 10.0,
    allow_short: bool = False,
) -> list[OrderRequest]:
    latest = latest_weights(target_weights)
    if latest.is_empty():
        return []
    date = str(latest["timestamp"].max())[:10]
    target_map = {r["asset"]: float(r["weight"]) for r in latest.iter_rows(named=True)}
    assets = sorted(set(target_map) | set(positions))
    orders: list[OrderRequest] = []
    for asset in assets:
        price = prices.get(asset)
        if not price or price <= 0:
            continue
        weight = target_map.get(asset, 0.0)
        if not allow_short:
            weight = max(0.0, weight)
        target_value = weight * equity
        current_pos = positions.get(asset)
        current_qty = current_pos.qty if current_pos else 0.0
        current_value = current_qty * price
        delta = target_value - current_value
        if abs(delta) < min_notional:
            continue
        side: Literal["buy", "sell"] = "buy" if delta > 0 else "sell"
        qty = abs(delta) / price
        if side == "sell" and not allow_short:
            qty = min(qty, max(0.0, current_qty))
        if qty <= 0:
            continue
        orders.append(
            OrderRequest(
                asset=asset,
                side=side,
                qty=round(qty, 10),
                client_order_id=_client_id(date, asset, side, qty),
                reference_price=price,
            )
        )
    return sorted(orders, key=lambda o: o.asset)


class OrderJournal:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                ts TEXT NOT NULL,
                client_order_id TEXT,
                asset TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL NOT NULL,
                status TEXT NOT NULL,
                filled_qty REAL,
                avg_price REAL,
                message TEXT,
                reference_price REAL
            )
            """
        )
        cols = [row[1] for row in self.conn.execute("PRAGMA table_info(orders)")]
        if "reference_price" not in cols:
            self.conn.execute("ALTER TABLE orders ADD COLUMN reference_price REAL")
        self.conn.commit()

    def record(
        self,
        result: OrderResult,
        client_order_id: str | None = None,
        reference_price: float | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO orders
            (id, ts, client_order_id, asset, side, qty, status,
             filled_qty, avg_price, message, reference_price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.order_id,
                datetime.now(UTC).isoformat(),
                client_order_id,
                result.asset,
                result.side,
                result.qty,
                result.status,
                result.filled_qty,
                result.avg_price,
                result.message,
                reference_price,
            ),
        )
        self.conn.commit()

    def recent(self, limit: int = 50) -> list[dict[str, object]]:
        rows = self.conn.execute(
            "SELECT * FROM orders ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        cols = [d[0] for d in self.conn.execute("SELECT * FROM orders LIMIT 0").description]
        return [dict(zip(cols, row, strict=True)) for row in rows]

    def close(self) -> None:
        self.conn.close()


def execute_orders(
    broker: Broker,
    orders: list[OrderRequest],
    journal: OrderJournal | None = None,
) -> list[OrderResult]:
    results: list[OrderResult] = []
    for order in orders:
        result = broker.submit_order(order)
        results.append(result)
        if journal:
            journal.record(result, order.client_order_id, order.reference_price)
    return results


def reconcile(
    target_weights: pl.DataFrame,
    equity: float,
    prices: dict[str, float],
    positions: dict[str, Position],
) -> pl.DataFrame:
    latest = latest_weights(target_weights)
    rows: list[dict[str, object]] = []
    assets = set(latest["asset"].to_list()) if not latest.is_empty() else set()
    assets.update(positions)
    target_map = (
        {r["asset"]: float(r["weight"]) for r in latest.iter_rows(named=True)}
        if not latest.is_empty()
        else {}
    )
    for asset in sorted(assets):
        price = prices.get(asset, 0.0)
        target_weight = target_map.get(asset, 0.0)
        target_value = target_weight * equity
        current_pos = positions.get(asset)
        current_value = current_pos.qty * price if current_pos else 0.0
        drift = current_value - target_value
        rows.append(
            {
                "asset": asset,
                "target_weight": target_weight,
                "target_value": target_value,
                "current_value": current_value,
                "drift_value": drift,
                "drift_pct": drift / equity if equity else 0.0,
            }
        )
    return pl.DataFrame(rows).sort("asset")
