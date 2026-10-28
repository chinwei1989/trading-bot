from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from tradingbot.config import DataConfig, load_config

ROOT = Path(__file__).resolve().parents[1]


def test_load_base_config() -> None:
    config = load_config(ROOT / "config" / "base.yaml")
    assert config.strategy.name == "trend"
    assert len(config.data.symbols) == 9
    assert "SUIUSDT" in config.data.symbols
    assert config.backtest.initial_capital == 10_000
    assert config.risk.max_gross == 1.0


def test_load_sui_config() -> None:
    config = load_config(ROOT / "config" / "sui.yaml")
    assert config.data.symbols == ["SUIUSDT"]
    assert config.data.interval == "1d"
    assert config.data.bars_path == Path("data/normalized/bars_sui.parquet")
    assert config.broker.name == "paper"
    assert config.broker.initial_cash == 10_000
    assert config.risk.max_asset_weight == 0.25
    assert config.data.universe_path is not None
    assert (ROOT / config.data.universe_path).exists()


def test_empty_symbols_rejected() -> None:
    with pytest.raises(ValidationError):
        DataConfig(symbols=[])


def test_symbols_deduplicated() -> None:
    config = DataConfig(symbols=["BTCUSDT", "BTCUSDT", "ETHUSDT"])
    assert config.symbols == ["BTCUSDT", "ETHUSDT"]
