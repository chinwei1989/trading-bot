"""Adapters from an AI decision to the options direction contract."""

from __future__ import annotations

from tradingbot.ai.decision import AgentDecision
from tradingbot.options.selector import Direction


def directions_from_decision(
    decision: AgentDecision,
    underlying_map: dict[str, str] | None = None,
) -> dict[str, Direction]:
    """Map typed AI actions or target weights to option directions.

    The options lane treats ``long`` as buy-call, ``short`` as buy-put, and
    ``flat`` as no new position. It never maps a negative weight to a naked
    short option.
    """
    mapping = underlying_map or {}
    directions: dict[str, Direction] = {}
    for action in decision.actions:
        underlying = mapping.get(action.asset, action.asset)
        if action.action in {"long", "short", "flat"}:
            directions[underlying] = action.action
    if decision.target_weights:
        for asset, weight in decision.target_weights.items():
            underlying = mapping.get(asset, asset)
            if abs(float(weight)) < 1e-12:
                directions[underlying] = "flat"
            elif float(weight) > 0:
                directions[underlying] = "long"
            else:
                directions[underlying] = "short"
    return directions
