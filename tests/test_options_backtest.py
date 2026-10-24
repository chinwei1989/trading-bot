from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tradingbot.options.account import OptionCandidate
from tradingbot.options.backtest import OptionSnapshot, replay_options


def _now() -> datetime:
    return datetime(2026, 10, 24, 10, 0, tzinfo=UTC)


def _candidate() -> OptionCandidate:
    expiry = _now().date() + timedelta(days=9)
    return OptionCandidate(
        instrument="ETH-07NOV26-4000-C",
        underlying="ETH",
        option_type="call",
        strike=4000.0,
        expiry=expiry,
        bid=183.3,
        ask=186.7,
        mark=185.0,
        delta=0.46,
        gamma=0.0002,
        vega=12.0,
        theta=-3.2,
        open_interest=1200,
    )


def test_replay_opens_and_closes_over_snapshots() -> None:
    first = _now()
    second = first + timedelta(minutes=30)
    snapshots = [
        OptionSnapshot(first, [_candidate()], {"ETH": 3900.0}),
        OptionSnapshot(second, [_candidate()], {"ETH": 3900.0}),
    ]

    def signal(snapshot: OptionSnapshot) -> dict[str, str]:
        return {"ETH": "long" if snapshot.timestamp == first else "flat"}

    result = replay_options(snapshots, signal)  # type: ignore[arg-type]
    assert len(result.cycles) == 2
    assert result.total_fills == 2
    assert result.final_equity < 10_000.0
    assert result.final_equity > 9_900.0
    assert result.total_fees > 0
    assert result.max_drawdown <= 0.0
    assert result.cycles[0].open_legs == 1
    assert result.cycles[1].open_legs == 0


def test_replay_rejects_duplicate_timestamps() -> None:
    ts = _now()
    snapshots = [
        OptionSnapshot(ts, [_candidate()], {"ETH": 3900.0}),
        OptionSnapshot(ts, [_candidate()], {"ETH": 3900.0}),
    ]
    with pytest.raises(ValueError, match="duplicate"):
        replay_options(snapshots, lambda snapshot: {"ETH": "flat"})


def test_replay_empty_snapshots() -> None:
    with pytest.raises(ValueError, match="no option snapshots"):
        replay_options([], lambda snapshot: {})
