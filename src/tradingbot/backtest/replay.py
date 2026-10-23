"""Historical paper-broker replay.

This walks the strategy through history and uses the same PaperBroker, order
planner, and accounting code as the live/paper runner. It is a bridge between
the vectorized backtest and real execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

import polars as pl

from tradingbot.backtest.engine import BacktestResult, run_backtest
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.config import AppConfig
from tradingbot.data.store import asset_columns, load_bars, normalize_bars, wide
from tradingbot.execution.orders import execute_orders, latest_weights, plan_orders
from tradingbot.execution.paper import PaperBroker
from tradingbot.portfolio.risk import enforce_limits
from tradingbot.strategies import build_strategy


@dataclass
class PaperReplayResult:
    daily: pl.DataFrame
    metrics: dict[str, float]
    backtest: BacktestResult
    fills: int


def _prices(row: dict[str, object], assets: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for asset in assets:
        value = row.get(asset)
        if value is not None:
            try:
                price = float(cast(Any, value))
            except (TypeError, ValueError):
                continue
            if price > 0:
                out[asset] = price
    return out


def _row_map(frame: pl.DataFrame) -> dict[datetime, dict[str, object]]:
    return {r["timestamp"]: r for r in frame.iter_rows(named=True)}


def paper_replay(
    config: AppConfig,
    bars: pl.DataFrame | None = None,
) -> PaperReplayResult:
    bars = normalize_bars(bars if bars is not None else load_bars(config.data.bars_path))
    strategy = build_strategy(config.strategy, config.backtest.periods_per_year)
    signal = strategy.generate_weights(bars)
    weights = enforce_limits(signal.weights, config.risk)
    if weights.is_empty():
        raise RuntimeError("strategy produced no weights")

    open_w = wide(bars, "open").sort("timestamp")
    close_w = wide(bars, "close").sort("timestamp")
    assets = asset_columns(open_w)
    open_w = open_w.with_columns([pl.col(a).forward_fill() for a in assets])
    close_w = close_w.with_columns([pl.col(a).forward_fill() for a in assets])
    open_map = _row_map(open_w)
    close_map = _row_map(close_w)

    decisions = {
        ts: group
        for (ts,), group in weights.group_by(["timestamp"], maintain_order=True)
    }
    dates = sorted(set(open_map) & set(close_map))
    if len(dates) < 2:
        raise RuntimeError("not enough bars for replay")

    allow_short = (
        config.strategy.trend.long_short
        if config.strategy.name == "trend"
        else config.strategy.xsmom.long_short
    )
    broker = PaperBroker(
        cash=config.backtest.initial_capital,
        commission_bps=config.backtest.cost_bps,
        slippage_bps=config.backtest.slippage_bps,
        allow_short=allow_short,
    )

    rows: list[dict[str, object]] = []
    fills = 0
    for i, decision_date in enumerate(dates[:-1]):
        next_date = dates[i + 1]
        turnover = 0.0
        if decision_date in decisions:
            target = latest_weights(decisions[decision_date])
            open_prices = _prices(open_map[next_date], assets)
            broker.set_prices(open_prices)
            account = broker.get_account()
            orders = plan_orders(
                target,
                account.equity,
                open_prices,
                broker.get_positions(),
                min_notional=config.broker.min_notional,
                allow_short=allow_short,
            )
            results = execute_orders(broker, orders)
            fills += len([r for r in results if r.status == "filled"])
            for result in results:
                if result.avg_price and result.filled_qty:
                    turnover += abs(result.filled_qty * result.avg_price) / max(account.equity, 1e-9)

        close_prices = _prices(close_map[next_date], assets)
        broker.set_prices(close_prices)
        account = broker.get_account()
        gross = (
            sum(abs(p.qty) * close_prices.get(a, p.avg_entry_price) for a, p in broker.positions.items())
            / max(account.equity, 1e-9)
        )
        rows.append(
            {
                "timestamp": next_date,
                "equity": account.equity,
                "cash": account.cash,
                "turnover": turnover,
                "gross_exposure": gross,
            }
        )

    daily = pl.DataFrame(rows).sort("timestamp")
    returns = daily["equity"].pct_change().fill_null(0.0)
    metrics = compute_metrics(
        returns,
        periods_per_year=config.backtest.periods_per_year,
        turnover=daily["turnover"],
        gross_exposure=daily["gross_exposure"],
    )
    metrics["final_equity"] = float(daily["equity"][-1]) if daily.height else config.backtest.initial_capital
    backtest = run_backtest(bars, weights, config.backtest)
    return PaperReplayResult(daily=daily, metrics=metrics, backtest=backtest, fills=fills)
