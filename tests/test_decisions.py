from __future__ import annotations

from tradingbot.ops.decisions import _decision, _reason


def test_decision_classification_uses_rebalance_band() -> None:
    assert _decision(0.05, 0.049, 0.005) == "HOLD"
    assert _decision(0.08, 0.05, 0.005) == "ADD"
    assert _decision(0.02, 0.05, 0.005) == "TRIM"
    assert _decision(0.0, 0.05, 0.005) == "EXIT"
    assert _decision(0.05, 0.0, 0.005) == "ENTER"
    assert _decision(0.0, 0.0, 0.005) == "FLAT"


def test_reason_contains_target_evidence_and_model() -> None:
    text = _reason(
        decision="HOLD",
        target=0.05,
        current=0.049,
        min_weight=0.005,
        basis="200d SMA trend",
        facts=["price +10.0% vs 200d SMA"],
        mode="strategy",
    )
    assert "inside the 0.50% rebalance band" in text
    assert "Evidence: price +10.0% vs 200d SMA." in text
    assert "Model: 200d SMA trend." in text
