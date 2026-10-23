from __future__ import annotations

from tradingbot.execution.broker import Account, OrderRequest, OrderResult, Position
from tradingbot.execution.manager import OrderManager, ReconciliationError
from tradingbot.execution.paper import PaperBroker
from tradingbot.execution.state import OrderStateStore


class PartialBroker:
    def __init__(self, keep_open: bool = True) -> None:
        self.submits = 0
        self.keep_open = keep_open
        self.result = OrderResult(
            "b1", "BTC", "buy", 10.0, "accepted", 4.0, 100.0, client_order_id="tb-1"
        )
        self.orders: dict[str, OrderResult] = {"tb-1": self.result}

    def get_account(self) -> Account:
        return Account(10_000, 10_000, 10_000)

    def get_positions(self) -> dict[str, Position]:
        return {}

    def get_prices(self, assets: list[str]) -> dict[str, float]:
        return {"BTC": 100.0}

    def submit_order(self, order: OrderRequest) -> OrderResult:
        self.submits += 1
        cid = order.client_order_id or ""
        if cid == "tb-1":
            result = self.result
        else:
            result = OrderResult(
                f"b{self.submits}",
                order.asset,
                order.side,
                order.qty,
                "filled",
                order.qty,
                100.0,
                client_order_id=cid,
            )
        self.orders[cid] = result
        return result

    def get_order(self, client_order_id: str, asset: str | None = None) -> OrderResult | None:
        return self.orders.get(client_order_id)

    def list_open_orders(self) -> list[OrderResult]:
        return [self.result] if self.keep_open else []

    def cancel_all(self) -> None:
        return None

    def flatten(self) -> None:
        return None


def test_manager_full_fill_and_idempotence(tmp_path) -> None:
    broker = PaperBroker(cash=1000, prices={"BTC": 100.0})
    state = OrderStateStore(tmp_path / "state.sqlite")
    manager = OrderManager(broker, state, poll_attempts=1, poll_interval=0.0)
    request = OrderRequest("BTC", "buy", 1.0, client_order_id="tb-1", reference_price=100.0)
    first = manager.execute([request])
    assert len(first) == 1
    assert first[0].status == "filled"
    assert state.get("tb-1").status == "FILLED"
    second = manager.execute([request])
    assert second == []
    assert len(broker.fills) == 1


def test_manager_partial_fill_does_not_resubmit_while_open(tmp_path) -> None:
    broker = PartialBroker(keep_open=True)
    state = OrderStateStore(tmp_path / "state.sqlite")
    manager = OrderManager(broker, state, poll_attempts=1, poll_interval=0.0)
    request = OrderRequest("BTC", "buy", 10.0, client_order_id="tb-1", reference_price=100.0)
    first = manager.execute([request])
    assert first[0].filled_qty == 4.0
    assert state.get("tb-1").status == "PARTIAL"
    manager.execute([request])
    assert broker.submits == 1


def test_manager_completes_terminal_partial(tmp_path) -> None:
    broker = PartialBroker(keep_open=False)
    state = OrderStateStore(tmp_path / "state.sqlite")
    manager = OrderManager(broker, state, poll_attempts=1, poll_interval=0.0)
    request = OrderRequest("BTC", "buy", 10.0, client_order_id="tb-1", reference_price=100.0)
    results = manager.execute([request])
    assert broker.submits == 2
    assert any(result.client_order_id == "tb-1-r1" for result in results)
    assert state.get("tb-1-r1").status == "FILLED"


def test_manager_slices_large_order(tmp_path) -> None:
    broker = PaperBroker(cash=10_000, prices={"BTC": 100.0})
    state = OrderStateStore(tmp_path / "state.sqlite")
    manager = OrderManager(
        broker,
        state,
        poll_attempts=1,
        poll_interval=0.0,
        max_child_notional=300.0,
        max_children=5,
    )
    request = OrderRequest("BTC", "buy", 10.0, client_order_id="tb-slice", reference_price=100.0)
    results = manager.execute([request])
    assert len(results) == 4
    assert len(broker.fills) == 4
    assert all(result.status == "filled" for result in results)


def test_reconcile_untracked_open_order(tmp_path) -> None:
    broker = PartialBroker()
    broker.list_open_orders = lambda: [
        OrderResult("b2", "ETH", "buy", 1.0, "accepted", client_order_id="ghost")
    ]
    state = OrderStateStore(tmp_path / "state.sqlite")
    manager = OrderManager(broker, state, poll_attempts=1, poll_interval=0.0)
    try:
        manager.assert_reconciled()
    except ReconciliationError:
        pass
    else:
        raise AssertionError("expected reconciliation failure")
