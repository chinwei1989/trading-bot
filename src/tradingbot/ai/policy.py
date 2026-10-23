"""Deterministic policy layer that constrains an AI decision.

The model may choose direction or propose weights. This module owns sizing,
gross/net caps, cash, confidence gating, and turnover control. A model can
therefore never bypass the risk policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import polars as pl

from tradingbot.ai.decision import AgentDecision, DecisionValidationError
from tradingbot.config import AgentPolicyConfig


@dataclass
class PolicyApplication:
    weights: pl.DataFrame
    target_weights: dict[str, float]
    gross: float
    turnover: float
    notes: list[str] = field(default_factory=list)


def _timestamp(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _inverse_vol_weights(
    decision: AgentDecision,
    assets: dict[str, Any],
    *,
    allow_short: bool,
    gross_target: float,
    min_confidence: float,
) -> tuple[dict[str, float], list[str]]:
    notes: list[str] = []
    longs: list[str] = []
    shorts: list[str] = []
    for action in decision.actions:
        if action.asset not in assets:
            notes.append(f"ignored unknown asset {action.asset}")
            continue
        if action.confidence < min_confidence:
            notes.append(
                f"{action.asset}: confidence {action.confidence:.2f} below "
                f"{min_confidence:.2f}; flat"
            )
            continue
        if action.action == "long":
            longs.append(action.asset)
        elif action.action == "short" and allow_short:
            shorts.append(action.asset)
        elif action.action == "short":
            notes.append(f"{action.asset}: short rejected (shorting disabled)")

    selected = [*longs, *shorts]
    if not selected:
        return ({asset: 0.0 for asset in assets}, notes)

    inv: dict[str, float] = {}
    for asset in selected:
        vol = assets[asset].get("vol_60d") or assets[asset].get("vol_20d") or 0.6
        inv[asset] = 1.0 / max(float(vol), 0.05)
    total_inv = sum(inv.values())
    weights = {asset: 0.0 for asset in assets}
    if total_inv <= 0:
        return weights, notes
    for asset in longs:
        weights[asset] = gross_target * inv[asset] / total_inv
    for asset in shorts:
        weights[asset] = -gross_target * inv[asset] / total_inv
    return weights, notes


def _cap_exposure(
    target: dict[str, float],
    *,
    max_gross: float,
    max_asset_weight: float,
    current: dict[str, float],
    max_turnover: float,
) -> tuple[dict[str, float], float]:
    safe_asset = max(0.0, max_asset_weight - 1e-9)
    for _ in range(4):
        target = {
            asset: max(-safe_asset, min(safe_asset, weight))
            for asset, weight in target.items()
        }
        gross = sum(abs(weight) for weight in target.values())
        if gross > max_gross and gross > 1e-12:
            scale = max_gross / gross
            target = {asset: weight * scale for asset, weight in target.items()}

    assets = set(target) | set(current)
    delta = {asset: target.get(asset, 0.0) - current.get(asset, 0.0) for asset in assets}
    one_way = 0.5 * sum(abs(value) for value in delta.values())
    if max_turnover >= 0 and one_way > max_turnover and one_way > 1e-12:
        scale = max_turnover / one_way
        target = {
            asset: current.get(asset, 0.0) + delta.get(asset, 0.0) * scale
            for asset in assets
        }
    target = {
        asset: max(-safe_asset, min(safe_asset, weight))
        for asset, weight in target.items()
    }
    gross = sum(abs(weight) for weight in target.values())
    return target, gross


def apply_policy(
    decision: AgentDecision,
    context: dict[str, Any],
    policy: AgentPolicyConfig,
) -> PolicyApplication:
    """Convert a provider decision into constrained portfolio weights."""
    assets: dict[str, Any] = context["assets"]
    universe: list[str] = list(context["universe"])
    current: dict[str, float] = {
        str(asset): float(weight)
        for asset, weight in context.get("portfolio", {}).get("current_weights", {}).items()
    }
    notes: list[str] = []

    if decision.confidence < policy.min_confidence and not decision.force_rebalance:
        notes.append(
            f"overall confidence {decision.confidence:.2f} below "
            f"{policy.min_confidence:.2f}; holding current weights"
        )
        target = {asset: current.get(asset, 0.0) for asset in universe}
        target, gross = _cap_exposure(
            target,
            max_gross=min(policy.max_gross, 1.0 - policy.min_cash_weight),
            max_asset_weight=policy.max_asset_weight,
            current=current,
            max_turnover=policy.max_turnover,
        )
        target = {asset: target.get(asset, 0.0) for asset in universe}
        gross = sum(abs(value) for value in target.values())
        delta = {
            asset: target.get(asset, 0.0) - current.get(asset, 0.0)
            for asset in universe
        }
        one_way_turnover = 0.5 * sum(abs(value) for value in delta.values())
        ts = _timestamp(decision.as_of)
        frame = pl.DataFrame(
            {
                "timestamp": [ts] * len(universe),
                "asset": universe,
                "weight": [target[asset] for asset in universe],
            }
        )
        return PolicyApplication(frame, target, gross, one_way_turnover, notes)

    cap = policy.max_gross
    if decision.regime == "risk_off":
        cap = min(cap, policy.risk_off_gross)
        notes.append("risk_off regime: gross cap reduced")
    elif decision.regime == "neutral":
        cap *= 0.75
        notes.append("neutral regime: gross cap at 75%")
    cap = min(cap, 1.0 - policy.min_cash_weight)

    if decision.target_weights:
        target = {asset: 0.0 for asset in universe}
        for asset, weight in decision.target_weights.items():
            if asset not in assets:
                notes.append(f"ignored unknown target asset {asset}")
                continue
            if weight < 0 and not policy.allow_short:
                notes.append(f"{asset}: negative target rejected (shorting disabled)")
                weight = 0.0
            target[asset] = float(weight)
        if not any(abs(value) > 1e-12 for value in target.values()):
            raise DecisionValidationError("decision contained no usable target weights")
        gross_before = sum(abs(value) for value in target.values())
        if gross_before > cap and gross_before > 1e-12:
            target = {asset: value * cap / gross_before for asset, value in target.items()}
    else:
        if not decision.actions:
            raise DecisionValidationError("decision contained neither actions nor target weights")
        gross_target = cap * (0.5 + 0.5 * decision.confidence)
        target, action_notes = _inverse_vol_weights(
            decision,
            assets,
            allow_short=policy.allow_short,
            gross_target=gross_target,
            min_confidence=policy.min_confidence,
        )
        notes.extend(action_notes)
        if not any(abs(value) > 1e-12 for value in target.values()):
            notes.append("no qualifying long/short actions; moving to cash")

    target, gross = _cap_exposure(
        target,
        max_gross=cap,
        max_asset_weight=policy.max_asset_weight,
        current=current,
        max_turnover=policy.max_turnover,
    )
    target = {asset: target.get(asset, 0.0) for asset in universe}
    gross = sum(abs(value) for value in target.values())
    delta = {
        asset: target.get(asset, 0.0) - current.get(asset, 0.0) for asset in universe
    }
    one_way_turnover = 0.5 * sum(abs(value) for value in delta.values())
    ts = _timestamp(decision.as_of)
    frame = pl.DataFrame(
        {
            "timestamp": [ts] * len(universe),
            "asset": universe,
            "weight": [target[asset] for asset in universe],
        }
    )
    return PolicyApplication(frame, target, gross, one_way_turnover, notes)
