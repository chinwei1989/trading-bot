from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import polars as pl
import pytest

from tradingbot.ai.context import build_context
from tradingbot.ai.decision import (
    AgentDecision,
    AssetDecision,
    DecisionValidationError,
    ProviderUnavailable,
)
from tradingbot.ai.policy import apply_policy
from tradingbot.ai.providers import (
    JevProvider,
    OpenAICompatibleProvider,
    _parse_json_object,
)
from tradingbot.config import (
    AgentConfig,
    AgentPolicyConfig,
    AppConfig,
    BacktestConfig,
    BrokerConfig,
    DataConfig,
    RiskConfig,
    StrategyConfig,
    TrendParams,
)
from tradingbot.data.store import save_bars


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
                    "volume": 1.0 + i / 100.0,
                }
            )
    return pl.DataFrame(rows)


def _context() -> dict:
    return {
        "as_of": "2026-10-22T00:00:00+00:00",
        "universe": ["BTC", "ETH"],
        "assets": {
            "BTC": {"vol_60d": 0.5, "trend_up": True, "return_60d": 0.2},
            "ETH": {"vol_60d": 0.7, "trend_up": True, "return_60d": 0.1},
        },
        "portfolio": {"current_weights": {"BTC": 0.0, "ETH": 0.0}},
        "market": {"breadth_above_sma200": 0.75, "data_age_days": 1},
        "constraints": {},
    }


def _policy() -> AgentPolicyConfig:
    return AgentPolicyConfig(
        max_gross=0.8,
        max_asset_weight=0.2,
        min_cash_weight=0.2,
        max_turnover=1.0,
        min_confidence=0.55,
    )


def test_context_uses_completed_features() -> None:
    context = build_context(
        _bars(),
        cash=10_000,
        equity=10_000,
        positions={},
        policy=_policy(),
        root=Path("."),
        include_macro=False,
        include_sentiment=False,
    )
    assert context["universe"] == ["A", "B"]
    assert context["assets"]["A"]["close"] > 0
    assert context["assets"]["A"]["history_days"] == 160
    assert context["market"]["breadth_above_sma200"] == 1.0
    assert context["portfolio"]["current_weights"]["A"] == 0.0


def test_policy_sizes_and_caps_actions() -> None:
    decision = AgentDecision(
        as_of=datetime(2026, 10, 22, tzinfo=UTC),
        confidence=0.9,
        regime="risk_on",
        actions=[
            AssetDecision(asset="BTC", action="long", confidence=0.9),
            AssetDecision(asset="ETH", action="short", confidence=0.9),
        ],
    )
    result = apply_policy(decision, _context(), _policy())
    assert result.gross <= 0.8 + 1e-9
    assert result.target_weights["BTC"] > 0
    assert result.target_weights["ETH"] == 0.0
    assert result.turnover <= 1.0


def test_policy_holds_on_low_confidence() -> None:
    decision = AgentDecision(
        as_of=datetime(2026, 10, 22, tzinfo=UTC),
        confidence=0.2,
        actions=[AssetDecision(asset="BTC", action="long", confidence=0.9)],
    )
    context = _context()
    context["portfolio"]["current_weights"] = {"BTC": 0.15, "ETH": 0.05}
    result = apply_policy(decision, context, _policy())
    assert result.target_weights["BTC"] == 0.15
    assert result.target_weights["ETH"] == 0.05
    assert any("holding current" in note for note in result.notes)


def test_policy_risk_off_reduces_gross() -> None:
    decision = AgentDecision(
        as_of=datetime(2026, 10, 22, tzinfo=UTC),
        confidence=0.9,
        regime="risk_off",
        target_weights={"BTC": 0.5, "ETH": 0.5},
    )
    result = apply_policy(decision, _context(), _policy())
    assert result.gross <= 0.25 + 1e-9


