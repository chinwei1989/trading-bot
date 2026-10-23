from __future__ import annotations

from tradingbot.execution.broker import OrderRequest, OrderResult
from tradingbot.execution.state import OrderStateStore


def test_state_roundtrip(tmp_path) -> None:
    store = OrderStateStore(tmp_path / "state.sqlite")
    order = OrderRequest("BTC", "buy", 1.5, client_order_id="tb-1", reference_price=100.0)
    intent = store.create(order)
    assert intent.status == "NEW"
    assert intent.asset == "BTC"

    updated = store.update("tb-1", status="SUBMITTED", attempts=1)
    assert updated.status == "SUBMITTED"
    result = OrderResult("b1", "BTC", "buy", 1.5, "filled", 1.5, 101.0, client_order_id="tb-1")
    final = store.apply_result(updated, result)
    assert final.status == "FILLED"
    assert final.filled_qty == 1.5
    store.close()
