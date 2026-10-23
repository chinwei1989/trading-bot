"""Build a broker from configuration."""

from __future__ import annotations

from tradingbot.config import AppConfig
from tradingbot.execution.broker import Broker
from tradingbot.execution.paper import PaperBroker


def build_broker(
    config: AppConfig,
    *,
    force_paper: bool = False,
    allow_short: bool = False,
) -> Broker:
    if force_paper or config.broker.name == "paper":
        return PaperBroker(
            cash=config.broker.initial_cash,
            commission_bps=config.backtest.cost_bps,
            slippage_bps=config.backtest.slippage_bps,
            allow_short=allow_short,
        )
    if config.broker.name == "alpaca":
        from tradingbot.execution.alpaca import AlpacaBroker

        return AlpacaBroker(paper=config.broker.paper)
    if config.broker.name == "ccxt":
        from tradingbot.execution.ccxt import CcxtBroker

        return CcxtBroker(
            exchange_id=config.broker.exchange,
            quote=config.broker.quote_currency,
            sandbox=config.broker.sandbox,
        )
    raise ValueError(f"unknown broker: {config.broker.name}")
