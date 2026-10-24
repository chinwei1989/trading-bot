from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from tradingbot.options.account import (
    OptionAccount,
    OptionCandidate,
    OptionLimits,
    OptionPosition,
    check_account,
    check_candidate,
)


def _now() -> datetime:
    return datetime(2026, 10, 24, 10, 0, tzinfo=UTC)


def _candidate(
    *,
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
        instrument="ETH-07NOV26-4000-C",
        underlying="ETH",
        option_type="call",
        strike=4000.0,
        expiry=expiry,
        bid=bid,
        ask=ask,
        mark=premium,
        delta=delta,
        gamma=0.0002,
        vega=12.0,
        theta=-3.2,
        open_interest=oi,
    )


def _position(*, premium: float = 100.0, dte: int = 9) -> OptionPosition:
    return OptionPosition(
        instrument="ETH-07NOV26-3800-C",
        underlying="ETH",
        option_type="call",
        strike=3800.0,
        expiry=_now().date() + timedelta(days=dte),
        qty=1,
        entry_premium=premium,
        mark_premium=premium,
        delta=0.40,
        vega=10.0,
        theta=-2.0,
    )


def test_account_gate_computes_premium_budget() -> None:
    account = OptionAccount(cash=10_000.0)
    check = check_account(account, OptionLimits(), now=_now())
    assert check.allowed is True
    assert check.equity == 10_000.0
    assert check.cash_reserve == 2_000.0
    assert check.max_total_premium == 500.0
    assert check.max_new_trade_premium == 200.0
    assert check.open_legs == 0


def test_account_gate_respects_existing_premium_and_legs() -> None:
    account = OptionAccount(
        cash=9_800.0,
        positions=(_position(premium=100.0), _position(premium=110.0)),
    )
    check = check_account(account, OptionLimits(), now=_now())
    assert check.allowed is False
    assert check.open_legs == 2
    assert any("max open legs" in item for item in check.blockers)
    assert check.premium_at_risk == 210.0


def test_account_gate_blocks_cash_below_reserve() -> None:
    large_leg = OptionPosition(
        instrument="ETH-07NOV26-4000-C",
        underlying="ETH",
        option_type="call",
        strike=4000.0,
        expiry=_now().date() + timedelta(days=9),
        qty=1,
        entry_premium=5_000.0,
        mark_premium=5_000.0,
        delta=0.50,
        vega=20.0,
        theta=-5.0,
    )
    account = OptionAccount(cash=1_000.0, positions=(large_leg,))
    check = check_account(account, OptionLimits(), now=_now())
    assert check.allowed is False
    assert any("below reserve" in item for item in check.blockers)


def test_candidate_gate_allows_one_contract() -> None:
    account = OptionAccount(cash=10_000.0)
    check = check_candidate(
        account,
        _candidate(),
        OptionLimits(),
        underlying_price=3_900.0,
        now=_now(),
    )
    assert check.allowed is True
    assert check.contracts == 1
    assert check.premium_per_contract > 185.0
    assert check.estimated_cost > 185.0
    assert check.dte == 9


def test_candidate_gate_blocks_wide_spread_low_oi_and_bad_dte() -> None:
    account = OptionAccount(cash=10_000.0)
    check = check_candidate(
        account,
        _candidate(spread=0.12, oi=10, dte=1, delta=0.10),
        OptionLimits(),
        now=_now(),
    )
    assert check.allowed is False
    assert any("spread" in item for item in check.blockers)
    assert any("open interest" in item for item in check.blockers)
    assert any("DTE" in item for item in check.blockers)
    assert any("delta" in item for item in check.blockers)


def test_candidate_gate_blocks_expensive_premium() -> None:
    account = OptionAccount(cash=10_000.0)
    check = check_candidate(
        account,
        _candidate(premium=350.0),
        OptionLimits(),
        now=_now(),
    )
    assert check.allowed is False
    assert check.contracts == 0


def test_expired_position_blocks_new_trades() -> None:
    expired = OptionPosition(
        instrument="ETH-01OCT26-4000-C",
        underlying="ETH",
        option_type="call",
        strike=4000.0,
        expiry=date(2026, 10, 1),
        qty=1,
        entry_premium=100.0,
        mark_premium=0.0,
        delta=0.0,
        vega=0.0,
        theta=0.0,
    )
    account = OptionAccount(cash=10_000.0, positions=(expired,))
    check = check_account(account, OptionLimits(), now=_now())
    assert check.allowed is False
    assert any("expired position" in item for item in check.blockers)
