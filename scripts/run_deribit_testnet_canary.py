"""Scheduled Deribit testnet canary.

Modes:
- ``cycle``: reconcile, clear stale canary orders, place one far-from-market
  testnet order, cancel it, and reconcile back to flat.
- ``open-only``: place one order and exit, leaving it open for a two-process
  restart test.
- ``recover-only``: start a fresh process, reconcile, cancel tracked open
  canary orders, and verify the account is flat.

This script is testnet-only. It never uses a live endpoint or a live order path.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from tradingbot.options.deribit_execution import (
    DeribitExecutionClient,
    DeribitOrderRequest,
)
from tradingbot.options.deribit_testnet import (
    CanaryGuard,
    CanaryLimits,
    ReconciliationReport,
    StoredOrder,
    TestnetExecutor,
    TestnetOrderStore,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / "artifacts" / "ai_options_30m" / "testnet_canary.sqlite"
REPORT_DIR = ROOT / "artifacts" / "ai_options_30m" / "testnet_canary"
BASE = "https://test.deribit.com/api/v2"


def _reconciliation(report: ReconciliationReport) -> dict[str, Any]:
    return {
        "ok": report.ok,
        "issues": list(report.issues),
        "open_orders": [order.client_order_id for order in report.open_orders],
        "resolved_orders": [order.client_order_id for order in report.resolved],
        "local_positions": report.local_positions,
        "remote_positions": [
            {"instrument": position.instrument, "size": position.size}
            for position in report.remote_positions
        ],
        "position_differences": report.position_differences,
    }


def _order(order: StoredOrder) -> dict[str, Any]:
    return {
        "client_order_id": order.client_order_id,
        "instrument": order.instrument,
        "side": order.side,
        "amount": order.amount,
        "price": order.price,
        "status": order.status,
        "filled_amount": order.filled_amount,
        "average_price": order.average_price,
        "venue_order_id": order.venue_order_id,
    }


def _select_option() -> dict[str, Any]:
    with httpx.Client(timeout=30.0) as http:
        instruments_response = http.get(
            BASE + "/public/get_instruments",
            params={"currency": "BTC", "kind": "option", "expired": "false"},
        )
        instruments_response.raise_for_status()
        instruments = instruments_response.json().get("result") or []
        books_response = http.get(
            BASE + "/public/get_book_summary_by_currency",
            params={"currency": "BTC", "kind": "option"},
        )
        books_response.raise_for_status()
        books = {
            row.get("instrument_name"): row
            for row in (books_response.json().get("result") or [])
            if isinstance(row, dict)
        }

    cutoff = datetime.now(UTC) + timedelta(days=3)
    candidates: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for item in instruments:
        name = str(item.get("instrument_name") or "")
        expiry_ms = item.get("expiration_timestamp")
        book = books.get(name)
        if not name or not expiry_ms or not book:
            continue
        if datetime.fromtimestamp(float(expiry_ms) / 1000.0, tz=UTC) <= cutoff:
            continue
        if float(item.get("min_trade_amount") or 0.0) > 1.0:
            continue
        tick = float(item.get("tick_size") or 0.0)
        bid = float(book.get("bid_price") or 0.0)
        ask = float(book.get("ask_price") or 0.0)
        volume = float(book.get("volume") or 0.0)
        if tick <= 0 or bid <= 0 or ask <= bid or volume <= 0 or ask > 0.01:
            continue
        spread = (ask - bid) / ask
        if spread > 0.35:
            continue
        candidates.append((spread, item, book))

    if not candidates:
        raise RuntimeError("no suitable testnet option found")
    candidates.sort(key=lambda item: item[0])
    spread, instrument, book = candidates[0]
    return {
        "instrument": instrument["instrument_name"],
        "tick": float(instrument["tick_size"]),
        "bid": float(book["bid_price"]),
        "ask": float(book["ask_price"]),
        "spread": spread,
    }


def _write_report(report: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    lines = [
        "# Deribit testnet canary",
        "",
        f"Generated: `{report['generated_at']}`",
        f"Mode: `{report['mode']}`",
        f"Status: **{'PASS' if report['ok'] else 'FAIL'}**",
        "",
    ]
    if report.get("selected"):
        lines.append(f"Instrument: `{report['selected']['instrument']}`")
    if report.get("order"):
        order = report["order"]
        lines.append(
            f"Order: `{order['client_order_id']}` {order['status']} "
            f"{order['amount']} @ {order['price']}"
        )
    lines.extend(
        [
            "",
            f"Issues: {len(report.get('issues', []))}",
        ]
    )
    for issue in report.get("issues", []):
        lines.append(f"- {issue}")
    lines.append("")
    (REPORT_DIR / "latest.md").write_text("\n".join(lines), encoding="utf-8")


def _cancel_open_orders(
    executor: TestnetExecutor,
    report: ReconciliationReport,
) -> list[str]:
    cancelled: list[str] = []
    for order in report.open_orders:
        executor.cancel(order.client_order_id)
        cancelled.append(order.client_order_id)
    return cancelled


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("cycle", "open-only", "recover-only"),
        default="cycle",
    )
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    args = parser.parse_args()

    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": args.mode,
        "ok": False,
        "issues": [],
        "selected": None,
        "order": None,
        "cancelled": [],
    }
    store = TestnetOrderStore(args.state)
    client = DeribitExecutionClient(environment="testnet")
    executor = TestnetExecutor(
        client,
        store,
        CanaryGuard(
            CanaryLimits(
                max_contracts=1,
                max_premium_coin=0.01,
                max_open_orders=1,
                max_orders_per_day=10,
            )
        ),
        poll_attempts=3,
        poll_interval=0.2,
    )
    try:
        initial = executor.reconcile_startup()
        report["initial_reconcile"] = _reconciliation(initial)
        if not initial.ok:
            report["issues"].extend(initial.issues)
            raise RuntimeError("initial reconciliation is not clean")
        if initial.local_positions:
            report["issues"].append("testnet account has nonzero option positions")
            raise RuntimeError("account is not flat before canary")

        if args.mode == "recover-only":
            report["cancelled"] = _cancel_open_orders(executor, initial)
            final = executor.reconcile_startup()
            report["final_reconcile"] = _reconciliation(final)
            if not final.ok:
                report["issues"].extend(final.issues)
            if final.open_orders:
                report["issues"].append("open orders remain after recovery")
            if final.local_positions:
                report["issues"].append("positions remain after recovery")
            report["ok"] = final.ok and not final.open_orders and not final.local_positions
            return 0 if report["ok"] else 1

        if initial.open_orders and args.mode == "cycle":
            report["cancelled"] = _cancel_open_orders(executor, initial)
            after_cleanup = executor.reconcile_startup()
            if not after_cleanup.ok or after_cleanup.open_orders:
                report["issues"].extend(after_cleanup.issues)
                report["issues"].append("stale canary orders could not be cleared")
                raise RuntimeError("could not clear stale canary orders")

        if args.mode == "open-only" and initial.open_orders:
            report["issues"].append("open-only requires a flat starting state")
            raise RuntimeError("cannot open a restart-test order while one is open")

        selected = _select_option()
        report["selected"] = selected
        request = DeribitOrderRequest(
            instrument=selected["instrument"],
            side="buy",
            amount=1,
            order_type="limit",
            price=selected["tick"],
            label="",
            post_only=True,
        )
        result = executor.submit(
            request,
            idempotency_key=f"canary-{args.mode}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}",
            wait=False,
        )
        report["order"] = _order(result.order)
        if result.order.status != "OPEN":
            report["issues"].append(
                f"canary order ended in unexpected state {result.order.status}"
            )
            raise RuntimeError("canary order did not remain open")

        if args.mode == "open-only":
            report["ok"] = True
            return 0

        cancelled = executor.cancel(result.order.client_order_id)
        report["cancelled"].append(cancelled.client_order_id)
        final = executor.reconcile_startup()
        report["final_reconcile"] = _reconciliation(final)
        if not final.ok:
            report["issues"].extend(final.issues)
        if final.open_orders:
            report["issues"].append("open orders remain after cycle")
        if final.local_positions:
            report["issues"].append("positions remain after cycle")
        report["ok"] = final.ok and not final.open_orders and not final.local_positions
        return 0 if report["ok"] else 1
    except Exception as exc:
        report["issues"].append(f"{type(exc).__name__}: {exc}")
        return 1
    finally:
        try:
            final = executor.reconcile_startup()
            report["final_reconcile"] = _reconciliation(final)
        except Exception as exc:
            report["issues"].append(f"final reconciliation failed: {exc}")
        _write_report(report)
        client.close()
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
