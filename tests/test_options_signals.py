from __future__ import annotations

from datetime import UTC, datetime

from tradingbot.ai.decision import AgentDecision, AssetDecision
from tradingbot.options.signals import directions_from_decision


def test_actions_map_to_call_put_and_flat() -> None:
    decision = AgentDecision(
        as_of=datetime(2026, 10, 24, tzinfo=UTC),
        actions=[
            AssetDecision(asset="BTCUSDT", action="long", confidence=0.8),
            AssetDecision(asset="ETHUSDT", action="short", confidence=0.7),
            AssetDecision(asset="SOLUSDT", action="flat", confidence=0.9),
        ],
    )
    directions = directions_from_decision(
        decision,
        {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "SOLUSDT": "SOL"},
    )
    assert directions == {"BTC": "long", "ETH": "short", "SOL": "flat"}


def test_target_weights_map_to_directions() -> None:
    decision = AgentDecision(
        as_of=datetime(2026, 10, 24, tzinfo=UTC),
        target_weights={"BTCUSDT": 0.2, "ETHUSDT": -0.1, "SOLUSDT": 0.0},
    )
    directions = directions_from_decision(
        decision,
        {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "SOLUSDT": "SOL"},
    )
    assert directions == {"BTC": "long", "ETH": "short", "SOL": "flat"}
