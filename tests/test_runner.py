from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
import yaml

from tradingbot.config import (
    AppConfig,
    BacktestConfig,
    BrokerConfig,
    DataConfig,
    RiskConfig,
    StrategyConfig,
    TrendParams,
)
from tradingbot.data.store import save_bars
from tradingbot.ops.risk_state import save_peak
from tradingbot.ops.runner import run_cycle, run_forever
from tradingbot.portfolio.risk import RiskLimitBreached


def _bars() -> pl.DataFrame:
    rows = []
    start = datetime(2023, 1, 1, tzinfo=UTC)
    for asset, rate in {"A": 0.004, "B": 0.002}.items():
        for i in range(160):
            close = 100.0 * ((1 + rate) ** i)
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


def _config() -> AppConfig:
    return AppConfig(
        data=DataConfig(
            symbols=["A", "B"],
            bars_path=Path("data/bars.parquet"),
            include_recent=False,
            start="2023-01",
        ),
        strategy=StrategyConfig(
            name="trend",
            trend=TrendParams(
                lookback=20,
                vol_window=10,
                target_vol=0.15,
                max_weight=0.5,
                vol_target=False,
                rebalance="W",
            ),
        ),
        backtest=BacktestConfig(
            initial_capital=10_000,
            cost_bps=0,
            slippage_bps=0,
            periods_per_year=365,
        ),
        risk=RiskConfig(
            max_drawdown=0.5,
            kill_switch_file=Path("artifacts/KILL"),
            state_path=Path("artifacts/risk.json"),
        ),
        broker=BrokerConfig(
            name="paper",
            initial_cash=10_000,
            min_notional=1,
            state_path=Path("artifacts/paper.json"),
            journal_path=Path("artifacts/orders.sqlite"),
            heartbeat_path=Path("artifacts/heartbeat.json"),
        ),
    )


def _prepare(tmp_path: Path, config: AppConfig) -> AppConfig:
    save_bars(_bars(), tmp_path / config.data.bars_path)
    return config


def test_paper_cycle_and_idempotence(tmp_path) -> None:
    config = _prepare(tmp_path, _config())
    first = run_cycle(config, mode="paper", root=tmp_path)
    assert first.orders
    assert first.fills
    assert (tmp_path / "artifacts" / "paper.json").exists()
    assert (tmp_path / "artifacts" / "heartbeat.json").exists()
    heartbeat = (tmp_path / "artifacts" / "heartbeat.json").read_text(encoding="utf-8")
    assert '"status": "ok"' in heartbeat

    second = run_cycle(config, mode="paper", root=tmp_path)
    assert second.orders == []


def test_paper_cycle_reports_post_fill_equity(tmp_path) -> None:
    config = _prepare(tmp_path, _config())
    config.backtest.cost_bps = 25
    config.backtest.slippage_bps = 10

    result = run_cycle(config, mode="paper", root=tmp_path)

    assert result.orders
    assert result.equity < 10_000
    heartbeat = json.loads(
        (tmp_path / "artifacts" / "heartbeat.json").read_text(encoding="utf-8")
    )
    assert heartbeat["equity"] == pytest.approx(result.equity)
    performance = [
        json.loads(line)
        for line in (tmp_path / "artifacts" / "performance.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert performance[-1]["equity"] == pytest.approx(result.equity)


def test_reset_archives_order_state(tmp_path) -> None:
    config = _prepare(tmp_path, _config())
    run_cycle(config, mode="paper", root=tmp_path)
    run_cycle(config, mode="paper", reset=True, root=tmp_path)
    assert list((tmp_path / "artifacts").glob("order_state.sqlite.bak-*"))
    assert list((tmp_path / "artifacts").glob("orders.sqlite.bak-*"))
    assert list((tmp_path / "artifacts").glob("performance.jsonl.bak-*"))


def test_live_requires_non_paper_and_flags(tmp_path) -> None:
    config = _prepare(tmp_path, _config())
    config.broker.name = "alpaca"
    config.broker.paper = True
    with pytest.raises(PermissionError):
        run_cycle(config, mode="live", confirm_live=True, root=tmp_path)


def test_kill_switch_blocks(tmp_path) -> None:
    config = _prepare(tmp_path, _config())
    kill = tmp_path / "artifacts" / "KILL"
    kill.parent.mkdir(parents=True, exist_ok=True)
    kill.write_text("stop", encoding="utf-8")
    with pytest.raises(RiskLimitBreached):
        run_cycle(config, mode="paper", root=tmp_path)


def test_run_forever_once_paper(tmp_path) -> None:
    config = _prepare(tmp_path, _config())
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    code = run_forever(path, mode="paper", once=True, root=tmp_path)
    assert code == 0
    assert (tmp_path / "artifacts" / "heartbeat.json").exists()


def test_drawdown_breach_auto_kills(tmp_path) -> None:
    root = tmp_path / "dd"
    config = _prepare(root, _config())
    config.risk.max_drawdown = 0.1
    config.risk.state_path = Path("artifacts/risk_dd.json")
    save_peak(root / config.risk.state_path, 20_000)
    with pytest.raises(RiskLimitBreached):
        run_cycle(config, mode="paper", root=root)
    assert (root / "artifacts" / "KILL").exists()
