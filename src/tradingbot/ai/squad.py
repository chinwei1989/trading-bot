"""An eight-agent, typed-decision squad for the separate AI paper lane.

Every specialist is a separate, role-scoped Jev call. They do not chat freely
and they do not call tools. Each writes a typed memo to a shared blackboard;
later agents receive the memos produced before them.

1. ``macro_analyst`` classifies the macro/regime backdrop.
2. ``trend_analyst`` proposes trend exposure.
3. ``xsmom_analyst`` proposes relative-strength exposure.
4. ``sentiment_analyst`` classifies sentiment, or abstains when no feed exists.
5. ``risk_critic`` approves, reduces, or vetoes the proposals.
6. ``execution_analyst`` checks liquidity/feasibility and may block.
7. ``chair`` synthesises every memo into the final typed decision.

The deterministic policy, risk checks, order manager, and paper broker remain
the only path to an order. Risk vetoes and execution blocks are enforced by
code before the policy layer. This module is paper-only by construction.
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


def _asset_choices(
    answers: dict[str, Any],
    assets: list[str],
    *,
    prefix: str,
    allowed: set[str],
    default: str,
) -> tuple[dict[str, str], dict[str, float]]:
    choices: dict[str, str] = {}
    confidences: dict[str, float] = {}
    for asset in assets:
        choice, confidence = _choice(
            answers, f"{prefix}{asset}", allowed, default
        )
        choices[asset] = choice
        confidences[asset] = confidence
    return choices, confidences


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


def _abstention(
    *,
    agent: str,
    stage: str,
    as_of: str,
    assets: list[str],
    value: str,
    regime: str,
    notes: str,
) -> AgentMemo:
    return AgentMemo(
        agent=agent,
        stage=stage,
        as_of=as_of,
        model="none",
        regime=regime,
        confidence=0.0,
        choices={asset: value for asset in assets},
        choice_confidence={asset: 0.0 for asset in assets},
        notes=notes,
        usage={},
        latency_ms=0.0,
        answers={},
    )


class SquadProvider:
    """Seven typed Jev calls, one bounded paper decision.

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

    def _stage_context(
        self,
        context: dict[str, Any],
        *,
        stage: str,
        memos: dict[str, AgentMemo] | None = None,
    ) -> dict[str, Any]:
        state = dict(context)
        squad: dict[str, Any] = {"stage": stage}
        if memos:
            squad["memos"] = {
                name: memo.to_dict() for name, memo in memos.items()
            }
        state["squad"] = squad
        return state

    def _macro_questions(self) -> dict[str, dict[str, Any]]:
        return {
            "macro_regime": {
                "type": "choice",
                "instructions": (
                    "You are the macro/regime analyst. Classify the broad "
                    "risk backdrop using only the supplied macro and market "
                    "state. Do not select assets, propose weights, or size."
                ),
                "criteria": {
                    "risk_on": (
                        "Macro and breadth are supportive, volatility is "
                        "contained, and risk appetite is healthy."
                    ),
                    "neutral": "Evidence is mixed; no strong risk signal.",
                    "risk_off": (
                        "Macro, breadth, or volatility is defensive; capital "
                        "preservation should dominate."
                    ),
                },
            }
        }

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
                    "using only the supplied state and prior memos. Do not "
                    "propose portfolio weights or make risk decisions."
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
                    f"{asset} using only the supplied state and prior memos. This "
                    "is a research signal, not an order. Do not consider "
                    "execution or position sizing."
                ),
                "criteria": criteria,
            }
        return questions

    def _breakout_questions(self, assets: list[str]) -> dict[str, dict[str, Any]]:
        criteria = {
            "long": (
                "Price has cleared a recent range high with confirming volume; "
                "the breakout is not obviously exhausted."
            ),
            "flat": (
                "No valid range break, the volume confirmation is weak, or the "
                "move looks like a failed breakout."
            ),
        }
        if self.config.policy.allow_short:
            criteria["short"] = (
                "Price has broken a recent range low with confirming volume; "
                "the breakdown is not obviously exhausted."
            )
        questions: dict[str, dict[str, Any]] = {
            "breakout_regime": {
                "type": "choice",
                "instructions": (
                    "You are the breakout analyst. Classify the broad breakout "
                    "environment using only the supplied state and prior memos. "
                    "Do not choose position sizes or execution."
                ),
                "criteria": {
                    "risk_on": "Range breaks are following through across the market.",
                    "neutral": "Breakouts are mixed or unconfirmed.",
                    "risk_off": "Breakdowns dominate or breakouts are failing.",
                },
            }
        }
        for asset in assets:
            questions[f"breakout_{asset}"] = {
                "type": "choice",
                "instructions": (
                    f"You are the breakout analyst. Judge {asset} using recent "
                    "highs/lows, range position, volume and false-break risk. "
                    "Choose long only when a range break is confirmed; choose "
                    "flat when evidence is weak. Do not size the position."
                ),
                "criteria": criteria,
            }
        return questions

    def _xsmom_questions(self, assets: list[str]) -> dict[str, dict[str, Any]]:
        criteria = {
            "long": (
                "The asset is among the strongest relative-strength names and "
                "has positive medium-term momentum."
            ),
            "flat": (
                "The asset is not a relative-strength leader, or its momentum "
                "is too weak or too noisy. Prefer flat outside the leaders."
            ),
        }
        if self.config.policy.allow_short:
            criteria["short"] = (
                "The asset is among the weakest relative-strength names and "
                "has negative medium-term momentum."
            )
        questions: dict[str, dict[str, Any]] = {
            "xs_regime": {
                "type": "choice",
                "instructions": (
                    "You are the cross-sectional momentum analyst. Classify "
                    "whether relative-strength breadth is broadly positive, "
                    "mixed, or broadly negative. Use only the supplied state."
                ),
                "criteria": {
                    "risk_on": "Most assets show positive relative strength.",
                    "neutral": "Leadership is mixed or narrow.",
                    "risk_off": "Most assets show weak relative strength.",
                },
            }
        }
        for asset in assets:
            questions[f"xs_{asset}"] = {
                "type": "choice",
                "instructions": (
                    f"You are the cross-sectional momentum analyst. Compare "
                    f"{asset} with the other assets in the universe. Choose long "
                    "only for relative-strength leaders; choose flat for the "
                    "rest. Do not use absolute trend alone and do not size."
                ),
                "criteria": criteria,
            }
        return questions

    def _sentiment_questions(self, assets: list[str]) -> dict[str, dict[str, Any]]:
        questions: dict[str, dict[str, Any]] = {}
        for asset in assets:
            questions[f"sentiment_{asset}"] = {
                "type": "choice",
                "instructions": (
                    f"You are the sentiment analyst. Classify recent public "
                    f"sentiment for {asset} using only the supplied sentiment "
                    "snapshot. If data is missing, stale, or insufficient, "
                    "choose unavailable. Do not infer sentiment from price and "
                    "do not propose weights."
                ),
                "criteria": {
                    "supportive": "Recent sentiment is clearly constructive.",
                    "neutral": "Recent sentiment is mixed or muted.",
                    "negative": "Recent sentiment is clearly negative.",
                    "unavailable": "No reliable sentiment evidence is available.",
                },
            }
        return questions

    def _risk_questions(self, assets: list[str]) -> dict[str, dict[str, Any]]:
        questions: dict[str, dict[str, Any]] = {
            "risk_regime": {
                "type": "choice",
                "instructions": (
                    "You are the risk critic. Classify the overall risk backdrop "
                    "using the supplied state and all prior memos. Be defensive "
                    "when volatility, drawdown, correlation, breadth, macro, or "
                    "sentiment evidence is poor."
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
                    f"You are the risk critic reviewing the specialist proposals "
                    f"for {asset}. Approve, reduce, or veto the proposed exposure. "
                    "Veto when the evidence is contradictory, concentration or "
                    "volatility is unacceptable, or the proposal would add "
                    "correlated risk. A veto is binding."
                ),
                "criteria": {
                    "approve": "The proposed exposure is acceptable.",
                    "reduce": (
                        "Exposure is acceptable only at a reduced size because of "
                        "volatility, correlation, drawdown, or weak breadth."
                    ),
                    "veto": "Do not hold this exposure; the risk is unacceptable.",
                },
            }
        return questions

    def _execution_questions(self, assets: list[str]) -> dict[str, dict[str, Any]]:
        questions: dict[str, dict[str, Any]] = {
            "execution_regime": {
                "type": "choice",
                "instructions": (
                    "You are the execution/TCA analyst. Judge the operational "
                    "environment using volume, volatility, current positions, "
                    "turnover limits, and the prior risk memo. Do not predict "
                    "returns."
                ),
                "criteria": {
                    "normal": "Liquidity and turnover conditions are workable.",
                    "stressed": (
                        "Liquidity, volatility, or turnover conditions are poor; "
                        "execution should be cautious."
                    ),
                },
            }
        }
        for asset in assets:
            questions[f"execution_{asset}"] = {
                "type": "choice",
                "instructions": (
                    f"You are the execution/TCA analyst reviewing {asset}. "
                    "Judge whether the proposed exposure is operationally "
                    "feasible. Use volume, volatility, current weight, and "
                    "turnover constraints. Allow, reduce, or block. Block when "
                    "liquidity or evidence is unreliable. You cannot place orders."
                ),
                "criteria": {
                    "allow": "Execution is feasible at the proposed exposure.",
                    "reduce": (
                        "Execution is feasible only at reduced size because of "
                        "liquidity, volatility, or turnover."
                    ),
                    "block": "Execution is not acceptable; do not add the exposure.",
                },
            }
        return questions

    def _chair_questions(self, assets: list[str]) -> dict[str, dict[str, Any]]:
        criteria = {
            "long": "Hold a long exposure after considering every memo.",
            "flat": "Hold no exposure after considering every memo.",
        }
        if self.config.policy.allow_short:
            criteria["short"] = "Hold a short exposure after considering every memo."
        questions: dict[str, dict[str, Any]] = {
            "regime": {
                "type": "choice",
                "instructions": (
                    "You are the chair of an eight-agent paper-trading squad. "
                    "Synthesise every memo into one market regime. The risk "
                    "critic's veto and the execution analyst's block are "
                    "binding. Do not invent assets."
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
                    f"{asset}. Use every memo. If the risk critic vetoes the "
                    "asset or the execution analyst blocks it, choose flat. If "
                    "either asks for a reduction, prefer flat unless the "
                    "evidence is strong. Do not size the position; the "
                    "deterministic policy layer owns sizing and caps."
                ),
                "criteria": criteria,
            }
        return questions

    @staticmethod
    def _sentiment_available(context: dict[str, Any]) -> bool:
        block = context.get("sentiment")
        return isinstance(block, dict) and bool(block.get("available"))

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
        memos: dict[str, AgentMemo] = {}
        metas: dict[str, dict[str, Any]] = {}

        # 1. Macro / regime.
        macro_answers, macro_meta = self._ask(
            self._stage_context(context, stage="macro"),
            self._macro_questions(),
        )
        macro_regime, macro_regime_conf = _choice(
            macro_answers,
            "macro_regime",
            {"risk_on", "neutral", "risk_off"},
            "neutral",
        )
        macro_memo = _memo(
            agent="macro_analyst",
            stage="macro",
            as_of=as_of_iso,
            answers=macro_answers,
            meta=macro_meta,
            choices={"regime": macro_regime},
            choice_confidence={"regime": macro_regime_conf},
            regime=macro_regime,
            notes="Macro backdrop only; no asset selection or sizing.",
        )
        memos["macro"] = macro_memo
        metas["macro"] = macro_meta
        board.write_memo(1, macro_memo)

        # 2. Trend.
        trend_answers, trend_meta = self._ask(
            self._stage_context(context, stage="trend", memos=memos),
            self._trend_questions(assets),
        )
        trend_choices, trend_conf = _asset_choices(
            trend_answers,
            assets,
            prefix="trend_",
            allowed={"long", "flat", "short"},
            default="flat",
        )
        if not self.config.policy.allow_short:
            trend_choices = {
                asset: "flat" if choice == "short" else choice
                for asset, choice in trend_choices.items()
            }
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
        memos["trend"] = trend_memo
        metas["trend"] = trend_meta
        board.write_memo(2, trend_memo)

        # 3. Breakout.
        breakout_answers, breakout_meta = self._ask(
            self._stage_context(context, stage="breakout", memos=memos),
            self._breakout_questions(assets),
        )
        breakout_choices, breakout_conf = _asset_choices(
            breakout_answers,
            assets,
            prefix="breakout_",
            allowed={"long", "flat", "short"},
            default="flat",
        )
        if not self.config.policy.allow_short:
            breakout_choices = {
                asset: "flat" if choice == "short" else choice
                for asset, choice in breakout_choices.items()
            }
        breakout_regime, _ = _choice(
            breakout_answers,
            "breakout_regime",
            {"risk_on", "neutral", "risk_off"},
            "neutral",
        )
        breakout_memo = _memo(
            agent="breakout_analyst",
            stage="breakout",
            as_of=as_of_iso,
            answers=breakout_answers,
            meta=breakout_meta,
            choices=breakout_choices,
            choice_confidence=breakout_conf,
            regime=breakout_regime,
            notes="Breakout signal only; no sizing or execution.",
        )
        memos["breakout"] = breakout_memo
        metas["breakout"] = breakout_meta
        board.write_memo(3, breakout_memo)

        # 4. Cross-sectional momentum.
        xs_answers, xs_meta = self._ask(
            self._stage_context(context, stage="xsmom", memos=memos),
            self._xsmom_questions(assets),
        )
        xs_choices, xs_conf = _asset_choices(
            xs_answers,
            assets,
            prefix="xs_",
            allowed={"long", "flat", "short"},
            default="flat",
        )
        if not self.config.policy.allow_short:
            xs_choices = {
                asset: "flat" if choice == "short" else choice
                for asset, choice in xs_choices.items()
            }
        xs_regime, _ = _choice(
            xs_answers,
            "xs_regime",
            {"risk_on", "neutral", "risk_off"},
            "neutral",
        )
        xs_memo = _memo(
            agent="xsmom_analyst",
            stage="xsmom",
            as_of=as_of_iso,
            answers=xs_answers,
            meta=xs_meta,
            choices=xs_choices,
            choice_confidence=xs_conf,
            regime=xs_regime,
            notes="Relative-strength signal only; no sizing or execution.",
        )
        memos["xsmom"] = xs_memo
        metas["xsmom"] = xs_meta
        board.write_memo(4, xs_memo)

        # 5. Sentiment. Abstain without a feed; no paid call for empty data.
        if self._sentiment_available(context):
            sent_answers, sent_meta = self._ask(
                self._stage_context(context, stage="sentiment", memos=memos),
                self._sentiment_questions(assets),
            )
            sent_choices, sent_conf = _asset_choices(
                sent_answers,
                assets,
                prefix="sentiment_",
                allowed={"supportive", "neutral", "negative", "unavailable"},
                default="unavailable",
            )
            sent_memo = _memo(
                agent="sentiment_analyst",
                stage="sentiment",
                as_of=as_of_iso,
                answers=sent_answers,
                meta=sent_meta,
                choices=sent_choices,
                choice_confidence=sent_conf,
                regime="neutral",
                notes=(
                    "Sentiment is advisory only. It cannot size, veto, or "
                    "execute."
                ),
            )
            metas["sentiment"] = sent_meta
        else:
            sent_memo = _abstention(
                agent="sentiment_analyst",
                stage="sentiment",
                as_of=as_of_iso,
                assets=assets,
                value="unavailable",
                regime="unavailable",
                notes=(
                    "No sentiment feed is available; the agent abstained "
                    "without an LLM call."
                ),
            )
        memos["sentiment"] = sent_memo
        board.write_memo(5, sent_memo)

        # 6. Risk critic.
        risk_answers, risk_meta = self._ask(
            self._stage_context(context, stage="risk", memos=memos),
            self._risk_questions(assets),
        )
        risk_choices, risk_conf = _asset_choices(
            risk_answers,
            assets,
            prefix="risk_",
            allowed={"approve", "reduce", "veto"},
            default="veto",
        )
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
        memos["risk"] = risk_memo
        metas["risk"] = risk_meta
        board.write_memo(6, risk_memo)

        # 7. Execution / TCA critic.
        exec_answers, exec_meta = self._ask(
            self._stage_context(context, stage="execution", memos=memos),
            self._execution_questions(assets),
        )
        exec_choices, exec_conf = _asset_choices(
            exec_answers,
            assets,
            prefix="execution_",
            allowed={"allow", "reduce", "block"},
            default="block",
        )
        exec_regime, _ = _choice(
            exec_answers,
            "execution_regime",
            {"normal", "stressed"},
            "stressed",
        )
        exec_memo = _memo(
            agent="execution_analyst",
            stage="execution",
            as_of=as_of_iso,
            answers=exec_answers,
            meta=exec_meta,
            choices=exec_choices,
            choice_confidence=exec_conf,
            regime=exec_regime,
            notes=(
                "Execution review only; blocks are enforced by the squad "
                "guardrail. This agent cannot place orders."
            ),
        )
        memos["execution"] = exec_memo
        metas["execution"] = exec_meta
        board.write_memo(7, exec_memo)

        # 8. Chair: final synthesis.
        chair_answers, chair_meta = self._ask(
            self._stage_context(context, stage="chair", memos=memos),
            self._chair_questions(assets),
        )
        chair_regime, _ = _choice(
            chair_answers,
            "regime",
            {"risk_on", "neutral", "risk_off"},
            "neutral",
        )
        if chair_regime == "risk_on" and (
            macro_regime == "risk_off"
            or breakout_regime == "risk_off"
            or risk_regime == "risk_off"
            or exec_regime == "stressed"
        ):
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
            exec_choice = exec_choices.get(asset, "block")
            reductions = 0
            if risk_choice == "reduce":
                reductions += 1
            if exec_choice == "reduce":
                reductions += 1
            reason = "chair synthesis"
            if risk_choice == "veto" or exec_choice == "block":
                action = "flat"
                confidence = 0.0
                blockers = []
                if risk_choice == "veto":
                    blockers.append("risk critic veto")
                if exec_choice == "block":
                    blockers.append("execution critic block")
                reason = " + ".join(blockers)
            elif reductions:
                confidence *= 0.5**reductions
                reason = (
                    "chair synthesis; risk/execution requested reduced size"
                )
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
                "Final synthesis. Risk vetoes and execution blocks are enforced "
                "by deterministic code before the policy layer."
            ),
        )
        memos["chair"] = chair_memo
        metas["chair"] = chair_meta
        board.write_memo(8, chair_memo)

        model = str(chair_meta.get("model") or macro_meta.get("model") or self.config.model)
        board.write_manifest(
            as_of=as_of_iso,
            provider=self.name,
            model=model,
            agents=[
                "macro_analyst",
                "trend_analyst",
                "breakout_analyst",
                "xsmom_analyst",
                "sentiment_analyst",
                "risk_critic",
                "execution_analyst",
                "chair",
            ],
        )

        total_usage = {"input_tokens": 0, "output_tokens": 0}
        for meta in metas.values():
            usage = dict(meta.get("usage", {}))
            total_usage["input_tokens"] += int(usage.get("input_tokens", 0))
            total_usage["output_tokens"] += int(usage.get("output_tokens", 0))
        total_latency = sum(
            float(meta.get("latency_ms", 0.0)) for meta in metas.values()
        )
        confidence = sum(actionable) / len(actionable) if actionable else 0.0
        relative_board = (
            board.directory.relative_to(root)
            if board.directory.is_relative_to(root)
            else board.directory
        )
        request = {
            "provider": self.name,
            "stages": {
                stage: meta.get("request", {}) for stage, meta in metas.items()
            },
        }
        response = {
            "provider": self.name,
            "model": model,
            "stages": {
                stage: meta.get("response", {}) for stage, meta in metas.items()
            },
        }
        force_rebalance = (
            any(choice == "veto" for choice in risk_choices.values())
            or any(choice == "block" for choice in exec_choices.values())
            or all(action.action == "flat" for action in actions)
        )
        return AgentDecision(
            as_of=as_of,
            provider=self.name,
            model=model,
            regime=chair_regime,  # type: ignore[arg-type]
            confidence=_clamp_confidence(confidence),
            actions=actions,
            force_rebalance=force_rebalance,
            notes=(
                "8-agent typed squad: macro -> trend -> breakout -> xsmom -> "
                "sentiment -> risk -> execution -> chair. Risk vetoes and execution blocks "
                f"force a rebalance. Blackboard: {relative_board}."
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
                    name: memo.to_dict() for name, memo in memos.items()
                },
            },
        )
