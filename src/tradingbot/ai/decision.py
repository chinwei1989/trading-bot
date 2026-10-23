"""Typed AI decision objects and validation."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Action = Literal["long", "flat", "short"]
Regime = Literal["risk_on", "neutral", "risk_off"]


class ProviderError(RuntimeError):
    """The decision provider failed or returned an unusable response."""


class ProviderUnavailable(ProviderError):
    """The provider is not configured (for example, no API key)."""


class DecisionValidationError(ValueError):
    """A model response violates the decision contract."""


class AssetDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    asset: str
    action: Action = "flat"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class AgentDecision(BaseModel):
    """A provider-independent decision.

    ``actions`` are discrete choices. ``target_weights`` is optional and is
    mainly for local LLM providers that propose explicit allocations. The
    deterministic policy layer validates and constrains either form.
    """

    model_config = ConfigDict(extra="ignore")

    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))
    provider: str = ""
    model: str = ""
    regime: Regime = "neutral"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    actions: list[AssetDecision] = Field(default_factory=list)
    target_weights: dict[str, float] | None = None
    notes: str = ""
    usage: dict[str, int] = Field(default_factory=dict)
    latency_ms: float = 0.0
    fallback: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("actions")
    @classmethod
    def _unique_assets(cls, value: list[AssetDecision]) -> list[AssetDecision]:
        seen: set[str] = set()
        for action in value:
            if action.asset in seen:
                raise ValueError(f"duplicate action for {action.asset}")
            seen.add(action.asset)
        return value

    @field_validator("target_weights")
    @classmethod
    def _finite_weights(cls, value: dict[str, float] | None) -> dict[str, float] | None:
        if value is None:
            return None
        for asset, weight in value.items():
            if not asset or not math.isfinite(float(weight)):
                raise ValueError(f"invalid target weight for {asset!r}")
        return {k: float(v) for k, v in value.items()}

    def action_map(self) -> dict[str, AssetDecision]:
        return {action.asset: action for action in self.actions}
