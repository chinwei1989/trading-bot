from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from tradingbot.config import (
    AppConfig,
    BacktestConfig,
    BrokerConfig,
    DataConfig,
    RiskConfig,
    StrategyConfig,
    SwingOptionsConfig,
    TrendParams,
)
from tradingbot.options.account import OptionCandidate
from tradingbot.options.swing import (
    SwingSignal,
    build_swing_signals,
    run_options_swing_cycle,
)

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
EXPIRY = date(2026, 11, 25)


def _bars(direction: str = "up", days: int = 220) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    start = NOW - timedelta(days=days)
    for asset, base in (("BTCUSDT", 100.0), ("ETHUSDT", 50.0)):
        for i in range(days):
            if direction == "up":
                close = base * (1.0 + 0.004) ** i
            elif direction == "down":
                close = base * (1.0 - 0.003) ** i
            else:
                close = base
            rows.append(
                {
                    "timestamp": start + timedelta(days=i),
                    "asset": asset,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1.0,
                }
            )
    return pl.DataFrame(rows)


def _candidate(
    *,
    instrument: str = "BTC-25NOV26-100-C",
    underlying: str = "BTC",
    option_type: str = "call",
    bid: float = 95.0,
    ask: float = 100.0,
    delta: float = 0.50,
) -> OptionCandidate:
    return OptionCandidate(
        instrument=instrument,
        underlying=underlying,
        option_type=option_type,  # type: ignore[arg-type]
        strike=100.0,
        expiry=EXPIRY,
        bid=bid,
        ask=ask,
        mark=(bid + ask) / 2.0,
        delta=delta,
        gamma=0.01,
        vega=1.0,
        theta=-0.1,
        open_interest=1000,
        volume=100,
    )


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        data=DataConfig(
            symbols=["BTCUSDT", "ETHUSDT"],
            bars_path=Path("data/bars.parquet"),
            include_recent=False,
        ),
        strategy=StrategyConfig(name="trend", trend=TrendParams(lookback=50)),
        backtest=BacktestConfig(initial_capital=10_000, cost_bps=0, slippage_bps=0),
        risk=RiskConfig(
            kill_switch_file=Path("artifacts/options_swing/KILL"),
            state_path=Path("artifacts/options_swing/risk.json"),
            max_drawdown=0.5,
        ),
        broker=BrokerConfig(
            name="paper",
            paper=True,
            initial_cash=10_000,
            min_notional=1,
            journal_path=Path("artifacts/options_swing/orders.sqlite"),
            order_state_path=Path("artifacts/options_swing/order_state.sqlite"),
            state_path=Path("artifacts/options_swing/paper.json"),
            performance_path=Path("artifacts/options_swing/performance.jsonl"),
            heartbeat_path=Path("artifacts/options_swing/heartbeat.json"),
        ),
        swing=SwingOptionsConfig(
            min_dte=10,
            max_dte=60,
            exit_dte=7,
            target_delta_min=0.40,
            target_delta_max=0.60,
            max_spread_pct=0.06,
            max_premium_per_trade_pct=0.02,
            max_total_premium_pct=0.05,
            max_open_legs=2,
            max_legs_per_underlying=1,
        ),
    )


def test_swing_signal_directions() -> None:
    up = build_swing_signals(_bars("up"))
    down = build_swing_signals(_bars("down"))
    flat = build_swing_signals(_bars("flat"))
    assert up["BTC"].direction == "long"
    assert down["BTC"].direction == "short"
    assert flat["BTC"].direction == "flat"


def test_swing_enters_and_takes_profit(tmp_path: Path) -> None:
    config = _config(tmp_path)
    chain = [_candidate()]
    up_signals = build_swing_signals(_bars("up"))
    long_btc = {
        "BTC": up_signals["BTC"],
        "ETH": SwingSignal("ETH", "flat", 50.0, 50.0, 50.0, 0.0, "test flat"),
    }
    first = run_options_swing_cycle(
        config,
        root=tmp_path,
        chain=chain,
        bars=_bars("up"),
        now=NOW,
        signals_override=long_btc,
    )
    assert first.status == "ok"
    assert len(first.fills) == 1
    assert first.fills[0].status == "filled"
    assert first.account_after is not None
    assert len(first.account_after.positions) == 1
    assert first.report_path is not None
    assert first.report_path.exists()

    flat_signals = {
        "BTC": SwingSignal("BTC", "flat", 100.0, 100.0, 100.0, 0.0, "test flat"),
    }
    second = run_options_swing_cycle(
        config,
        root=tmp_path,
        chain=[_candidate(bid=160.0, ask=165.0)],
        bars=_bars("up"),
        now=NOW,
        signals_override=flat_signals,
    )
    assert second.status == "ok"
    assert len(second.exits) == 1
    assert second.exits[0].reason == "profit_target"
    assert second.exits[0].status == "filled"
    assert second.exits[0].pnl == pytest.approx(60.0)
    assert second.account_after is not None
    assert second.account_after.positions == ()


def test_swing_stop_loss_exits(tmp_path: Path) -> None:
    config = _config(tmp_path)
    up_signals = build_swing_signals(_bars("up"))
    long_btc = {
        "BTC": up_signals["BTC"],
        "ETH": SwingSignal("ETH", "flat", 50.0, 50.0, 50.0, 0.0, "test flat"),
    }
    first = run_options_swing_cycle(
        config,
        root=tmp_path,
        chain=[_candidate()],
        bars=_bars("up"),
        now=NOW,
        signals_override=long_btc,
    )
    assert first.fills
    flat_signals = {
        "BTC": SwingSignal("BTC", "flat", 100.0, 100.0, 100.0, 0.0, "test flat"),
    }
    second = run_options_swing_cycle(
        config,
        root=tmp_path,
        chain=[_candidate(bid=40.0, ask=45.0)],
        bars=_bars("up"),
        now=NOW,
        signals_override=flat_signals,
    )
    assert second.exits
    assert second.exits[0].reason in {"stop_loss", "trend_exit"}
    assert second.account_after is not None
    assert second.account_after.positions == ()