def test_jev_provider_parses_typed_answers(monkeypatch) -> None:
    monkeypatch.setenv("TYPESAFE_TEST_KEY", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret"
        payload = json.loads(request.content)
        assert payload["model"] == "jev-latest"
        assert "regime" in payload["questions"]
        return httpx.Response(
            200,
            json={
                "model": "jev-1.14.0",
                "answers": {
                    "regime": {"type": "choice", "choice": "risk_on", "confidence": 0.8},
                    "BTC": {"type": "choice", "choice": "long", "confidence": 0.9},
                    "ETH": {"type": "choice", "choice": "flat", "confidence": 0.7},
                },
                "usage": {"input_tokens": 100, "output_tokens": 10},
            },
        )

    config = AgentConfig(
        provider="jev",
        api_key_env="TYPESAFE_TEST_KEY",
        policy=_policy(),
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    decision = JevProvider(config, client=client).decide(_context())
    assert decision.provider == "jev"
    assert decision.model == "jev-1.14.0"
    assert {a.asset: a.action for a in decision.actions} == {"BTC": "long", "ETH": "flat"}
    assert decision.usage["input_tokens"] == 100


def test_jev_without_key_is_unavailable(monkeypatch) -> None:
    monkeypatch.delenv("TYPESAFE_MISSING_KEY", raising=False)
    config = AgentConfig(provider="jev", api_key_env="TYPESAFE_MISSING_KEY")
    with pytest.raises(ProviderUnavailable, match="not set"):
        JevProvider(config).decide(_context())


def test_openai_compatible_provider_parses_json() -> None:
    content = json.dumps(
        {
            "regime": "neutral",
            "confidence": 0.72,
            "target_weights": {"BTC": 0.2, "ETH": 0.1},
            "notes": "test",
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["messages"]
        return httpx.Response(
            200,
            json={
                "model": "local-model",
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    config = AgentConfig(
        provider="openai_compatible",
        endpoint="http://localhost/v1/chat/completions",
        model="local-model",
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    decision = OpenAICompatibleProvider(config, client=client).decide(_context())
    assert decision.model == "local-model"
    assert decision.target_weights == {"BTC": 0.2, "ETH": 0.1}
    assert decision.usage["input_tokens"] == 10


def test_json_parser_handles_fences() -> None:
    assert _parse_json_object('```json\n{"confidence": 0.5}\n```')["confidence"] == 0.5


def _ai_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        data=DataConfig(
            symbols=["A", "B"],
            bars_path=Path("data/bars.parquet"),
            include_recent=False,
        ),
        strategy=StrategyConfig(
            name="trend",
            trend=TrendParams(lookback=20, vol_window=10, vol_target=False),
        ),
        backtest=BacktestConfig(cost_bps=0, slippage_bps=0),
        risk=RiskConfig(
            max_gross=0.8,
            max_net=0.8,
            max_asset_weight=0.2,
            min_cash_weight=0.2,
            max_drawdown=0.5,
            kill_switch_file=Path("artifacts/ai/KILL"),
            state_path=Path("artifacts/ai/risk.json"),
        ),
        broker=BrokerConfig(
            name="paper",
            initial_cash=10_000,
            min_notional=1,
            journal_path=Path("artifacts/ai/orders.sqlite"),
            order_state_path=Path("artifacts/ai/order_state.sqlite"),
            state_path=Path("artifacts/ai/paper.json"),
            performance_path=Path("artifacts/ai/performance.jsonl"),
            heartbeat_path=Path("artifacts/ai/heartbeat.json"),
        ),
        agent=AgentConfig(
            enabled=True,
            provider="deterministic",
            fallback="none",
            paper_only=True,
            include_macro=False,
            include_sentiment=False,
            policy=_policy(),
        ),
    )


def test_ai_pipeline_is_separate_and_runs(tmp_path) -> None:
    from tradingbot.ai.pipeline import run_ai_cycle

    config = _ai_config(tmp_path)
    save_bars(_bars(), tmp_path / config.data.bars_path)
    result = run_ai_cycle(config, root=tmp_path, provider_override="deterministic")
    assert result.status == "ok"
    assert result.fallback is True
    assert (tmp_path / "artifacts/ai/paper.json").exists()
    assert (tmp_path / "artifacts/ai/orders.sqlite").exists()
    assert (tmp_path / "artifacts/ai/reports/latest.json").exists()
    assert list((tmp_path / "artifacts/ai/audit").glob("*.json"))
    report = json.loads((tmp_path / "artifacts/ai/reports/latest.json").read_text())
    assert report["pipeline"] == "ai_agent"
    assert report["fallback"] is True
    assert report["account"]["equity"] > 0


def test_ai_pipeline_uses_provider_decision(tmp_path, monkeypatch) -> None:
    from tradingbot.ai.pipeline import run_ai_cycle

    class FakeProvider:
        name = "jev"

        def decide(self, context):
            return AgentDecision(
                as_of=context["as_of"],
                provider="jev",
                model="jev-test",
                regime="neutral",
                confidence=0.9,
                actions=[
                    AssetDecision(asset="A", action="long", confidence=0.9),
                    AssetDecision(asset="B", action="flat", confidence=0.8),
                ],
            )

    monkeypatch.setattr(
        "tradingbot.ai.pipeline.build_provider", lambda config: FakeProvider()
    )
    config = _ai_config(tmp_path)
    config.agent.provider = "jev"
    save_bars(_bars(), tmp_path / config.data.bars_path)
    result = run_ai_cycle(config, root=tmp_path)
    assert result.status == "ok"
    assert result.provider == "jev"
    assert result.fallback is False
    report = json.loads((tmp_path / "artifacts/ai/reports/latest.json").read_text())
    assert report["provider"] == "jev"
    assert report["model"] == "jev-test"
    assert report["policy"]["target_weights"]["A"] > 0
    assert report["policy"]["target_weights"]["B"] == 0

    from tradingbot.ai.evaluation import build_scorecard

    scorecard = build_scorecard(config, tmp_path)
    assert scorecard["provider"]["decisions"] == 1
    assert scorecard["provider"]["fallback"] == 0
    assert scorecard["status"] == "insufficient_data"


def test_ai_pipeline_refuses_non_paper(tmp_path) -> None:
    from tradingbot.ai.pipeline import run_ai_cycle

    config = _ai_config(tmp_path)
    config.broker.paper = False
    with pytest.raises(PermissionError):
        run_ai_cycle(config, root=tmp_path, provider_override="deterministic")


def test_ai_pipeline_fails_closed_without_provider(tmp_path, monkeypatch) -> None:
    from tradingbot.ai.pipeline import run_ai_cycle

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    config = _ai_config(tmp_path)
    config.agent.provider = "jev"
    config.agent.fallback = "none"
    save_bars(_bars(), tmp_path / config.data.bars_path)
    result = run_ai_cycle(config, root=tmp_path)
    assert result.status == "error"
    report = json.loads((tmp_path / "artifacts/ai/reports/latest.json").read_text())
    assert report["status"] == "error"
    assert report["orders"] == []
    assert "TYPESAFE_API_KEY" in report["alerts"][0]


def _gate_config() -> AppConfig:
    return AppConfig(
        strategy=StrategyConfig(name="trend"),
        risk=RiskConfig(
            max_drawdown=0.3,
            kill_switch_file=Path("artifacts/KILL"),
            state_path=Path("artifacts/risk.json"),
        ),
        broker=BrokerConfig(
            name="alpaca",
            paper=False,
            journal_path=Path("artifacts/orders.sqlite"),
            order_state_path=Path("artifacts/order_state.sqlite"),
            state_path=Path("artifacts/paper.json"),
            performance_path=Path("artifacts/performance.jsonl"),
            heartbeat_path=Path("artifacts/heartbeat.json"),
        ),
    )


def test_live_gate_blocks_empty_evidence(tmp_path) -> None:
    from tradingbot.ops.live_gate import build_live_gate

    gate = build_live_gate(_gate_config(), root=tmp_path)
    assert gate["status"] == "NO_GO"
    assert "walk-forward" in gate["failed"]


def test_live_gate_can_go_when_all_checks_pass(tmp_path, monkeypatch) -> None:
    from tradingbot.ops.live_gate import build_live_gate

    monkeypatch.setenv("LIVE_TRADING", "YES")
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    artifacts = tmp_path / "artifacts"
    (artifacts / "reports").mkdir(parents=True)
    (artifacts / "walkforward_trend.json").write_text(
        json.dumps({"dsr": 0.97, "pbo": 0.10}), encoding="utf-8"
    )
    (artifacts / "reports" / "evaluation_trend.json").write_text(
        json.dumps(
            {
                "tca": {"weighted_slip_bps": 5.0, "fills": 10},
                "data": {"age_days": 1},
                "alerts": [],
            }
        ),
        encoding="utf-8",
    )
    rows = []
    for i in range(56):
        rows.append(
            json.dumps(
                {
                    "timestamp": f"2026-07-{i + 1:02d}T00:00:00+00:00"
                    if i < 31
                    else f"2026-08-{i - 30:02d}T00:00:00+00:00",
                    "equity": 10_000 + i,
                    "cash": 5_000,
                    "gross_exposure": 0.5,
                }
            )
        )
    (artifacts / "performance_trend.jsonl").write_text(
        "\n".join(rows) + "\n", encoding="utf-8"
    )
    gate = build_live_gate(_gate_config(), root=tmp_path)
    assert gate["status"] == "GO", gate


def test_invalid_provider_payload_raises() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "local",
                "choices": [{"message": {"content": "not json"}}],
            },
        )

    config = AgentConfig(
        provider="openai_compatible",
        endpoint="http://localhost/v1/chat/completions",
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(DecisionValidationError):
        OpenAICompatibleProvider(config, client=client).decide(_context())
