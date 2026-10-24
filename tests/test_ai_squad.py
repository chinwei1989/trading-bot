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
            "BTC": {
                "trend_up": True,
                "return_60d": 0.2,
                "vol_60d": 0.4,
                "volume_z_20d": 0.8,
            },
            "ETH": {
                "trend_up": True,
                "return_60d": 0.1,
                "vol_60d": 0.6,
                "volume_z_20d": -1.2,
            },
        },
        "portfolio": {
            "cash": 10_000.0,
            "equity": 10_000.0,
            "positions": {},
            "current_weights": {"BTC": 0.0, "ETH": 0.0},
        },
        "market": {"breadth_above_sma200": 0.75, "data_age_days": 1},
        "macro": {
            "available": True,
            "risk_score": -0.2,
            "interpretation": "risk_on",
            "series": {"VIXCLS": {"last": 15.0, "z_1y": -0.5}},
        },
        "sentiment": {
            "available": True,
            "window_days": 7,
            "assets": {
                "BTC": {"mean": 0.4, "count": 12},
                "ETH": {"mean": 0.0, "count": 7},
            },
        },
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
            "macro": {
                "macro_regime": {"choice": "risk_on", "confidence": 0.8},
            },
            "trend": {
                "trend_regime": {"choice": "risk_on", "confidence": 0.8},
                "trend_BTC": {"choice": "long", "confidence": 0.9},
                "trend_ETH": {"choice": "long", "confidence": 0.8},
            },
            "breakout": {
                "breakout_regime": {"choice": "neutral", "confidence": 0.7},
                "breakout_BTC": {"choice": "long", "confidence": 0.8},
                "breakout_ETH": {"choice": "flat", "confidence": 0.6},
            },
            "xsmom": {
                "xs_regime": {"choice": "risk_on", "confidence": 0.8},
                "xs_BTC": {"choice": "long", "confidence": 0.85},
                "xs_ETH": {"choice": "flat", "confidence": 0.7},
            },
            "sentiment": {
                "sentiment_BTC": {"choice": "supportive", "confidence": 0.7},
                "sentiment_ETH": {"choice": "neutral", "confidence": 0.6},
            },
            "risk": {
                "risk_regime": {"choice": "neutral", "confidence": 0.7},
                "risk_BTC": {"choice": "veto", "confidence": 0.9},
                "risk_ETH": {"choice": "approve", "confidence": 0.8},
            },
            "execution": {
                "execution_regime": {"choice": "normal", "confidence": 0.8},
                "execution_BTC": {"choice": "allow", "confidence": 0.8},
                "execution_ETH": {"choice": "reduce", "confidence": 0.7},
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
        if "macro_regime" in keys:
            stage = "macro"
        elif "trend_BTC" in keys:
            stage = "trend"
        elif "breakout_BTC" in keys:
            stage = "breakout"
        elif "xs_BTC" in keys:
            stage = "xsmom"
        elif "sentiment_BTC" in keys:
            stage = "sentiment"
        elif "risk_BTC" in keys:
            stage = "risk"
        elif "execution_BTC" in keys:
            stage = "execution"
        else:
            stage = "chair"
        return self.answers[stage], {
            "model": "jev-test",
            "usage": {"input_tokens": 100, "output_tokens": 10},
            "latency_ms": 12.5,
            "request": {"stage": stage},
            "response": {"stage": stage},
        }


def test_full_squad_writes_blackboard_and_enforces_guardrails(tmp_path: Path) -> None:
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
    assert decision.force_rebalance is True
    assert decision.usage == {"input_tokens": 800, "output_tokens": 80}
    assert decision.latency_ms == 100.0
    assert decision.raw["run_id"]

    board = tmp_path / "artifacts" / "ai_squad" / "squad" / str(decision.raw["run_id"])
    for name in (
        "01_macro.json",
        "02_trend.json",
        "03_breakout.json",
        "04_xsmom.json",
        "05_sentiment.json",
        "06_risk.json",
        "07_execution.json",
        "08_chair.json",
        "manifest.json",
    ):
        assert (board / name).exists(), name

    manifest = (board / "manifest.json").read_text(encoding="utf-8")
    assert "macro_analyst" in manifest
    assert "breakout_analyst" in manifest
    assert "xsmom_analyst" in manifest
    assert "sentiment_analyst" in manifest
    assert "execution_analyst" in manifest
    assert "risk_critic" in manifest
    assert "chair" in manifest

    assert len(llm.calls) == 8
    risk_state = llm.calls[5][0]
    exec_state = llm.calls[6][0]
    chair_state = llm.calls[7][0]
    assert set(risk_state["squad"]["memos"]) == {
        "macro",
        "trend",
        "breakout",
        "xsmom",
        "sentiment",
    }
    assert set(exec_state["squad"]["memos"]) == {
        "macro",
        "trend",
        "breakout",
        "xsmom",
        "sentiment",
        "risk",
    }
    assert set(chair_state["squad"]["memos"]) == {
        "macro",
        "trend",
        "breakout",
        "xsmom",
        "sentiment",
        "risk",
        "execution",
    }
    assert chair_state["squad"]["memos"]["risk"]["choices"]["BTC"] == "veto"


def test_execution_block_flattens_a_chair_long(tmp_path: Path) -> None:
    answers = FakeSquadLLM().answers
    answers["risk"]["risk_BTC"] = {"choice": "approve", "confidence": 0.8}
    answers["risk"]["risk_ETH"] = {"choice": "approve", "confidence": 0.8}
    answers["execution"]["execution_BTC"] = {"choice": "allow", "confidence": 0.8}
    answers["execution"]["execution_ETH"] = {"choice": "block", "confidence": 0.9}
    provider = SquadProvider(_config(), llm=FakeSquadLLM(answers), root=tmp_path)
    decision = provider.decide(_context())
    actions = decision.action_map()
    assert actions["BTC"].action == "long"
    assert actions["ETH"].action == "flat"
    assert actions["ETH"].reason == "execution critic block"
    assert decision.force_rebalance is True


def test_squad_fails_closed_when_risk_answers_are_missing(tmp_path: Path) -> None:
    answers = FakeSquadLLM().answers
    answers["risk"] = {}
    provider = SquadProvider(_config(), llm=FakeSquadLLM(answers), root=tmp_path)
    decision = provider.decide(_context())
    assert {action.asset: action.action for action in decision.actions} == {
        "BTC": "flat",
        "ETH": "flat",
    }
    assert all(action.reason == "risk critic veto" for action in decision.actions)
    assert decision.force_rebalance is True


def test_sentiment_abstains_without_a_feed(tmp_path: Path) -> None:
    context = _context()
    context["sentiment"] = {"available": False}
    llm = FakeSquadLLM()
    provider = SquadProvider(_config(), llm=llm, root=tmp_path)
    decision = provider.decide(context)
    assert len(llm.calls) == 7
    board = tmp_path / "artifacts" / "ai_squad" / "squad" / str(decision.raw["run_id"])
    import json

    memo = json.loads((board / "05_sentiment.json").read_text(encoding="utf-8"))
    assert memo["model"] == "none"
    assert set(memo["choices"].values()) == {"unavailable"}
    assert "without an LLM call" in memo["notes"]


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
