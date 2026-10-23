from __future__ import annotations

import pytest

from tradingbot.execution.broker import OrderRequest
from tradingbot.execution.paper import PaperBroker


def test_buy_sell_accounting() -> None:
    broker = PaperBroker(cash=1000.0, prices={"BTC": 100.0})
    result = broker.submit_order(OrderRequest("BTC", "buy", 1.0))
    assert result.status == "filled"
    assert broker.cash == 900.0
    assert broker.get_positions()["BTC"].qty == 1.0

    result = broker.submit_order(OrderRequest("BTC", "sell", 0.5))
    assert result.status == "filled"
    assert broker.cash == 950.0
    assert broker.get_positions()["BTC"].qty == 0.5


def test_reject_insufficient_cash() -> None:
    broker = PaperBroker(cash=100.0, prices={"BTC": 100.0})
    result = broker.submit_order(OrderRequest("BTC", "buy", 2.0))
    assert result.status == "rejected"
    assert broker.cash == 100.0


def test_reject_short_when_disabled() -> None:
    broker = PaperBroker(cash=100.0, prices={"BTC": 100.0})
    result = broker.submit_order(OrderRequest("BTC", "sell", 1.0))
    assert result.status == "rejected"


def test_allow_short_creates_negative_position() -> None:
    broker = PaperBroker(cash=100.0, prices={"BTC": 100.0}, allow_short=True)
    result = broker.submit_order(OrderRequest("BTC", "sell", 0.5))
    assert result.status == "filled"
    assert broker.get_positions()["BTC"].qty == -0.5
    assert broker.cash == 150.0


def test_state_roundtrip(tmp_path) -> None:
    broker = PaperBroker(cash=1000.0, prices={"BTC": 100.0})
    broker.submit_order(OrderRequest("BTC", "buy", 1.0))
    path = tmp_path / "state.json"
    broker.save_state(path)

    restored = PaperBroker(cash=0.0, prices={"BTC": 100.0})
    assert restored.load_state(path)
    assert restored.cash == pytest.approx(900.0)
    assert restored.get_positions()["BTC"].qty == pytest.approx(1.0)
    assert restored.get_account().equity == pytest.approx(1000.0)


def test_slippage_and_commission() -> None:
    broker = PaperBroker(
        cash=1000.0,
        prices={"BTC": 100.0},
        commission_bps=10,
        slippage_bps=10,
    )
    broker.submit_order(OrderRequest("BTC", "buy", 1.0))
    # 100 * 1.001 * 1.001 = 100.2001
    assert broker.cash == pytest.approx(1000.0 - 100.2001)
