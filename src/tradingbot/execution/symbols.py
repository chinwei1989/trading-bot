"""Symbol mapping between data vendors and brokers."""

from __future__ import annotations

import polars as pl

QUOTES = ("USDT", "USDC", "USD", "BTC", "ETH")


def to_broker_symbol(asset: str, broker: str, quote: str = "USDT") -> str:
    """Map a data symbol (e.g. BTCUSDT) to a broker symbol (e.g. BTC/USDT)."""
    if broker != "ccxt":
        return asset
    if "/" in asset:
        return asset
    for q in (quote, *QUOTES):
        if asset.endswith(q) and len(asset) > len(q):
            return f"{asset[: -len(q)]}/{q}"
    return f"{asset}/{quote}"


def map_weights(
    weights: pl.DataFrame,
    broker: str,
    quote: str = "USDT",
) -> pl.DataFrame:
    if weights.is_empty():
        return weights
    mapping = {
        asset: to_broker_symbol(asset, broker, quote)
        for asset in weights["asset"].unique().to_list()
    }
    return weights.with_columns(pl.col("asset").replace(mapping).alias("asset"))
