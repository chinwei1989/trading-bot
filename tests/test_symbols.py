from __future__ import annotations

import polars as pl

from tradingbot.execution.symbols import map_weights, to_broker_symbol


def test_symbol_mapping() -> None:
    assert to_broker_symbol("BTCUSDT", "ccxt", "USDT") == "BTC/USDT"
    assert to_broker_symbol("ETHUSDC", "ccxt", "USDC") == "ETH/USDC"
    assert to_broker_symbol("BTC/USDT", "ccxt") == "BTC/USDT"
    assert to_broker_symbol("SPY", "alpaca") == "SPY"


def test_map_weights() -> None:
    weights = pl.DataFrame(
        {"timestamp": [1, 1], "asset": ["BTCUSDT", "ETHUSDT"], "weight": [0.5, 0.5]}
    )
    mapped = map_weights(weights, "ccxt", "USDT")
    assert set(mapped["asset"].to_list()) == {"BTC/USDT", "ETH/USDT"}
