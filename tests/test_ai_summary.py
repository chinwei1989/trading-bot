from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tradingbot.ops.ai_summary import _compose, load_ai_summary


def _state() -> dict:
    return {
        "as_of": "2026-10-27",
        "portfolio": {
            "gross_usd": 23_690.0,
            "net_usd": 14_690.0,
            "open_pnl_usd": 14.80,
            "open_pnl_pct": 0.000625,
            "lane_pnl_usd": -65.58,
            "lane_pnl_pct": -0.000729,
            "positions": 34,
            "active_lanes": 7,
            "paper_accounts": 9,
        },
        "sui": {"qty": 4_347.5, "value_usd": 4_058.0, "pnl_usd": 23.44},
        "options": {"open_contracts": 0, "value_usd": 0.0},
        "gates": {
            "spot_live": "NO_GO",
            "options_live": "NO_GO",
            "host": "DEGRADED",
        },
        "note": "paper only",
    }


def test_compose_gist_has_ai_classification_and_pnl_percentages() -> None:
    answers = {
        "posture": {"choice": "cautious", "confidence": 0.69},
        "next_action": {"choice": "review", "confidence": 0.44},
        "top_risk": {"choice": "execution", "confidence": 0.49},
    }
    result = _compose(
        _state(),
        answers,
        "jev-test",
        datetime(2026, 10, 28, 5, 0, tzinfo=UTC),
    )
    assert result["headline"] == "Cautious · Review Before Adding"
    assert "cautious" in result["summary"]
    assert "review before adding" in result["summary"]
    assert "execution/data reliability" in result["summary"]
    assert "+$14.80" in result["summary"]
    assert "-0.07%" in result["summary"]
    assert result["confidence"] == 0.54
    assert result["provider"] == "jev"
    assert result["paper_only"] is True
    assert len(result["bullets"]) == 4


def test_load_ai_summary(tmp_path: Path) -> None:
    path = tmp_path / "artifacts" / "ai_summary" / "latest.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"headline": "test"}), encoding="utf-8")
    assert load_ai_summary(tmp_path) == {"headline": "test"}
    assert load_ai_summary(tmp_path / "missing") is None
