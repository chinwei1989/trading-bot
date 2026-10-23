"""A three-agent, typed-decision squad for the separate AI paper lane.

The squad is deliberately small and structured:

1. ``trend_analyst`` proposes long/flat exposure from the supplied state.
2. ``risk_critic`` reviews those proposals and may approve, reduce, or veto.
3. ``chair`` synthesises both memos and returns the final typed decision.

Each stage is a separate Jev request with a narrow question set. The agents do
not chat freely and do not call tools. Their memos are written to a shared
blackboard under ``artifacts/<ai_dir>/squad/<run_id>/``. The existing
deterministic policy, risk checks, order manager, and paper broker remain the
only path to an order.

This module is paper-only by construction: it produces a typed
:class:`~tradingbot.ai.decision.AgentDecision`; it never receives broker
credentials and never executes an order.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from tradingbot.ai.decision import (
    AgentDecision,
    AssetDecision,
    DecisionValidationError,
    ProviderError,
)
from tradingbot.ai.providers import JevProvider
from tradingbot.config import AgentConfig


class TypedQuestionProvider(Protocol):
    """The small part of the Jev adapter the squad needs."""

    def ask(
        self,
        context: dict[str, Any],
        questions: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any]]: ...


@dataclass(frozen=True)
class AgentMemo:
    """One agent's typed contribution to the shared blackboard."""

    agent: str
    stage: str
    as_of: str
    model: str
    regime: str
    confidence: float
    choices: dict[str, str]
    choice_confidence: dict[str, float]
    notes: str
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: float = 0.0
    answers: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SquadBlackboard:
    """Persist each agent memo so the squad's information sharing is auditable."""

    def __init__(self, root: Path, run_id: str | None = None):
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        self.run_id = run_id or f"{stamp}_{uuid.uuid4().hex[:8]}"
        self.directory = root / "squad" / self.run_id
        self.directory.mkdir(parents=True, exist_ok=True)
        self._stages: dict[str, str] = {}

    def write_memo(self, index: int, memo: AgentMemo) -> Path:
        path = self.directory / f"{index:02d}_{memo.stage}.json"
        path.write_text(
            json.dumps(memo.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )
        self._stages[memo.stage] = path.name
        return path

    def write_manifest(
        self,
        *,
        as_of: str,
        provider: str,
        model: str,
        agents: list[str],
    ) -> Path:
        path = self.directory / "manifest.json"
        payload = {
            "run_id": self.run_id,
            "as_of": as_of,
            "provider": provider,
            "model": model,
            "agents": agents,
            "memos": dict(self._stages),
            "created_at": datetime.now(UTC).isoformat(),
            "paper_only": True,
        }
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path


def _as_of(context: dict[str, Any]) -> datetime:
    value = context.get("as_of")
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return datetime.now(UTC)
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _clamp_confidence(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


def _choice(
    answers: dict[str, Any],
    key: str,
    allowed: set[str],
    default: str,
) -> tuple[str, float]:
    answer = answers.get(key)
    if not isinstance(answer, dict):
        return default, 0.0
    value = str(answer.get("choice", default))
    if value not in allowed:
        value = default
    return value, _clamp_confidence(answer.get("confidence"), 0.0)


def _memo(
    *,
    agent: str,
    stage: str,
    as_of: str,
    answers: dict[str, Any],
    meta: dict[str, Any],
    choices: dict[str, str],
    choice_confidence: dict[str, float],
    regime: str,
    notes: str,
) -> AgentMemo:
    confidence_values = [
        value for value in choice_confidence.values() if value > 0.0
    ]
    confidence = (
        sum(confidence_values) / len(confidence_values)
        if confidence_values
        else 0.0
    )
    return AgentMemo(
        agent=agent,
        stage=stage,
        as_of=as_of,
        model=str(meta.get("model", "")),
        regime=regime,
        confidence=confidence,
        choices=choices,
        choice_confidence=choice_confidence,
        notes=notes,
        usage={
            str(key): int(value)
            for key, value in dict(meta.get("usage", {})).items()
        },
        latency_ms=float(meta.get("latency_ms", 0.0)),
        answers=answers,
    )


class SquadProvider:
    """Three typed Jev calls, one bounded paper decision.

    The provider is intentionally a ``DecisionProvider`` so the existing AI
    pipeline can own state, policy, risk, execution, reports, and audit.
    """

    name = "squad"

    def __init__(
        self,
        config: AgentConfig,
        *,
        llm: TypedQuestionProvider | None = None,
        root: Path | None = None,
    ):
        self.config = config
        self.llm = llm or JevProvider(config)
        self.root = root or Path.cwd()

    def _ask(
        self,
        context: dict[str, Any],
        questions: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        # Internal routing keys are not model input.
        state = {
            key: value
            for key, value in context.items()
            if not key.startswith("_squad_")
        }
        answers, meta = self.llm.ask(state, questions)
        if not isinstance(answers, dict):
            raise ProviderError("squad agent returned no answers")
        return answers, meta

    def _trend_questions(self, assets: list[str]) -> dict[str, dict[str, Any]]:
        criteria = {
            "long": (
                "Price is above the long-term trend, medium-term momentum is "
                "positive, and the trend is not clearly overextended."
            ),
            "flat": (
                "Trend is mixed, negative, or too weak to justify exposure. "
                "Prefer flat when the evidence is ambiguous."
            ),
        }
        if self.config.policy.allow_short:
            criteria["short"] = (
                "Price is below the long-term trend, medium-term momentum is "
                "negative, and the trend is not clearly overextended."
            )
        questions: dict[str, dict[str, Any]] = {
            "trend_regime": {
                "type": "choice",
                "instructions": (
                    "You are the trend analyst. Classify the broad crypto trend "
                    "using only the supplied state. Do not propose portfolio "
                    "weights or make risk decisions."
                ),
                "criteria": {
                    "risk_on": "Broad uptrend with positive medium-term momentum.",
                    "neutral": "Mixed or range-bound trend with no clear direction.",
                    "risk_off": "Broad downtrend with negative medium-term momentum.",
                },
            }
        }
        for asset in assets:
            questions[f"trend_{asset}"] = {
                "type": "choice",
                "instructions": (
                    f"You are the trend analyst. Choose the trend exposure for "
                    f"{asset} using only the supplied state. This is a research "
                    "signal, not an order. Do not consider execution or position "
                    "sizing."
                ),
                "criteria": criteria,
            }
        return questions

    def _risk_questions(self, assets: list[str]) -> dict[str, dict[str, Any]]:
        questions: dict[str, dict[str, Any]] = {
            "risk_regime": {
                "type": "choice",
                "instructions": (
                    "You are the risk critic. Classify the overall risk backdrop "
                    "using only the supplied state and the trend memo. Be "
                    "defensive when volatility, drawdown, correlation, breadth, "
                    "or macro evidence is poor."
                ),
                "criteria": {
                    "risk_on": "Risk is contained and the backdrop supports exposure.",
                    "neutral": "Mixed risk; allow only normal, constrained exposure.",
                    "risk_off": "Risk is elevated; capital preservation dominates.",
                },
            }
        }
        for asset in assets:
            questions[f"risk_{asset}"] = {
                "type": "choice",
                "instructions": (
                    f"You are the risk critic reviewing the trend analyst's "
                    f"proposal for {asset}. Approve, reduce, or veto the proposed "
                    "exposure. Veto when the evidence is contradictory, "
                    "concentration or volatility is unacceptable, or the proposal "
                    "would add correlated risk. A veto is binding."
                ),
                "criteria": {
                    "approve": "The proposed trend exposure is acceptable.",
                    "reduce": (
                        "Exposure is acceptable only at a reduced size because of "
                        "volatility, correlation, drawdown, or weak breadth."
                    ),
                    "veto": "Do not hold this exposure; the risk is unacceptable.",
                },
            }
        return questions

    def _chair_questions(self, assets: list[str]) -> dict[str, dict[str, Any]]:
        criteria = {
            "long": "Hold a long exposure after considering both memos.",
            "flat": "Hold no exposure after considering both memos.",
        }
        if self.config.policy.allow_short:
            criteria["short"] = "Hold a short exposure after considering both memos."
        questions: dict[str, dict[str, Any]] = {
            "regime": {
                "type": "choice",
                "instructions": (
                    "You are the chair of a three-agent paper-trading squad. "
                    "Synthesise the trend and risk memos into one market regime. "
                    "The risk critic's veto is binding. Do not invent assets."
                ),
                "criteria": {
                    "risk_on": "The combined evidence supports normal risk.",
                    "neutral": "The combined evidence supports cautious risk.",
                    "risk_off": "The combined evidence calls for capital preservation.",
                },
            }
        }
        for asset in assets:
            questions[asset] = {
                "type": "choice",
                "instructions": (
                    f"You are the chair. Choose the final paper exposure for "
                    f"{asset}. Use the trend memo and the risk critic's review. "
                    "If the risk critic vetoes the asset, choose flat. If the "
                    "risk critic asks for a reduction, prefer flat unless the "
                    "evidence is strong. Do not size the position; the "
                    "deterministic policy layer owns sizing and caps."
                ),
                "criteria": criteria,
            }
        return questions

    def _stage_context(
        self,
        context: dict[str, Any],
        *,
        stage: str,
        trend: AgentMemo | None = None,
        risk: AgentMemo | None = None,
    ) -> dict[str, Any]:
        state = dict(context)
        squad: dict[str, Any] = {"stage": stage}
        if trend is not None:
            squad["trend_memo"] = trend.to_dict()
        if risk is not None:
            squad["risk_memo"] = risk.to_dict()
        state["squad"] = squad
        return state

    def decide(self, context: dict[str, Any]) -> AgentDecision:
        assets = list(context.get("universe", []))
        if not assets:
            raise DecisionValidationError("squad context has no universe")

        as_of = _as_of(context)
        as_of_iso = as_of.isoformat()
        root = Path(str(context.get("_squad_root", self.root)))
        artifacts_dir = (
            self.config.artifacts_dir
            if self.config.artifacts_dir.is_absolute()
            else root / self.config.artifacts_dir
        )
        board = SquadBlackboard(artifacts_dir)

        trend_context = self._stage_context(context, stage="trend")
        trend_answers, trend_meta = self._ask(
            trend_context, self._trend_questions(assets)
        )
        trend_choices: dict[str, str] = {}
        trend_conf: dict[str, float] = {}
        for asset in assets:
            choice, confidence = _choice(
                trend_answers,
                f"trend_{asset}",
                {"long", "flat", "short"},
                "flat",
            )
            if choice == "short" and not self.config.policy.allow_short:
                choice = "flat"
            trend_choices[asset] = choice
            trend_conf[asset] = confidence
        trend_regime, _ = _choice(
            trend_answers,
            "trend_regime",
            {"risk_on", "neutral", "risk_off"},
            "neutral",
        )
        trend_memo = _memo(
            agent="trend_analyst",
            stage="trend",
            as_of=as_of_iso,
            answers=trend_answers,
            meta=trend_meta,
            choices=trend_choices,
            choice_confidence=trend_conf,
            regime=trend_regime,
            notes="Trend signal only; no sizing or execution.",
        )
        board.write_memo(1, trend_memo)

        risk_context = self._stage_context(
            context, stage="risk", trend=trend_memo
        )
        risk_answers, risk_meta = self._ask(
            risk_context, self._risk_questions(assets)
        )
        risk_choices: dict[str, str] = {}
        risk_conf: dict[str, float] = {}
        for asset in assets:
            choice, confidence = _choice(
                risk_answers,
                f"risk_{asset}",
                {"approve", "reduce", "veto"},
                "veto",
            )
            risk_choices[asset] = choice
            risk_conf[asset] = confidence
        risk_regime, _ = _choice(
            risk_answers,
            "risk_regime",
            {"risk_on", "neutral", "risk_off"},
            "risk_off",
        )
        risk_memo = _memo(
            agent="risk_critic",
            stage="risk",
            as_of=as_of_iso,
            answers=risk_answers,
            meta=risk_meta,
            choices=risk_choices,
            choice_confidence=risk_conf,
            regime=risk_regime,
            notes="Risk review only; vetoes are enforced by the squad guardrail.",
        )
        board.write_memo(2, risk_memo)

        chair_context = self._stage_context(
            context, stage="chair", trend=trend_memo, risk=risk_memo
        )
        chair_answers, chair_meta = self._ask(
            chair_context, self._chair_questions(assets)
        )
        chair_regime, _ = _choice(
            chair_answers,
            "regime",
            {"risk_on", "neutral", "risk_off"},
            "neutral",
        )
        if risk_regime == "risk_off" and chair_regime == "risk_on":
            chair_regime = "neutral"

        actions: list[AssetDecision] = []
        actionable: list[float] = []
        for asset in assets:
            action, confidence = _choice(
                chair_answers, asset, {"long", "flat", "short"}, "flat"
            )
            if action == "short" and not self.config.policy.allow_short:
                action = "flat"
                confidence = 0.0
            risk_choice = risk_choices.get(asset, "veto")
            reason = "chair synthesis"
            if risk_choice == "veto":
                action = "flat"
                confidence = 0.0
                reason = "risk critic veto"
            elif risk_choice == "reduce":
                confidence *= 0.5
                reason = "chair synthesis; risk critic requested reduced size"
            actions.append(
                AssetDecision(
                    asset=asset,
                    action=action,  # type: ignore[arg-type]
                    confidence=_clamp_confidence(confidence),
                    reason=reason,
                )
            )
            if action != "flat" and confidence >= self.config.policy.min_confidence:
                actionable.append(_clamp_confidence(confidence))

        chair_choices = {action.asset: str(action.action) for action in actions}
        chair_conf = {action.asset: action.confidence for action in actions}
        chair_memo = _memo(
            agent="chair",
            stage="chair",
            as_of=as_of_iso,
            answers=chair_answers,
            meta=chair_meta,
            choices=chair_choices,
            choice_confidence=chair_conf,
            regime=chair_regime,
            notes=(
                "Final synthesis. Risk vetoes and reductions are enforced by "
                "deterministic code before the policy layer."
            ),
        )
        board.write_memo(3, chair_memo)

        model = str(chair_meta.get("model") or trend_meta.get("model") or self.config.model)
        board.write_manifest(
            as_of=as_of_iso,
            provider=self.name,
            model=model,
            agents=["trend_analyst", "risk_critic", "chair"],
        )

        total_usage = {"input_tokens": 0, "output_tokens": 0}
        for meta in (trend_meta, risk_meta, chair_meta):
            usage = dict(meta.get("usage", {}))
            total_usage["input_tokens"] += int(usage.get("input_tokens", 0))
            total_usage["output_tokens"] += int(usage.get("output_tokens", 0))
        total_latency = sum(
            float(meta.get("latency_ms", 0.0))
            for meta in (trend_meta, risk_meta, chair_meta)
        )
        confidence = (
            sum(actionable) / len(actionable) if actionable else 0.0
        )
        relative_board = (
            board.directory.relative_to(root)
            if board.directory.is_relative_to(root)
            else board.directory
        )
        request = {
            "provider": self.name,
            "stages": {
                "trend": trend_meta.get("request", {}),
                "risk": risk_meta.get("request", {}),
                "chair": chair_meta.get("request", {}),
            },
        }
        response = {
            "provider": self.name,
            "model": model,
            "stages": {
                "trend": trend_meta.get("response", {}),
                "risk": risk_meta.get("response", {}),
                "chair": chair_meta.get("response", {}),
            },
        }
        return AgentDecision(
            as_of=as_of,
            provider=self.name,
            model=model,
            regime=chair_regime,  # type: ignore[arg-type]
            confidence=_clamp_confidence(confidence),
            actions=actions,
            notes=(
                "3-agent typed squad: trend_analyst -> risk_critic -> chair. "
                f"Blackboard: {relative_board}."
            ),
            usage=total_usage,
            latency_ms=total_latency,
            fallback=False,
            raw={
                "request": request,
                "response": response,
                "run_id": board.run_id,
                "blackboard": str(relative_board),
                "memos": {
                    "trend": trend_memo.to_dict(),
                    "risk": risk_memo.to_dict(),
                    "chair": chair_memo.to_dict(),
                },
            },
        )
