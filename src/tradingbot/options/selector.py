"""Deterministic option selection and the two-stage account gate.

The selector turns a direction into a candidate call or put. It never bypasses
the account gate or the contract gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from tradingbot.options.account import (
    AccountCheck,
    CandidateCheck,
    OptionAccount,
    OptionCandidate,
    OptionLimits,
    check_account,
    check_candidate,
)

Direction = Literal["long", "short", "flat"]


@dataclass
class SelectionResult:
    underlying: str
    direction: Direction
    candidate: OptionCandidate | None
    account_check: AccountCheck
    candidate_check: CandidateCheck | None
    blockers: list[str] = field(default_factory=list)
    considered: int = 0
    reason: str = ""


def _target_delta(limits: OptionLimits) -> float:
    return (limits.target_delta_min + limits.target_delta_max) / 2.0


def select_candidate(
    account: OptionAccount,
    chain: list[OptionCandidate],
    *,
    underlying: str,
    direction: Direction,
    limits: OptionLimits | None = None,
    underlying_price: float = 0.0,
    now: datetime | None = None,
) -> SelectionResult:
    """Pick the first acceptable contract for a direction.

    ``long`` buys a call, ``short`` buys a put, and ``flat`` does nothing.
    No naked short options are supported in phase 1.
    """
    limits = limits or OptionLimits()
    account_check = check_account(account, limits, now=now)
    if direction == "flat":
        return SelectionResult(
            underlying=underlying,
            direction=direction,
            candidate=None,
            account_check=account_check,
            candidate_check=None,
            reason="flat direction",
        )
    if not account_check.allowed:
        return SelectionResult(
            underlying=underlying,
            direction=direction,
            candidate=None,
            account_check=account_check,
            candidate_check=None,
            blockers=list(account_check.blockers),
            reason="portfolio gate blocked",
        )

    option_type: Literal["call", "put"] = "call" if direction == "long" else "put"
    candidates = [
        candidate
        for candidate in chain
        if candidate.underlying == underlying
        and candidate.option_type == option_type
    ]
    if not candidates:
        return SelectionResult(
            underlying=underlying,
            direction=direction,
            candidate=None,
            account_check=account_check,
            candidate_check=None,
            blockers=[f"no {option_type} candidates for {underlying}"],
            reason="empty chain",
        )

    target = _target_delta(limits)
    candidates.sort(
        key=lambda c: (
            abs(abs(c.delta) - target),
            c.spread_pct,
            -c.open_interest,
        )
    )

    blockers: list[str] = []
    for candidate in candidates:
        check = check_candidate(
            account,
            candidate,
            limits,
            underlying_price=underlying_price,
            now=now,
        )
        if check.allowed:
            return SelectionResult(
                underlying=underlying,
                direction=direction,
                candidate=candidate,
                account_check=account_check,
                candidate_check=check,
                considered=len(candidates),
                reason="contract gate passed",
            )
        blockers.append(f"{candidate.instrument}: {'; '.join(check.blockers)}")
        if len(blockers) >= 5:
            break
    return SelectionResult(
        underlying=underlying,
        direction=direction,
        candidate=None,
        account_check=account_check,
        candidate_check=None,
        blockers=blockers,
        considered=len(candidates),
        reason="no contract passed the gate",
    )
