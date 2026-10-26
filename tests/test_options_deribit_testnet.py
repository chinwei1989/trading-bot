from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tradingbot.options.deribit_execution import (
    DeribitOrderRequest,
    DeribitOrderResult,
    DeribitPosition,
)
from tradingbot.options.deribit_testnet import (
    CanaryGuard,
    CanaryLimits,
    CanaryRejected,
    TestnetExecutor,
    TestnetOrderStore,
    make_idempotency_key,
)

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
INSTRUMENT = "BTC-27NOV26-110000-C"


def request(**overrides: Any) -> DeribitOrderRequest:
    values: dict[str, Any] = {
        "instrument": INSTRUMENT,
        "side": "buy",
        "amount": 1,
        "order_type": "limit",
        "price": 0.0001,
        "label": "",
    }
    values.update(overrides)
    return DeribitOrderRequest(**values)


class FakeClient:
    environment = "testnet"

    def __init__(self) -> None:
        self.orders: dict[str, DeribitOrderResult] = {}
        self.calls: list[DeribitOrderRequest] = []
        self.fake_positions: list[DeribitPosition] = []
        self.extra_open: list[dict[str, Any]] = []
        self.fail_next = False
        self._next = 1

    def place_order(self, order: DeribitOrderRequest) -> DeribitOrderResult:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("simulated venue timeout")
        self.calls.append(order)
        oid = f"venue-{self._next}"
        self._next += 1
        result = DeribitOrderResult(
            order_id=oid,
            instrument=order.instrument,
            side=order.side,
            state="open",
            amount=float(order.amount),
            filled_amount=0.0,
            average_price=None,
            price=order.price,
            fee=0.0,
            label=order.label,
        )
        self.orders[oid] = result
        return result

    def order_state(self, order_id: str) -> DeribitOrderResult:
        return self.orders[order_id]

    def open_orders(self, currency: str = "BTC") -> list[dict[str, Any]]:
        rows = [
            {
                "order_id": order.order_id,
                "label": order.label,
                "instrument_name": order.instrument,
                "direction": order.side,
                "order_state": order.state,
                "amount": order.amount,
                "filled_amount": order.filled_amount,
                "average_price": order.average_price,
            }
            for order in self.orders.values()
            if order.state == "open" and order.instrument.startswith(currency + "-")
        ]
        return rows + [
            row
            for row in self.extra_open
            if str(row.get("instrument_name", "")).startswith(currency + "-")
        ]

    def positions(self, currency: str = "BTC") -> list[DeribitPosition]:
        return [
            position
            for position in self.fake_positions
            if position.instrument.startswith(currency + "-")
        ]

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        self.orders[order_id] = replace(self.orders[order_id], state="cancelled")
        return {"order_id": order_id}

    def fill_order(self, order_id: str, price: float) -> None:
        old = self.orders[order_id]
        self.orders[order_id] = replace(
            old,
            state="filled",
            filled_amount=old.amount,
            average_price=price,
        )

    def close(self) -> None:
        pass


@pytest.fixture
def store(tmp_path: Path) -> TestnetOrderStore:
    value = TestnetOrderStore(tmp_path / "testnet.sqlite")
    yield value
    value.close()


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


def test_canary_guard_blocks_unsafe_requests(store: TestnetOrderStore, tmp_path: Path) -> None:
    kill = tmp_path / "KILL"
    guard = CanaryGuard(
        CanaryLimits(max_contracts=1, max_premium_coin=0.01, max_open_orders=1),
        kill_switch_path=kill,
    )
    assert guard.check(request(), store=store, environment="testnet", now=NOW).allowed
    assert not guard.check(
        request(amount=2), store=store, environment="testnet", now=NOW
    ).allowed
    assert not guard.check(
        request(order_type="market"), store=store, environment="testnet", now=NOW
    ).allowed
    assert not guard.check(
        request(side="sell"), store=store, environment="testnet", now=NOW
    ).allowed
    assert guard.check(
        request(side="sell", reduce_only=True, price=1.0),
        store=store,
        environment="testnet",
        now=NOW,
    ).allowed
    assert not guard.check(
        request(instrument="SOL-27NOV26-100-C"),
        store=store,
        environment="testnet",
        now=NOW,
    ).allowed
    assert not guard.check(
        request(), store=store, environment="live", now=NOW
    ).allowed
    kill.write_text("stop", encoding="utf-8")
    assert not guard.check(
        request(), store=store, environment="testnet", now=NOW
    ).allowed


