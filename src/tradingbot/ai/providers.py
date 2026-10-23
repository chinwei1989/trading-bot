"""Decision providers.

Jev is a typed-decision API. The local provider speaks the OpenAI-compatible
chat-completions protocol (Ollama, vLLM, LM Studio, or a hosted endpoint).
The deterministic provider exists only as an explicitly labelled fallback.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from tradingbot.ai.decision import (
    AgentDecision,
    AssetDecision,
    DecisionValidationError,
    ProviderError,
    ProviderUnavailable,
)
from tradingbot.config import AgentConfig


class DecisionProvider(Protocol):
    name: str

    def decide(self, context: dict[str, Any]) -> AgentDecision: ...


def _as_of(context: dict[str, Any]) -> datetime:
    value = context.get("as_of")
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return datetime.now(UTC)
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class JevProvider:
    """TypeSafe Jev System One decision provider.

    Jev returns typed answers, not generated text. The policy layer converts
    its per-asset choices into constrained weights.
    """

    name = "jev"

    def __init__(self, config: AgentConfig, client: httpx.Client | None = None):
        self.config = config
        self.client = client
        self.api_key = os.getenv(config.api_key_env)

    def _questions(self, assets: list[str]) -> dict[str, dict[str, Any]]:
        questions: dict[str, dict[str, Any]] = {
            "regime": {
                "type": "choice",
                "instructions": (
                    "Classify the overall market regime for a risk-managed crypto "
                    "portfolio using only the supplied state."
                ),
                "criteria": {
                    "risk_on": "Broad uptrend, contained volatility, supportive macro.",
                    "neutral": "Mixed trend, normal volatility, no clear risk appetite.",
                    "risk_off": "Broad weakness, rising volatility, or defensive macro.",
                },
            }
        }
        criteria = {
            "long": "Positive trend and acceptable risk; own this asset.",
            "flat": "No clear edge or unfavorable risk; hold no exposure.",
        }
        if self.config.policy.allow_short:
            criteria["short"] = "Clear negative trend and acceptable risk; short this asset."
        for asset in assets:
            questions[asset] = {
                "type": "choice",
                "instructions": (
                    f"Choose the appropriate exposure for {asset}. Use only the "
                    "state. Prefer flat when evidence is weak."
                ),
                "criteria": criteria,
            }
        return questions

    def ask(
        self,
        context: dict[str, Any],
        questions: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Ask Jev a caller-defined typed question set.

        The multi-agent squad uses this to give each specialist a narrow
        question set. Jev still returns typed choices, not generated chat.
        """
        if not self.api_key:
            raise ProviderUnavailable(
                f"{self.config.api_key_env} is not set; Jev is not configured"
            )
        payload = {
            "model": self.config.model,
            "state": context,
            "questions": questions,
        }
        started = time.perf_counter()
        client = self.client or httpx.Client(timeout=self.config.timeout_seconds)
        close_client = self.client is None
        try:
            response = self._post(client, payload)
        finally:
            if close_client:
                client.close()
        latency_ms = (time.perf_counter() - started) * 1000.0
        data = response.json()
        answers = data.get("answers")
        if not isinstance(answers, dict):
            raise ProviderError("Jev response has no answers object")
        return answers, {
            "model": str(data.get("model", self.config.model)),
            "usage": {
                "input_tokens": int(data.get("usage", {}).get("input_tokens", 0)),
                "output_tokens": int(data.get("usage", {}).get("output_tokens", 0)),
            },
            "latency_ms": latency_ms,
            "request": payload,
            "response": data,
        }

    def decide(self, context: dict[str, Any]) -> AgentDecision:
        if not self.api_key:
            raise ProviderUnavailable(
                f"{self.config.api_key_env} is not set; Jev is not configured"
            )
        assets = list(context.get("universe", []))
        if not assets:
            raise DecisionValidationError("context has no universe")
        payload = {
            "model": self.config.model,
            "state": context,
            "questions": self._questions(assets),
        }
        started = time.perf_counter()
        client = self.client or httpx.Client(timeout=self.config.timeout_seconds)
        close_client = self.client is None
        try:
            response = self._post(client, payload)
        finally:
            if close_client:
                client.close()
        latency_ms = (time.perf_counter() - started) * 1000.0
        data = response.json()
        answers = data.get("answers")
        if not isinstance(answers, dict):
            raise ProviderError("Jev response has no answers object")

        regime_answer = answers.get("regime", {})
        regime = str(regime_answer.get("choice", "neutral"))
        if regime not in {"risk_on", "neutral", "risk_off"}:
            regime = "neutral"
        regime_conf = float(regime_answer.get("confidence", 0.5) or 0.5)

        actions: list[AssetDecision] = []
        confidences: list[float] = []
        for asset in assets:
            answer = answers.get(asset)
            if not isinstance(answer, dict):
                continue
            choice = str(answer.get("choice", "flat"))
            if choice not in {"long", "flat", "short"}:
                choice = "flat"
            confidence = float(answer.get("confidence", 0.5) or 0.0)
            confidence = max(0.0, min(1.0, confidence))
            actions.append(
                AssetDecision(
                    asset=asset,
                    action=choice,  # type: ignore[arg-type]
                    confidence=confidence,
                    reason="Jev typed choice",
                )
            )
            confidences.append(confidence)
        if not actions:
            raise ProviderError("Jev returned no usable per-asset answers")

        # Judge the decision by the actions that could actually trade, not by
        # the confidence of flat/non-actionable assets. Flat assets with high
        # confidence should not dilute a strong long signal.
        actionable = [
            action.confidence
            for action in actions
            if action.action != "flat"
            and action.confidence >= self.config.policy.min_confidence
        ]
        confidence = (
            min(regime_conf, sum(actionable) / len(actionable)) if actionable else 0.0
        )
        return AgentDecision(
            as_of=_as_of(context),
            provider=self.name,
            model=str(data.get("model", self.config.model)),
            regime=regime,  # type: ignore[arg-type]
            confidence=max(0.0, min(1.0, confidence)),
            actions=actions,
            notes="Jev typed decision; no generated rationale.",
            usage={
                "input_tokens": int(data.get("usage", {}).get("input_tokens", 0)),
                "output_tokens": int(data.get("usage", {}).get("output_tokens", 0)),
            },
            latency_ms=latency_ms,
            raw={"request": payload, "response": data},
        )

    def _post(self, client: httpx.Client, payload: dict[str, Any]) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = client.post(
                    self.config.endpoint,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    time.sleep(min(4.0, 2.0**attempt))
                    continue
                raise ProviderError(f"Jev request failed: {exc}") from exc
            if response.status_code in {401, 403}:
                raise ProviderError(
                    f"Jev rejected the API key (HTTP {response.status_code})"
                )
            if response.status_code == 422:
                raise ProviderError(f"Jev validation error: {response.text[:500]}")
            if response.status_code == 429 or response.status_code >= 500:
                last_error = ProviderError(
                    f"Jev transient HTTP {response.status_code}"
                )
                if attempt < self.config.max_retries:
                    time.sleep(min(4.0, 2.0**attempt))
                    continue
                raise ProviderError(str(last_error))
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ProviderError(f"Jev HTTP {response.status_code}") from exc
            return response
        raise ProviderError(str(last_error or "Jev request failed"))


class OpenAICompatibleProvider:
    """Single-shot JSON decision provider for local or hosted chat models."""

    name = "openai_compatible"

    def __init__(self, config: AgentConfig, client: httpx.Client | None = None):
        self.config = config
        self.client = client
        self.api_key = os.getenv(config.api_key_env)

    def _messages(self, context: dict[str, Any]) -> list[dict[str, str]]:
        constraints = context.get("constraints", {})
        system = (
            "You are the decision engine in a paper-trading research system. "
            "You receive a point-in-time market snapshot and must choose portfolio "
            "exposure. Return ONLY one JSON object, with no markdown and no prose.\n"
            "Schema:\n"
            '{"regime":"risk_on|neutral|risk_off","confidence":0.0,'
            '"actions":[{"asset":"BTC","action":"long|flat|short",'
            '"confidence":0.0,"reason":"short text"}],'
            '"target_weights":{"BTC":0.0},"notes":"short text"}\n'
            "Use actions for discrete choices or target_weights for explicit weights, "
            "not both. Never invent assets. Respect the supplied constraints. "
            "When evidence is weak, prefer flat and lower confidence. "
            "This is a decision task, not a conversation.\n"
            f"Constraints: {json.dumps(constraints, sort_keys=True)}"
        )
        user = json.dumps(context, sort_keys=True, default=str)
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def decide(self, context: dict[str, Any]) -> AgentDecision:
        started = time.perf_counter()
        client = self.client or httpx.Client(timeout=self.config.timeout_seconds)
        close_client = self.client is None
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": self._messages(context),
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": False,
        }
        try:
            response = client.post(self.config.endpoint, headers=headers, json=payload)
            if response.status_code in {401, 403}:
                raise ProviderError(
                    f"LLM provider rejected credentials (HTTP {response.status_code})"
                )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"LLM request failed: {exc}") from exc
        finally:
            if close_client:
                client.close()
        latency_ms = (time.perf_counter() - started) * 1000.0
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("LLM response has no message content") from exc
        try:
            parsed = _parse_json_object(str(content))
        except Exception as exc:
            raise DecisionValidationError(f"LLM output is not valid JSON: {exc}") from exc
        parsed.setdefault("as_of", context.get("as_of"))
        parsed["provider"] = self.name
        parsed["model"] = str(data.get("model", self.config.model))
        parsed["latency_ms"] = latency_ms
        parsed["raw"] = {"request": payload, "response": data}
        usage = data.get("usage", {})
        parsed["usage"] = {
            "input_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "output_tokens": int(usage.get("completion_tokens", 0) or 0),
        }
        try:
            decision = AgentDecision.model_validate(parsed)
        except Exception as exc:
            raise DecisionValidationError(f"invalid LLM decision: {exc}") from exc
        if not decision.actions and not decision.target_weights:
            raise DecisionValidationError("LLM returned no actions or target weights")
        return decision


