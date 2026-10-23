"""ccxt broker adapter (crypto spot/futures).

This is a thin wrapper. Start with sandbox/testnet and never enable withdrawals.
"""

from __future__ import annotations

import os

import ccxt  # type: ignore[import-untyped]

from tradingbot.execution.broker import Account, OrderRequest, OrderResult, Position


class CcxtBroker:
    def __init__(
        self,
        exchange_id: str = "kraken",
        api_key: str | None = None,
        secret: str | None = None,
        password: str | None = None,
        *,
        quote: str = "USD",
        sandbox: bool = True,
    ):
        self.quote = quote
        exchange_class = getattr(ccxt, exchange_id, None)
        if exchange_class is None:
            raise ValueError(f"unknown ccxt exchange: {exchange_id}")
        config = {
            "apiKey": api_key or os.getenv("CRYPTO_API_KEY"),
            "secret": secret or os.getenv("CRYPTO_API_SECRET"),
            "password": password or os.getenv("CRYPTO_PASSPHRASE"),
            "enableRateLimit": True,
        }
        self.exchange = exchange_class({k: v for k, v in config.items() if v})
        if sandbox and hasattr(self.exchange, "set_sandbox_mode"):
            self.exchange.set_sandbox_mode(True)
        self.exchange.load_markets()
        self._client_orders: dict[str, str] = {}

    def get_account(self) -> Account:
        balance = self.exchange.fetch_balance()
        total = balance.get("total", {})
        free = balance.get("free", {})
        quote_total = float(total.get(self.quote, 0.0) or 0.0)
        quote_free = float(free.get(self.quote, 0.0) or 0.0)
        equity = quote_total
        for asset, qty in total.items():
            if asset == self.quote or not qty:
                continue
            symbol = f"{asset}/{self.quote}"
            if symbol in self.exchange.markets:
                try:
                    price = float(self.exchange.fetch_ticker(symbol)["last"])
                    equity += float(qty) * price
                except Exception:
                    continue
        return Account(equity=equity, cash=quote_free, buying_power=quote_free)

    def get_positions(self) -> dict[str, Position]:
        balance = self.exchange.fetch_balance()
        total = balance.get("total", {})
        out: dict[str, Position] = {}
        for asset, qty in total.items():
            qty = float(qty or 0.0)
            if qty <= 0 or asset == self.quote:
                continue
            symbol = f"{asset}/{self.quote}"
            if symbol not in self.exchange.markets:
                continue
            try:
                price = float(self.exchange.fetch_ticker(symbol)["last"])
            except Exception:
                continue
            out[symbol] = Position(symbol, qty, qty * price, price)
        return out

    def get_prices(self, assets: list[str]) -> dict[str, float]:
        if not assets:
            return {}
        out: dict[str, float] = {}
        try:
            tickers = self.exchange.fetch_tickers(assets)
        except Exception:
            tickers = {}
        for symbol, ticker in tickers.items():
            last = ticker.get("last")
            if last is not None and float(last) > 0:
                out[symbol] = float(last)
        for symbol in assets:
            if symbol in out:
                continue
            try:
                ticker = self.exchange.fetch_ticker(symbol)
                last = ticker.get("last")
                if last is not None and float(last) > 0:
                    out[symbol] = float(last)
            except Exception:
                continue
        return out

    def submit_order(self, order: OrderRequest) -> OrderResult:
        params = {}
        if order.client_order_id:
            params["clientOrderId"] = order.client_order_id
        result = self.exchange.create_order(
            order.asset,
            order.order_type,
            order.side,
            order.qty,
            order.limit_price,
            params,
        )
        if order.client_order_id:
            self._client_orders[order.client_order_id] = str(result.get("id", ""))
        return self._to_result(result, order.client_order_id)

    def _to_result(self, result: dict, client_order_id: str | None = None) -> OrderResult:
        return OrderResult(
            order_id=str(result.get("id", "")),
            asset=str(result.get("symbol", "")),
            side=str(result.get("side", "")),
            qty=float(result.get("amount", 0.0) or 0.0),
            status=str(result.get("status", "submitted")),
            filled_qty=float(result.get("filled", 0.0) or 0.0),
            avg_price=(
                float(result["average"]) if result.get("average") is not None else None
            ),
            client_order_id=(
                str(result.get("clientOrderId") or client_order_id)
                if (result.get("clientOrderId") or client_order_id)
                else None
            ),
        )

    def get_order(
        self, client_order_id: str, asset: str | None = None
    ) -> OrderResult | None:
        order_id = self._client_orders.get(client_order_id)
        if not order_id or not asset:
            return None
        try:
            result = self.exchange.fetch_order(order_id, asset)
        except Exception:
            return None
        return self._to_result(result, client_order_id)

    def list_open_orders(self) -> list[OrderResult]:
        try:
            orders = self.exchange.fetch_open_orders()
        except Exception:
            return []
        return [self._to_result(order) for order in orders]

    def cancel_all(self) -> None:
        if self.exchange.has.get("cancelAllOrders"):
            self.exchange.cancel_all_orders()
        else:
            for order in self.exchange.fetch_open_orders():
                self.exchange.cancel_order(order["id"], order["symbol"])

    def flatten(self) -> None:
        for symbol, pos in self.get_positions().items():
            if pos.qty > 0:
                self.submit_order(OrderRequest(symbol, "sell", pos.qty))
