from __future__ import annotations

import pytest

from tradingbot.config import AppConfig
from tradingbot.execution.factory import build_broker
from tradingbot.execution.paper import PaperBroker


def test_build_paper_broker() -> None:
    broker = build_broker(AppConfig())
    assert isinstance(broker, PaperBroker)


def test_alpaca_requires_keys(monkeypatch) -> None:
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    config = AppConfig()
    config.broker.name = "alpaca"
    with pytest.raises(RuntimeError):
        build_broker(config)
