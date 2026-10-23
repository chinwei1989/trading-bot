from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from tradingbot.config import RiskConfig
from tradingbot.portfolio.risk import RiskLimitBreached, assert_safe, check_limits, enforce_limits


def _weights(rows: list[tuple[str, float]]) -> pl.DataFrame:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    return pl.DataFrame(
        {
            "timestamp": [ts] * len(rows),
            "asset": [r[0] for r in rows],
            "weight": [r[1] for r in rows],
        }
    )


def test_enforce_limits_clips_and_scales() -> None:
    config = RiskConfig(max_gross=1.0, max_net=1.0, max_asset_weight=0.25)
    weights = _weights([("A", 0.8), ("B", 0.8), ("C", -0.8)])
    out = enforce_limits(weights, config)
    assert out["weight"].abs().max() <= 0.25 + 1e-9
    gross = out.group_by("timestamp").agg(pl.col("weight").abs().sum())["weight"].max()
    assert gross <= 1.0 + 1e-9


def test_check_limits_detects_violation() -> None:
    config = RiskConfig(max_gross=0.5, max_net=0.5, max_asset_weight=0.2)
    report = check_limits(_weights([("A", 0.9)]), config)
    assert report.breached
    assert report.max_asset > 0.2


def test_kill_switch(tmp_path) -> None:
    kill = tmp_path / "KILL"
    kill.write_text("stop", encoding="utf-8")
    with pytest.raises(RiskLimitBreached):
        assert_safe(_weights([("A", 0.1)]), RiskConfig(), kill_file=kill)
