"""Deterministic, paper-only options cycle.

The cycle is deliberately independent of Jev and of a venue. A signal provider
returns a direction per underlying; the selector and the two account gates do
the rest. A venue adapter and an AI-squad signal adapter can be connected later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from tradingbot.options.account import (
    AccountCheck,
    OptionAccount,
    OptionCandidate,
    OptionLimits,
    check_account,
)
from tradingbot.options.broker import (
    OptionFill,
    OptionSettlement,
    PaperOptionsBroker,
)
from tradingbot.options.selector import (
    Direction,
    SelectionResult,
    select_candidate,
)


@dataclass
class OptionsCycleResult:
    status: str
    as_of: datetime
    account_before: OptionAccount
    account_after: OptionAccount
    account_check: AccountCheck
    fills: list[OptionFill] = field(default_factory=list)
    settlements: list[OptionSettlement] = field(default_factory=list)
    selections: list[SelectionResult] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)


def _close_direction(
    broker: PaperOptionsBroker,
    chain: list[OptionCandidate],
    *,
    underlying: str,
    desired: Direction,
    now: datetime,
) -> list[OptionFill]:
    """Close holdings that no longer match the desired direction."""
    quotes = {candidate.instrument: candidate for candidate in chain}
    fills: list[OptionFill] = []
    for instrument, holding in list(broker.holdings.items()):
        if holding.underlying != underlying:
            continue
        desired_type = "call" if desired == "long" else "put"
        if desired != "flat" and holding.option_type == desired_type:
            continue
        quote = quotes.get(instrument)
        if quote is None:
            fills.append(
                OptionFill(
                    instrument,
                    "sell",
                    holding.qty,
                    holding.mark_premium,
                    0.0,
                    broker.cash,
                    status="rejected",
                    reason="no current quote to close",
                )
            )
            continue
        fills.append(broker.sell(quote, holding.qty, now=now))
    return fills


def run_options_cycle(
    broker: PaperOptionsBroker,
    chain: list[OptionCandidate],
    directions: dict[str, Direction],
    underlying_prices: dict[str, float],
    *,
    limits: OptionLimits | None = None,
    now: datetime | None = None,
    max_contracts: int = 1,
) -> OptionsCycleResult:
    """Run one paper options decision/execution cycle.

    This is an integration harness, not a live order path. It does not call Jev,
    a venue, or a network.
    """
    limits = limits or OptionLimits()
    now = now or datetime.now(UTC)
    today = now.date()
    broker.mark_to_chain(chain)
    account_before = broker.account()
    settlements = broker.settle_expired(underlying_prices, today=today)
    alerts: list[str] = []
    for settlement in settlements:
        if settlement.status != "settled":
            alerts.append(
                f"{settlement.instrument}: {settlement.status}; position retained"
            )

    # Close what no longer matches before opening anything new.
    fills: list[OptionFill] = []
    for underlying, direction in directions.items():
        fills.extend(
            _close_direction(
                broker,
                chain,
                underlying=underlying,
                desired=direction,
                now=now,
            )
        )

    account = broker.account()
    account_check = check_account(account, limits, now=now)
    selections: list[SelectionResult] = []
    if not account_check.allowed:
        return OptionsCycleResult(
            status="blocked",
            as_of=now,
            account_before=account_before,
            account_after=account,
            account_check=account_check,
            fills=fills,
            settlements=settlements,
            alerts=alerts + list(account_check.blockers),
        )

    for underlying, direction in directions.items():
        if direction == "flat":
            continue
        if any(
            holding.underlying == underlying and holding.option_type == (
                "call" if direction == "long" else "put"
            )
            for holding in broker.holdings.values()
        ):
            continue
        selection = select_candidate(
            broker.account(),
            chain,
            underlying=underlying,
            direction=direction,
            limits=limits,
            underlying_price=underlying_prices.get(underlying, 0.0),
            now=now,
        )
        selections.append(selection)
        if selection.candidate is None or selection.candidate_check is None:
            if selection.blockers:
                alerts.extend(
                    f"{underlying}: {blocker}" for blocker in selection.blockers
                )
            continue
        contracts = min(max_contracts, selection.candidate_check.contracts)
        if contracts <= 0:
            alerts.append(f"{underlying}: contract gate returned zero contracts")
            continue
        fill = broker.buy(selection.candidate, contracts, now=now)
        fills.append(fill)
        if fill.status != "filled":
            alerts.append(f"{underlying}: {fill.reason}")

    account_after = broker.account()
    post_check = check_account(account_after, limits, now=now)
    return OptionsCycleResult(
        status="ok" if not alerts else "ok_with_alerts",
        as_of=now,
        account_before=account_before,
        account_after=account_after,
        account_check=post_check,
        fills=fills,
        settlements=settlements,
        selections=selections,
        alerts=alerts,
    )


def result_payload(result: OptionsCycleResult) -> dict[str, Any]:
    """JSON-friendly summary for tests, reports, or a future dashboard."""
    return {
        "status": result.status,
        "as_of": result.as_of.isoformat(),
        "account_before": {
            "cash": result.account_before.cash,
            "equity": result.account_before.equity(),
            "legs": len(result.account_before.positions),
        },
        "account_after": {
            "cash": result.account_after.cash,
            "equity": result.account_after.equity(),
            "legs": len(result.account_after.positions),
        },
        "account_check": {
            "allowed": result.account_check.allowed,
            "available_premium": result.account_check.available_premium,
            "max_new_trade_premium": result.account_check.max_new_trade_premium,
            "blockers": result.account_check.blockers,
            "warnings": result.account_check.warnings,
        },
        "fills": [
            {
                "instrument": fill.instrument,
                "side": fill.side,
                "qty": fill.qty,
                "premium": fill.premium,
                "fee": fill.fee,
                "status": fill.status,
                "reason": fill.reason,
            }
            for fill in result.fills
        ],
        "settlements": [
            {
                "instrument": settlement.instrument,
                "qty": settlement.qty,
                "intrinsic": settlement.intrinsic,
                "proceeds": settlement.proceeds,
                "status": settlement.status,
            }
            for settlement in result.settlements
        ],
        "selections": [
            {
                "underlying": selection.underlying,
                "direction": selection.direction,
                "candidate": (
                    selection.candidate.instrument if selection.candidate else None
                ),
                "reason": selection.reason,
                "blockers": selection.blockers,
            }
            for selection in result.selections
        ],
        "alerts": result.alerts,
    }
