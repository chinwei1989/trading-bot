"""Scheduled paper/live execution cycle with heartbeat and risk-state control."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import polars as pl

from tradingbot.config import AppConfig, load_config
from tradingbot.data.universe import load_bars_with_universe
from tradingbot.execution.broker import OrderRequest, OrderResult, Position
from tradingbot.execution.factory import build_broker
from tradingbot.execution.manager import OrderManager, ReconciliationError
from tradingbot.execution.orders import (
    OrderJournal,
    latest_weights,
    plan_orders,
    reconcile,
)
from tradingbot.execution.paper import PaperBroker
from tradingbot.execution.state import OrderStateStore
from tradingbot.execution.symbols import map_weights
from tradingbot.ops.alerts import notify
from tradingbot.ops.calendar import is_us_trading_day
from tradingbot.ops.heartbeat import write_heartbeat
from tradingbot.ops.performance import append_performance
from tradingbot.ops.risk_state import load_peak, save_peak
from tradingbot.portfolio.risk import RiskLimitBreached, assert_safe, enforce_limits
from tradingbot.strategies import build_strategy

Mode = Literal["paper", "preview", "live"]


@dataclass
class RunResult:
    mode: str
    equity: float
    cash: float
    status: str = "ok"
    orders: list[OrderRequest] = field(default_factory=list)
    fills: list[OrderResult] = field(default_factory=list)
    reconciliation: pl.DataFrame = field(default_factory=pl.DataFrame)
    positions: dict[str, Position] = field(default_factory=dict)
    heartbeat_path: Path | None = None


def _resolve(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def _strategy_long_short(config: AppConfig) -> bool:
    if config.strategy.name == "trend":
        return config.strategy.trend.long_short
    if config.strategy.name == "xsmom":
        return config.strategy.xsmom.long_short
    if config.strategy.name == "breakout":
        return config.strategy.breakout.long_short
    if config.strategy.name == "reversal":
        return config.strategy.reversal.long_short
    if config.strategy.name == "meta":
        return any(
            [
                config.strategy.trend.long_short,
                config.strategy.xsmom.long_short,
                config.strategy.breakout.long_short,
                config.strategy.reversal.long_short,
            ]
        )
    return False


def _assert_live_ready(config: AppConfig, confirm_live: bool) -> None:
    if config.broker.name == "paper" or config.broker.paper:
        raise PermissionError("live mode requires a non-paper broker (alpaca/ccxt) and paper=false")
    if not confirm_live:
        raise PermissionError("live mode requires --confirm-live")
    if os.getenv("LIVE_TRADING") != "YES":
        raise PermissionError("live mode requires LIVE_TRADING=YES in the environment")
    if config.broker.name == "ccxt" and config.broker.sandbox:
        raise PermissionError("live mode requires broker.sandbox=false")
    if config.broker.name == "alpaca" and config.data.source != "alpaca":
        raise PermissionError("Alpaca live mode requires data.source=alpaca")
    if config.broker.name == "ccxt" and config.data.source != "binance":
        raise PermissionError("ccxt live mode requires data.source=binance")


def _completed_bars(bars: pl.DataFrame, interval: str) -> pl.DataFrame:
    """Drop the current, still-forming daily bar."""
    if interval != "1d" or bars.is_empty():
        return bars
    today = datetime.now(UTC).date()
    return bars.filter(pl.col("timestamp").dt.date() < today)


def _last_prices(bars: pl.DataFrame) -> dict[str, float]:
    last = bars.sort("timestamp").group_by("asset").tail(1)
    return {r["asset"]: float(r["close"]) for r in last.iter_rows(named=True)}


def run_cycle(
    config: AppConfig,
    mode: Mode = "paper",
    *,
    confirm_live: bool = False,
    reset: bool = False,
    root: Path | None = None,
) -> RunResult:
    root = root or Path.cwd()
    if mode == "live":
        _assert_live_ready(config, confirm_live)
        if reset:
            raise ValueError("reset is not allowed in live mode")

    bars_path = _resolve(root, config.data.bars_path)
    if not bars_path.exists():
        raise FileNotFoundError(f"missing bars: {bars_path}")
    universe_path = _resolve(root, config.data.universe_path) if config.data.universe_path else None
    bars = _completed_bars(
        load_bars_with_universe(bars_path, universe_path),
        config.data.interval,
    )
    if bars.is_empty():
        raise RuntimeError("no completed bars available")

    if mode == "live" and config.data.source == "alpaca" and not is_us_trading_day():
        heartbeat_path = _resolve(root, config.broker.heartbeat_path)
        write_heartbeat(
            heartbeat_path,
            {"mode": mode, "status": "market_closed", "strategy": config.strategy.name},
        )
        return RunResult(
            mode=mode,
            equity=0.0,
            cash=0.0,
            status="market_closed",
            heartbeat_path=heartbeat_path,
        )

    strategy = build_strategy(config.strategy, config.backtest.periods_per_year)
    signal = strategy.generate_weights(bars)
    weights = enforce_limits(signal.weights, config.risk)
    assert_safe(
        weights,
        config.risk,
        kill_file=_resolve(root, config.risk.kill_switch_file),
    )

    force_paper = mode == "paper"
    allow_short = _strategy_long_short(config) if force_paper else config.broker.allow_short
    broker = build_broker(config, force_paper=force_paper, allow_short=allow_short)

    state_path = _resolve(root, config.broker.state_path)
    if isinstance(broker, PaperBroker):
        broker.set_prices(_last_prices(bars))
        if not reset:
            broker.load_state(state_path)

    account = broker.get_account()
    risk_path = _resolve(root, config.risk.state_path)
    peak = load_peak(risk_path)
    if peak is None or reset or account.equity > peak:
        peak = account.equity
        save_peak(risk_path, peak)
    drawdown = account.equity / peak - 1.0 if peak > 0 else 0.0
    if drawdown < -config.risk.max_drawdown:
        if config.risk.auto_kill_on_drawdown:
            kill = _resolve(root, config.risk.kill_switch_file)
            kill.parent.mkdir(parents=True, exist_ok=True)
            kill.write_text(
                f"auto-kill: drawdown {drawdown:.2%} < -{config.risk.max_drawdown:.2%}",
                encoding="utf-8",
            )
        raise RiskLimitBreached(
            f"drawdown {drawdown:.2%} < -{config.risk.max_drawdown:.2%}"
        )

    if not force_paper and config.broker.name == "ccxt":
        weights = map_weights(weights, "ccxt", config.broker.quote_currency)
    latest = latest_weights(weights)
    if latest.is_empty():
        raise RuntimeError("strategy produced no target weights")

    positions = broker.get_positions()
    assets = sorted(set(latest["asset"].to_list()) | set(positions))
    prices = (
        _last_prices(bars)
        if isinstance(broker, PaperBroker)
        else broker.get_prices(assets)
    )
    orders = plan_orders(
        latest,
        account.equity,
        prices,
        positions,
        min_notional=config.broker.min_notional,
        allow_short=allow_short,
    )

    heartbeat_path = _resolve(root, config.broker.heartbeat_path)
    if mode == "preview":
        rec = reconcile(latest, account.equity, prices, positions)
        result = RunResult(
            mode=mode,
            equity=account.equity,
            cash=account.cash,
            orders=orders,
            positions=positions,
            reconciliation=rec,
            heartbeat_path=heartbeat_path,
        )
        write_heartbeat(
            heartbeat_path,
            {
                "mode": mode,
                "status": "preview",
                "equity": account.equity,
                "cash": account.cash,
                "drawdown": drawdown,
                "n_orders": len(orders),
                "n_fills": 0,
                "strategy": config.strategy.name,
                "broker": config.broker.name,
            },
        )
        return result

    journal_path = _resolve(root, config.broker.journal_path)
    order_state_path = _resolve(root, config.broker.order_state_path)
    if reset and mode == "paper":
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        for path in (
            journal_path,
            order_state_path,
            _resolve(root, config.broker.performance_path),
        ):
            if path.exists():
                path.replace(path.with_name(f"{path.name}.bak-{stamp}"))
    journal = OrderJournal(journal_path)
    state = OrderStateStore(order_state_path)
    manager = OrderManager(
        broker,
        state,
        journal,
        max_child_notional=config.broker.max_child_notional,
        max_children=config.broker.max_children,
    )
    manager.assert_reconciled()
    fills = manager.execute(orders)
    journal.close()
    state.close()
    if isinstance(broker, PaperBroker):
        broker.save_state(state_path)

    positions = broker.get_positions()
    rec = reconcile(latest, account.equity, prices, positions)
    post = broker.get_account()
    gross_exposure = (
        sum(abs(pos.qty) * prices.get(asset, pos.avg_entry_price) for asset, pos in positions.items())
        / max(post.equity, 1e-9)
    )
    net_exposure = (
        sum(pos.qty * prices.get(asset, pos.avg_entry_price) for asset, pos in positions.items())
        / max(post.equity, 1e-9)
    )
    append_performance(
        _resolve(root, config.broker.performance_path),
        {
            "mode": mode,
            "strategy": config.strategy.name,
            "equity": post.equity,
            "cash": post.cash,
            "drawdown": drawdown,
            "gross_exposure": gross_exposure,
            "net_exposure": net_exposure,
            "n_orders": len(orders),
            "n_fills": len([f for f in fills if f.status in {"filled", "accepted", "new"}]),
            "positions": len(positions),
        },
    )
    write_heartbeat(
        heartbeat_path,
        {
            "mode": mode,
            "status": "ok",
            "equity": account.equity,
            "cash": account.cash,
            "drawdown": drawdown,
            "n_orders": len(orders),
            "n_fills": len([f for f in fills if f.status in {"filled", "accepted", "new"}]),
            "strategy": config.strategy.name,
            "broker": config.broker.name,
            "positions": {a: p.qty for a, p in positions.items()},
        },
    )
    if orders:
        notify(
            f"tradingbot {mode} {datetime.now(UTC):%Y-%m-%d %H:%M UTC}",
            [
                f"equity {account.equity:,.2f} cash {account.cash:,.2f}",
                f"orders {len(orders)} fills {len(fills)} drawdown {drawdown:.2%}",
            ],
        )
    return RunResult(
        mode=mode,
        equity=account.equity,
        cash=account.cash,
        orders=orders,
        fills=fills,
        reconciliation=rec,
        positions=positions,
        heartbeat_path=heartbeat_path,
    )


def _error_heartbeat(root: Path, config: AppConfig | None, mode: str, exc: Exception) -> None:
    path = (
        _resolve(root, config.broker.heartbeat_path)
        if config
        else root / "artifacts" / "heartbeat.json"
    )
    write_heartbeat(
        path,
        {
            "mode": mode,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "strategy": config.strategy.name if config else None,
            "broker": config.broker.name if config else None,
        },
    )


def run_forever(
    config_path: str | Path,
    mode: Mode = "paper",
    *,
    interval_seconds: int = 3600,
    confirm_live: bool = False,
    once: bool = False,
    reset: bool = False,
    strategy_override: str | None = None,
    root: Path | None = None,
) -> int:
    root = root or Path.cwd()
    while True:
        config: AppConfig | None = None
        try:
            config = load_config(config_path)
            if strategy_override:
                config.strategy.name = strategy_override  # type: ignore[assignment]
            if mode == "live":
                _assert_live_ready(config, confirm_live)
            result = run_cycle(
                config,
                mode,
                confirm_live=confirm_live,
                reset=reset,
                root=root,
            )
            print(
                f"[{result.mode}] status={result.status} equity={result.equity:,.2f} "
                f"cash={result.cash:,.2f} orders={len(result.orders)} fills={len(result.fills)}"
            )
            if result.status == "ok":
                try:
                    from tradingbot.ops.evaluation import (
                        build_report,
                        print_summary,
                        write_report,
                    )

                    report = build_report(config, config.strategy.name, root)
                    write_report(report, root)
                    print_summary(report)
                except Exception as exc:
                    print(f"[warn] evaluation failed: {type(exc).__name__}: {exc}")
            reset = False
        except KeyboardInterrupt:
            print("stopped")
            return 0
        except Exception as exc:
            _error_heartbeat(root, config, mode, exc)
            notify(
                "tradingbot error",
                [f"mode {mode}", f"{type(exc).__name__}: {exc}"],
            )
            print(f"[error] {type(exc).__name__}: {exc}")
            if once:
                return 1
            if isinstance(exc, (PermissionError, RiskLimitBreached, ReconciliationError)):
                return 2
            kill = _resolve(root, config.risk.kill_switch_file) if config else None
            if kill and kill.exists():
                return 3
        if once:
            return 0
        time.sleep(max(1, interval_seconds))