def test_idempotent_submit_does_not_place_twice(
    store: TestnetOrderStore, client: FakeClient
) -> None:
    executor = TestnetExecutor(client, store, poll_attempts=1, poll_interval=0)
    first = executor.submit(request(), idempotency_key="same-key", wait=False)
    second = executor.submit(request(), idempotency_key="same-key", wait=False)
    assert not first.duplicate
    assert second.duplicate
    assert second.order.client_order_id == first.order.client_order_id
    assert len(client.calls) == 1
    assert len(store.all()) == 1


def test_active_order_blocks_a_different_order(
    store: TestnetOrderStore, client: FakeClient
) -> None:
    executor = TestnetExecutor(client, store, poll_attempts=1, poll_interval=0)
    executor.submit(request(), idempotency_key="first", wait=False)
    with pytest.raises(CanaryRejected, match=r"max open orders|active order"):
        executor.submit(request(), idempotency_key="second", wait=False)
    assert len(client.calls) == 1


def test_restart_reconciles_persistent_open_order(
    tmp_path: Path, client: FakeClient
) -> None:
    path = tmp_path / "restart.sqlite"
    first_store = TestnetOrderStore(path)
    first = TestnetExecutor(client, first_store, poll_attempts=1, poll_interval=0)
    report = first.submit(request(), idempotency_key="restart-key", wait=False)
    old_id = report.order.client_order_id
    first_store.close()

    second_store = TestnetOrderStore(path)
    second = TestnetExecutor(client, second_store, poll_attempts=1, poll_interval=0)
    restored = second.reconcile_startup()
    assert restored.ok
    assert len(restored.resolved) == 1
    assert restored.resolved[0].client_order_id == old_id
    assert restored.open_orders[0].status == "OPEN"
    duplicate = second.submit(request(), idempotency_key="restart-key", wait=False)
    assert duplicate.duplicate
    assert len(client.calls) == 1
    second_store.close()


def test_fill_is_persisted_and_reconciled(
    store: TestnetOrderStore, client: FakeClient
) -> None:
    executor = TestnetExecutor(client, store, poll_attempts=1, poll_interval=0)
    submitted = executor.submit(request(), idempotency_key="fill-key", wait=False)
    order_id = submitted.order.client_order_id
    assert submitted.order.venue_order_id
    client.fill_order(submitted.order.venue_order_id, 0.0002)
    client.fake_positions = [
        DeribitPosition(
            instrument=INSTRUMENT,
            size=1.0,
            average_price=0.0002,
            mark_price=0.0002,
            delta=0.5,
            kind="option",
        )
    ]
    refreshed = executor.refresh(order_id)
    assert refreshed.status == "FILLED"
    assert refreshed.filled_amount == 1
    assert len(store.fills()) == 1
    assert store.positions() == {INSTRUMENT: 1.0}
    reconciled = executor.reconcile_startup()
    assert reconciled.ok
    assert reconciled.local_positions == {INSTRUMENT: 1.0}
    assert not reconciled.position_differences


def test_untracked_remote_order_is_reported(
    store: TestnetOrderStore, client: FakeClient
) -> None:
    client.extra_open = [
        {
            "order_id": "untracked-1",
            "label": "not-in-store",
            "instrument_name": INSTRUMENT,
            "order_state": "open",
            "amount": 1,
        }
    ]
    report = TestnetExecutor(client, store).reconcile_startup()
    assert not report.ok
    assert any("untracked" in issue for issue in report.issues)


def test_failed_submission_is_unknown_and_never_resubmitted(
    store: TestnetOrderStore, client: FakeClient
) -> None:
    client.fail_next = True
    executor = TestnetExecutor(client, store, poll_attempts=1, poll_interval=0)
    with pytest.raises(RuntimeError, match="timeout"):
        executor.submit(request(), idempotency_key="unknown-key", wait=False)
    orders = store.all()
    assert len(orders) == 1
    assert orders[0].status == "UNKNOWN"
    assert orders[0].last_error
    duplicate = executor.submit(request(), idempotency_key="unknown-key", wait=False)
    assert duplicate.duplicate
    assert len(client.calls) == 0


def test_non_testnet_client_is_refused(store: TestnetOrderStore) -> None:
    client = FakeClient()
    client.environment = "live"
    with pytest.raises(PermissionError, match="testnet"):
        TestnetExecutor(client, store)  # type: ignore[arg-type]


def test_idempotency_key_is_stable() -> None:
    assert make_idempotency_key(request()) == make_idempotency_key(request())
    assert make_idempotency_key(request()) != make_idempotency_key(request(price=0.0002))
