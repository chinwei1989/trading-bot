from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from tradingbot.options.account import OptionCandidate, OptionLimits
from tradingbot.options.broker import PaperOptionsBroker
from tradingbot.options.pipeline import result_payload, run_options_cycle


def _now() -> datetime:
    return datetime(2026, 10, 24, 10, 0, tzinfo=UTC)


def _candidate(
    *,
    instrument: str = "ETH-07NOV26-4000-C",
    underlying: str = "ETH",
    option_type: str = "call",
    premium: float = 185.0,
    dte: int = 9,
    delta: float = 0.46,
    spread: float = 0.018,
    oi: int = 1200,
) -> OptionCandidate:
    expiry = _now().date() + timedelta(days=dte)
    bid = premium * (1.0 - spread / 2.0)
    ask = premium * (1.0 + spread / 2.0)
    return OptionCandidate(
        instrument=instrument,
        underlying=underlying,
        option_type=option_type,  # type: ignore[arg-type]
        strike=4000.0 if underlying == "ETH" else 100000.0,
        expiry=expiry,
        bid=bid,
        ask=ask,
        mark=premium,
        delta=delta if option_type == "call" else -delta,
        gamma=0.0002,
        vega=12.0,
        theta=-3.2,
        open_interest=oi,
    )


def test_cycle_opens_marks_and_closes_position() -> None:
    broker = PaperOptionsBroker(cash=10_000.0)
    chain = [_candidate()]
    opened = run_options_cycle(
        broker,
        chain,
        {"ETH": "long"},
        {"ETH": 3_900.0},
        limits=OptionLimits(),
        now=_now(),
    )
    assert opened.status == "ok"
    assert len(opened.fills) == 1
    assert opened.fills[0].status == "filled"
    assert opened.fills[0].side == "buy"
    assert len(broker.holdings) == 1
    assert broker.cash < 10_000.0

    closed = run_options_cycle(
        broker,
        chain,
        {"ETH": "flat"},
        {"ETH": 3_900.0},
        limits=OptionLimits(),
        now=_now() + timedelta(minutes=30),
    )
    assert closed.fills[-1].side == "sell"
    assert closed.fills[-1].status == "filled"
    assert len(broker.holdings) == 0
    assert broker.cash < 10_000.0
    assert broker.cash > 9_900.0


def test_cycle_blocks_wide_spread() -> None:
    broker = PaperOptionsBroker(cash=10_000.0)
    result = run_options_cycle(
        broker,
        [_candidate(spread=0.20)],
        {"ETH": "long"},
        {"ETH": 3_900.0},
        limits=OptionLimits(),
        now=_now(),
    )
    assert result.fills == []
    assert result.selections
    assert result.selections[0].candidate is None
    assert any("spread" in alert for alert in result.alerts)


def test_cycle_uses_pre_selector_leg_limit() -> None:
    broker = PaperOptionsBroker(cash=10_000.0)
    chain = [
        _candidate(
            instrument="BTC-07NOV26-100000-C",
            underlying="BTC",
            premium=190.0,
        ),
        _candidate(
            instrument="ETH-07NOV26-4000-C",
            underlying="ETH",
            premium=185.0,
        ),
    ]
    first = run_options_cycle(
        broker,
        chain,
        {"BTC": "long", "ETH": "long"},
        {"BTC": 100_000.0, "ETH": 3_900.0},
        limits=OptionLimits(max_open_legs=1),
        now=_now(),
    )
    assert len(first.fills) == 1
    assert len(broker.holdings) == 1

    second = run_options_cycle(
        broker,
        chain,
        {"BTC": "long", "ETH": "long"},
        {"BTC": 100_000.0, "ETH": 3_900.0},
        limits=OptionLimits(max_open_legs=1),
        now=_now() + timedelta(minutes=30),
    )
    assert any("max open legs" in alert for alert in second.alerts)


def test_cycle_settles_expired_option() -> None:
    broker = PaperOptionsBroker(cash=10_000.0)
    candidate = _candidate(dte=1)
    broker.buy(candidate, 1, now=_now())
    expired = _now() + timedelta(days=2)
    result = run_options_cycle(
        broker,
        [],
        {"ETH": "flat"},
        {"ETH": 4_100.0},
        now=expired,
    )
    assert len(broker.holdings) == 0
    assert result.settlements
    assert result.settlements[0].proceeds > 0
    assert result.settlements[0].status == "settled"


def test_paper_broker_state_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "options_state.json"
    broker = PaperOptionsBroker(cash=10_000.0, state_path=path)
    broker.buy(_candidate(), 1, now=_now())
    broker.save()
    restored = PaperOptionsBroker(cash=0.0, state_path=path)
    assert restored.load() is True
    assert restored.cash == broker.cash
    assert list(restored.holdings) == list(broker.holdings)


def test_result_payload_is_json_friendly() -> None:
    import json

    broker = PaperOptionsBroker(cash=10_000.0)
    result = run_options_cycle(
        broker,
        [_candidate()],
        {"ETH": "long"},
        {"ETH": 3_900.0},
        now=_now(),
    )
    payload = result_payload(result)
    encoded = json.dumps(payload)
    assert "ETH-07NOV26-4000-C" in encoded
    assert payload["account_after"]["legs"] == 1
