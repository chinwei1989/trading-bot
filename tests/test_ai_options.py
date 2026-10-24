from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from tradingbot.ai.decision import AgentDecision, AssetDecision
from tradingbot.config import (
    AgentConfig,
    AgentPolicyConfig,
    AppConfig,
    BacktestConfig,
    BrokerConfig,
    DataConfig,
    RiskConfig,
    StrategyConfig,
)
from tradingbot.data.store import save_bars
from tradingbot.options.account import OptionCandidate
from tradingbot.options.ai_pipeline import run_ai_options_cycle


def _bars() -> pl.DataFrame:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    rows = []
    for i in range(260):
        ts = start + timedelta(minutes=30 * i)
        for asset, base in (("BTCUSDT", 100_000.0), ("ETHUSDT", 3_800.0)):
            close = base * (1.0 + 0.0002 * i)
            rows.append(
                {
                    "timestamp": ts,
                    "asset": asset,
                    "open": close * 0.999,
                    "high": close * 1.004,
                    "low": close * 0.996,
                    "close": close,
                    "volume": 1000.0,
                }
            )
    return pl.DataFrame(rows)


class FakeProvider:
    def decide(self, context: dict) -> AgentDecision:
        return AgentDecision(
            as_of=context["as_of"],
            provider="fake",
            model="fake-1",
            regime="risk_on",
            confidence=0.8,
            actions=[
                AssetDecision(asset="BTCUSDT", action="flat", confidence=0.7),
                AssetDecision(asset="ETHUSDT", action="long", confidence=0.8),
            ],
        )


class FakeChain:
    def fetch_chain(self, currencies, *, now=None):
        expiry = now.date() + timedelta(days=9)
        return [
            OptionCandidate(
                instrument="ETH-07NOV26-4000-C",
                underlying="ETH",
                option_type="call",
                strike=4000.0,
                expiry=expiry,
                bid=183.3,
                ask=186.7,
                mark=185.0,
                delta=0.46,
                gamma=0.0002,
                vega=12.0,
                theta=-3.2,
                open_interest=1200,
            )
        ]


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        data=DataConfig(
            symbols=["BTCUSDT", "ETHUSDT"],
            interval="30m",
            bars_path=Path("data/bars_30m.parquet"),
            include_recent=False,
            recent_limit=1000,
        ),
        strategy=StrategyConfig(name="trend"),
        backtest=BacktestConfig(
            initial_capital=10_000,
            cost_bps=0,
            slippage_bps=0,
            periods_per_year=17_520,
        ),
        risk=RiskConfig(
            kill_switch_file=Path("artifacts/ai_options_30m/KILL"),
            state_path=Path("artifacts/ai_options_30m/risk.json"),
        ),
        broker=BrokerConfig(
            name="paper",
            paper=True,
            initial_cash=10_000,
            state_path=Path("artifacts/ai_options_30m/paper.json"),
            performance_path=Path("artifacts/ai_options_30m/performance.jsonl"),
            heartbeat_path=Path("artifacts/ai_options_30m/heartbeat.json"),
        ),
        agent=AgentConfig(
            enabled=True,
            provider="deterministic",
            paper_only=True,
            include_macro=False,
            include_sentiment=False,
            artifacts_dir=Path("artifacts/ai_options_30m"),
            policy=AgentPolicyConfig(min_confidence=0.5, allow_short=True),
        ),
    )


def test_ai_options_cycle_uses_decision_and_paper_broker(tmp_path: Path) -> None:
    config = _config(tmp_path)
    save_bars(_bars(), tmp_path / config.data.bars_path)
    result = run_ai_options_cycle(
        config,
        root=tmp_path,
        decision_provider=FakeProvider(),
        chain_provider=FakeChain(),
        refresh=False,
    )
    assert result.status == "ok"
    assert result.provider == "fake"
    assert result.directions == {"BTC": "flat", "ETH": "long"}
    assert result.paper is not None
    assert result.paper["fills"]
    assert result.equity < 10_000
    assert (tmp_path / config.agent.artifacts_dir / "paper.json").exists()
    assert (tmp_path / config.agent.artifacts_dir / "reports/latest.json").exists()
    report = json.loads(
        (tmp_path / config.agent.artifacts_dir / "reports/latest.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["pipeline"] == "ai_options"
    assert report["directions"]["ETH"] == "long"