class DeterministicProvider:
    """Fallback only. It is not an AI model and is labelled as such."""

    name = "deterministic_fallback"

    def decide(self, context: dict[str, Any]) -> AgentDecision:
        assets: dict[str, Any] = context.get("assets", {})
        breadth = float(context.get("market", {}).get("breadth_above_sma200", 0.0))
        regime = "risk_on" if breadth >= 0.6 else "risk_off" if breadth <= 0.3 else "neutral"
        actions: list[AssetDecision] = []
        for asset in context.get("universe", []):
            features = assets.get(asset, {})
            long_ok = bool(features.get("trend_up")) and (
                (features.get("return_60d") or 0.0) > 0
            )
            actions.append(
                AssetDecision(
                    asset=asset,
                    action="long" if long_ok else "flat",
                    confidence=0.65 if long_ok else 0.55,
                    reason="Fallback rule: 200d trend + 60d momentum",
                )
            )
        return AgentDecision(
            as_of=_as_of(context),
            provider=self.name,
            model="none",
            regime=regime,  # type: ignore[arg-type]
            confidence=0.65,
            actions=actions,
            notes=(
                "FALLBACK RULE ENGINE — not an AI model. Configure Jev or a local "
                "LLM to use the AI pipeline."
            ),
            fallback=True,
        )


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("model output must be a JSON object")
    return parsed


def build_provider(config: AgentConfig) -> DecisionProvider:
    if config.provider == "jev":
        return JevProvider(config)
    if config.provider == "squad":
        from tradingbot.ai.squad import SquadProvider

        return SquadProvider(config)
    if config.provider == "openai_compatible":
        return OpenAICompatibleProvider(config)
    if config.provider == "deterministic":
        return DeterministicProvider()
    raise ValueError(f"unknown agent provider: {config.provider}")
