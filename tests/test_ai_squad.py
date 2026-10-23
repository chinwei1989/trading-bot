from __future__ import annotations

from pathlib import Path

from tradingbot.ai.decision import ProviderUnavailable
from tradingbot.ai.providers import build_provider
from tradingbot.ai.squad import SquadProvider
from tradingbot.config import AgentConfig, AgentPolicyConfig


def _context() -> dict:
    return {
        "as_of": "2026-10-24T00:00:00+00:00",
        "universe": ["BTC", "ETH"],
        "assets": {
            "BTC": {"trend_up": True, "return_60d": 0.2, "vol_60d": 0.4},
            "ETH": {"trend_up": True, "return_60d": 0.1, "vol_60d": 0.6},
        },
        "portfolio": {
            "cash": 10_000.0,
            "equity": 10_000.0,
            "positions": {},
            "current_weights": {"BTC": 0.0, "ETH": 0.0},
        },
        "market": {"breadth_above_sma200": 0.75, "data_age_days": 1},
        "constraints": {},
    }


def _policy() -> AgentPolicyConfig:
    return AgentPolicyConfig(
        max_gross=0.8,
        max_asset_weight=0.2,
        min_cash_weight=0.2,
        max_turnover=0.5,
        min_confidence=0.55,
        allow_short=False,
    )


def _config() -> AgentConfig:
    return AgentConfig(
        provider="squad",
        artifacts_dir=Path("artifacts/ai_squad"),
        policy=_policy(),
    )


class FakeSquadLLM:
    """Return typed answers for each stage and record what each agent saw."""

    def __init__(self, answers: dict[str, dict] | None = None):
        self.answers = answers or {
            "trend": {
                "trend_regime": {"choice": "risk_on", "confidence": 0.8},
                "trend_BTC": {"choice": "long", "confidence": 0.9},
                "trend_ETH": {"choice": "long", "confidence": 0.8},
            },
            "risk": {
                "risk_regime": {"choice": "neutral", "confidence": 0.7},
                "risk_BTC": {"choice": "veto", "confidence": 0.9},
                "risk_ETH": {"choice": "reduce", "confidence": 0.8},
            },
            "chair": {
                "regime": {"choice": "risk_on", "confidence": 0.8},
                "BTC": {"choice": "long", "confidence": 0.9},
                "ETH": {"choice": "long", "confidence": 0.9},
            },
        }
        self.calls: list[tuple[dict, dict]] = []

    def ask(self, context: dict, questions: dict) -> tuple[dict, dict]:
        self.calls.append((context, questions))
        keys = set(questions)
        if "trend_BTC" in keys:
            stage = "trend"
        elif "risk_BTC" in keys:
            stage = "risk"
        else:
            stage = "chair"
        return self.answers[stage], {
            "model": "jev-test",
            "usage": {"input_tokens": 100, "output_tokens": 10},
            "latency_ms": 12.5,
            "request": {"stage": stage},
            "response": {"stage": stage},
        }


def test_three_agent_squad_writes_blackboard_and_enforces_risk_veto(tmp_path: Path) -> None:
    llm = FakeSquadLLM()
    provider = SquadProvider(_config(), llm=llm, root=tmp_path)
    decision = provider.decide(_context())

    assert decision.provider == "squad"
    assert decision.model == "jev-test"
    assert decision.fallback is False
    actions = decision.action_map()
    assert actions["BTC"].action == "flat"
    assert actions["BTC"].reason == "risk critic veto"
    assert actions["ETH"].action == "long"
    assert actions["ETH"].confidence == 0.45
    assert decision.usage == {"input_tokens": 300, "output_tokens": 30}
    assert decision.latency_ms == 37.5
    assert decision.raw["run_id"]

    board = tmp_path / "artifacts" / "ai_squad" / "squad" / str(decision.raw["run_id"])
    assert (board / "01_trend.json").exists()
    assert (board / "02_risk.json").exists()
    assert (board / "03_chair.json").exists()
    manifest = (board / "manifest.json").read_text(encoding="utf-8")
    assert "trend_analyst" in manifest
    assert "risk_critic" in manifest
    assert "chair" in manifest

    # Each stage sees the memos produced by the earlier stages.
    assert len(llm.calls) == 3
    risk_state = llm.calls[1][0]
    chair_state = llm.calls[2][0]
    assert risk_state["squad"]["trend_memo"]["agent"] == "trend_analyst"
    assert chair_state["squad"]["trend_memo"]["agent"] == "trend_analyst"
    assert chair_state["squad"]["risk_memo"]["agent"] == "risk_critic"
    assert chair_state["squad"]["risk_memo"]["choices"]["BTC"] == "veto"


def test_squad_fails_closed_when_risk_answers_are_missing(tmp_path: Path) -> None:
    answers = {
        "trend": {
            "trend_regime": {"choice": "risk_on", "confidence": 0.8},
            "trend_BTC": {"choice": "long", "confidence": 0.9},
            "trend_ETH": {"choice": "long", "confidence": 0.8},
        },
        "risk": {},
        "chair": {
            "regime": {"choice": "risk_on", "confidence": 0.8},
            "BTC": {"choice": "long", "confidence": 0.9},
            "ETH": {"choice": "long", "confidence": 0.9},
        },
    }
    provider = SquadProvider(_config(), llm=FakeSquadLLM(answers), root=tmp_path)
    decision = provider.decide(_context())
    assert {action.asset: action.action for action in decision.actions} == {
        "BTC": "flat",
        "ETH": "flat",
    }
    assert all(action.reason == "risk critic veto" for action in decision.actions)


def test_squad_requires_a_key_when_no_llm_is_injected(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("TYPESAFE_MISSING_SQUAD_KEY", raising=False)
    config = _config()
    config.api_key_env = "TYPESAFE_MISSING_SQUAD_KEY"
    provider = SquadProvider(config, root=tmp_path)
    try:
        provider.decide(_context())
    except ProviderUnavailable as exc:
        assert "not set" in str(exc)
    else:
        raise AssertionError("expected ProviderUnavailable")


def test_build_provider_creates_squad() -> None:
    provider = build_provider(_config())
    assert provider.name == "squad"
