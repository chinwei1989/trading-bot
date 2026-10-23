from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from tradingbot.config import DataConfig, load_config

ROOT = Path(__file__).resolve().parents[1]


def test_load_base_config() -> None:
    config = load_config(ROOT / "config" / "base.yaml")
    assert config.strategy.name == "trend"
    assert len(config.data.symbols) == 8
    assert config.backtest.initial_capital == 10_000
    assert config.risk.max_gross == 1.0


def test_empty_symbols_rejected() -> None:
    with pytest.raises(ValidationError):
        DataConfig(symbols=[])


def test_symbols_deduplicated() -> None:
    config = DataConfig(symbols=["BTCUSDT", "BTCUSDT", "ETHUSDT"])
    assert config.symbols == ["BTCUSDT", "ETHUSDT"]
