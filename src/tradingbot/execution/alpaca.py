"""Alpaca broker adapter (US equities/ETFs).

Requires ALPACA_API_KEY and ALPACA_SECRET_KEY. Defaults to paper trading.
This adapter is intentionally thin; order state is reconciled by the caller.
"""

from __future__ import annotations

import os
import time
from typing import Any, cast

from tradingbot.execution.broker import Account, OrderRequest, OrderResult, Position


class AlpacaBroker:
    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
        *,
        paper: bool = True,
    ):
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.trading.client import TradingClient

        self.api_key = api_key or os.getenv("ALPACA_API_KEY")
        self.secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY")
        if not self.api_key or not self.secret_key:
            raise RuntimeError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required")
        self.paper = paper
        self.trading = TradingClient(self.api_key, self.secret_key, paper=paper)
        self.data = StockHistoricalDataClient(self.api_key, self.secret_key)

    def get_account(self) -> Account:
        acct = cast(Any, self.trading.get_account())
        return Account(
            equity=float(acct.equity),
            cash=float(acct.cash),
            buying_power=float(acct.buying_power),
        )

    def get_positions(self) -> dict[str, Position]:
        out: dict[str, Position] = {}
        for pos in cast(Any, self.trading.get_all_positions()):
            qty = float(pos.qty)
            market_value = float(pos.market_value) if pos.market_value is not None else 0.0
            out[pos.symbol] = Position(
                asset=pos.symbol,
                qty=qty,
                market_value=market_value,
                avg_entry_price=float(pos.avg_entry_price or 0.0),
            )
        return out

    def get_prices(self, assets: list[str]) -> dict[str, float]:
        from datetime import UTC, datetime, timedelta

        from alpaca.data.enums import Adjustment
        from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest
        from alpaca.data.timeframe import TimeFrame

        if not assets:
            return {}
        out: dict[str, float] = {}
        try:
            request = StockLatestTradeRequest(symbol_or_symbols=assets)
            trades = cast(Any, self.data.get_stock_latest_trade(request))
            for symbol, trade in trades.items():
                price = getattr(trade, "price", None)
                if price is not None and float(price) > 0:
                    out[symbol] = float(price)
        except Exception:
            out = {}
        if out:
            return out

        # Fallback: last daily close. Useful when the trade feed is unavailable
        # outside market hours or the account lacks a real-time subscription.
        end = datetime.now(UTC)
        bars = cast(
            Any,
            self.data.get_stock_bars(
                StockBarsRequest(
                    symbol_or_symbols=assets,
                    timeframe=TimeFrame.Day,
                    start=end - timedelta(days=10),
                    end=end,
                    adjustment=Adjustment.ALL,
                )
            ),
        ).df
        if bars is None or bars.empty:
            return {}
        frame = bars.reset_index().sort_values("timestamp")
        for symbol, group in frame.groupby("symbol"):
            out[str(symbol)] = float(group["close"].iloc[-1])
        return out

    def submit_order(self, order: OrderRequest) -> OrderResult:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest

        side = OrderSide.BUY if order.side == "buy" else OrderSide.SELL
        kwargs = {
            "symbol": order.asset,
            "qty": order.qty,
            "side": side,
            "time_in_force": TimeInForce.DAY,
            "client_order_id": order.client_order_id,
        }
        request: Any
        if order.order_type == "limit" and order.limit_price:
            request = LimitOrderRequest(limit_price=order.limit_price, **kwargs)
        else:
            request = MarketOrderRequest(**kwargs)
        submitted = cast(Any, self.trading.submit_order(request))
        # Poll briefly for a market fill; the paper/live order endpoint is async.
        for _ in range(20):
            if str(getattr(submitted, "status", "")).lower().endswith("filled"):
                break
            time.sleep(0.5)
            try:
                submitted = cast(Any, self.trading.get_order_by_id(str(submitted.id)))
            except Exception:
                break
        return self._to_result(submitted, fallback_client_id=order.client_order_id)

    def _to_result(self, submitted: Any, fallback_client_id: str | None = None) -> OrderResult:
        side = str(getattr(submitted, "side", "")).lower()
        side = "buy" if "buy" in side else "sell"
        return OrderResult(
            order_id=str(submitted.id),
            asset=str(submitted.symbol),
            side=side,
            qty=float(submitted.qty or 0.0),
            status=str(submitted.status),
            filled_qty=float(submitted.filled_qty or 0.0),
            avg_price=(
                float(submitted.filled_avg_price)
                if submitted.filled_avg_price is not None
                else None
            ),
            client_order_id=str(
                getattr(submitted, "client_order_id", None) or fallback_client_id or ""
            )
            or None,
        )

    def get_order(
        self, client_order_id: str, asset: str | None = None
    ) -> OrderResult | None:
        try:
            order = cast(Any, self.trading.get_order_by_client_id(client_order_id))
        except Exception:
            return None
        if order is None:
            return None
        return self._to_result(order, fallback_client_id=client_order_id)

    def list_open_orders(self) -> list[OrderResult]:
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        try:
            orders = cast(
                Any,
                self.trading.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN)),
            )
        except Exception:
            return []
        return [self._to_result(order) for order in orders]

    def cancel_all(self) -> None:
        self.trading.cancel_orders()

    def flatten(self) -> None:
        self.trading.close_all_positions(cancel_orders=True)
