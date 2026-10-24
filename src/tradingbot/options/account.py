"""Option account and feasibility checks.

This module is deliberately independent of any venue. It provides the two
gates that must sit around an option selector:

1. a portfolio / cash gate before a contract is chosen;
2. a contract gate after the selector proposes one.

Both are deterministic and have no LLM input. They do not place orders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal

OptionType = Literal["call", "put"]


@dataclass(frozen=True)
class OptionPosition:
    instrument: str
    underlying: str
    option_type: OptionType
    strike: float
    expiry: date
    qty: int
    entry_premium: float
    mark_premium: float
    delta: float
    vega: float
    theta: float
    multiplier: float = 1.0

    def premium_value(self) -> float:
        return max(0.0, float(self.qty) * float(self.mark_premium) * self.multiplier)

    def premium_at_risk(self) -> float:
        return max(0.0, float(self.qty) * float(self.entry_premium) * self.multiplier)

    def delta_notional(self, underlying_price: float) -> float:
        return float(self.qty) * self.delta * self.multiplier * underlying_price


@dataclass(frozen=True)
class OptionCandidate:
    instrument: str
    underlying: str
    option_type: OptionType
    strike: float
    expiry: date
    bid: float
    ask: float
    mark: float
    delta: float
    gamma: float
    vega: float
    theta: float
    open_interest: int
    volume: int = 0
    multiplier: float = 1.0

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return max(self.bid, self.ask, self.mark)

    @property
    def spread_pct(self) -> float:
        mid = self.mid
        return (self.ask - self.bid) / mid if mid > 0 else 1.0


@dataclass(frozen=True)
class OptionAccount:
    cash: float
    positions: tuple[OptionPosition, ...] = ()

    def premium_value(self) -> float:
        return sum(position.premium_value() for position in self.positions)

    def equity(self) -> float:
        return float(self.cash) + self.premium_value()

    def premium_at_risk(self) -> float:
        return sum(position.premium_at_risk() for position in self.positions)


@dataclass(frozen=True)
class OptionLimits:
    max_premium_per_trade_pct: float = 0.02
    max_total_premium_pct: float = 0.05
    min_cash_pct: float = 0.20
    max_open_legs: int = 2
    max_legs_per_underlying: int = 1
    min_dte: int = 3
    max_dte: int = 21
    exit_dte: int = 2
    target_delta_min: float = 0.30
    target_delta_max: float = 0.60
    max_spread_pct: float = 0.05
    min_open_interest: int = 100
    max_net_delta_abs: float = 2.0
    max_net_vega_abs: float = 100.0
    max_net_theta_abs: float = 100.0
    fee_bps: float = 3.0
    min_contracts: int = 1


@dataclass
class AccountCheck:
    allowed: bool
    equity: float
    cash: float
    cash_reserve: float
    premium_at_risk: float
    max_total_premium: float
    available_premium: float
    max_new_trade_premium: float
    open_legs: int
    underlying_counts: dict[str, int] = field(default_factory=dict)
    net_delta: float = 0.0
    net_vega: float = 0.0
    net_theta: float = 0.0
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class CandidateCheck:
    allowed: bool
    contracts: int
    premium_per_contract: float
    estimated_fees: float
    estimated_cost: float
    max_loss: float
    spread_pct: float
    dte: int
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _today(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).date()


def _dte(expiry: date, today: date) -> int:
    return (expiry - today).days


def check_account(
    account: OptionAccount,
    limits: OptionLimits | None = None,
    *,
    now: datetime | None = None,
) -> AccountCheck:
    """Pre-selector gate: how much premium capacity and risk capacity exist?"""
    limits = limits or OptionLimits()
    today = _today(now)
    equity = account.equity()
    cash = float(account.cash)
    cash_reserve = max(0.0, equity * limits.min_cash_pct)
    premium_at_risk = account.premium_at_risk()
    max_total_premium = max(0.0, equity * limits.max_total_premium_pct)
    available_premium = max(
        0.0,
        min(max_total_premium - premium_at_risk, cash - cash_reserve),
    )
    max_new_trade_premium = min(
        max(0.0, equity * limits.max_premium_per_trade_pct),
        available_premium,
    )

    underlying_counts: dict[str, int] = {}
    blockers: list[str] = []
    warnings: list[str] = []
    for position in account.positions:
        underlying_counts[position.underlying] = (
            underlying_counts.get(position.underlying, 0) + 1
        )
        if position.expiry < today:
            blockers.append(f"{position.instrument}: expired position requires settlement")
        elif _dte(position.expiry, today) <= 1:
            warnings.append(f"{position.instrument}: 1 DTE or less")

    if equity <= 0:
        blockers.append("account equity is not positive")
    if cash < cash_reserve:
        blockers.append(
            f"cash ${cash:,.2f} below reserve ${cash_reserve:,.2f}"
        )
    if len(account.positions) >= limits.max_open_legs:
        blockers.append(
            f"max open legs reached ({len(account.positions)}/{limits.max_open_legs})"
        )
    if max_new_trade_premium <= 0:
        blockers.append("no premium budget available")

    net_delta = sum(
        position.delta * position.qty * position.multiplier
        for position in account.positions
    )
    net_vega = sum(
        position.vega * position.qty * position.multiplier
        for position in account.positions
    )
    net_theta = sum(
        position.theta * position.qty * position.multiplier
        for position in account.positions
    )
    if abs(net_delta) > limits.max_net_delta_abs:
        blockers.append(
            f"net delta {net_delta:.2f} above {limits.max_net_delta_abs:.2f}"
        )
    if abs(net_vega) > limits.max_net_vega_abs:
        blockers.append(
            f"net vega {net_vega:.2f} above {limits.max_net_vega_abs:.2f}"
        )
    if abs(net_theta) > limits.max_net_theta_abs:
        blockers.append(
            f"net theta {net_theta:.2f} above {limits.max_net_theta_abs:.2f}"
        )

    if premium_at_risk > 0 and equity > 0:
        warnings.append(
            f"premium at risk ${premium_at_risk:,.2f} "
            f"({premium_at_risk / equity:.1%} of equity)"
        )

    return AccountCheck(
        allowed=not blockers,
        equity=equity,
        cash=cash,
        cash_reserve=cash_reserve,
        premium_at_risk=premium_at_risk,
        max_total_premium=max_total_premium,
        available_premium=available_premium,
        max_new_trade_premium=max_new_trade_premium,
        open_legs=len(account.positions),
        underlying_counts=underlying_counts,
        net_delta=net_delta,
        net_vega=net_vega,
        net_theta=net_theta,
        blockers=blockers,
        warnings=warnings,
    )


def check_candidate(
    account: OptionAccount,
    candidate: OptionCandidate,
    limits: OptionLimits | None = None,
    *,
    underlying_price: float = 0.0,
    now: datetime | None = None,
) -> CandidateCheck:
    """Post-selector gate: can this exact contract be bought within budget?"""
    limits = limits or OptionLimits()
    today = _today(now)
    account_check = check_account(account, limits, now=now)
    dte = _dte(candidate.expiry, today)
    premium = max(0.0, candidate.ask) * candidate.multiplier
    fee = premium * limits.fee_bps / 10_000.0
    blockers = list(account_check.blockers)
    warnings: list[str] = []

    if dte < limits.min_dte:
        blockers.append(f"DTE {dte} below minimum {limits.min_dte}")
    if dte > limits.max_dte:
        blockers.append(f"DTE {dte} above maximum {limits.max_dte}")
    if candidate.spread_pct > limits.max_spread_pct:
        blockers.append(
            f"spread {candidate.spread_pct:.1%} above {limits.max_spread_pct:.1%}"
        )
    if candidate.open_interest < limits.min_open_interest:
        blockers.append(
            f"open interest {candidate.open_interest} below "
            f"{limits.min_open_interest}"
        )
    if abs(candidate.delta) < limits.target_delta_min:
        blockers.append(
            f"delta {candidate.delta:.2f} below target minimum "
            f"{limits.target_delta_min:.2f}"
        )
    if abs(candidate.delta) > limits.target_delta_max:
        blockers.append(
            f"delta {candidate.delta:.2f} above target maximum "
            f"{limits.target_delta_max:.2f}"
        )
    if account_check.underlying_counts.get(
        candidate.underlying, 0
    ) >= limits.max_legs_per_underlying:
        blockers.append(
            f"max legs for {candidate.underlying} reached "
            f"({limits.max_legs_per_underlying})"
        )
    if premium <= 0:
        blockers.append("no valid ask premium")

    budget = account_check.max_new_trade_premium
    contracts = 0
    if premium > 0 and budget > 0:
        contracts = int(budget // (premium + fee))
    if contracts < limits.min_contracts:
        blockers.append(
            f"premium budget ${budget:,.2f} cannot fund one contract "
            f"(need ${premium + fee:,.2f})"
        )
    elif contracts > 0:
        prospective_delta = (
            account_check.net_delta + candidate.delta * contracts * candidate.multiplier
        )
        prospective_vega = (
            account_check.net_vega + candidate.vega * contracts * candidate.multiplier
        )
        prospective_theta = (
            account_check.net_theta + candidate.theta * contracts * candidate.multiplier
        )
        if abs(prospective_delta) > limits.max_net_delta_abs:
            blockers.append(
                f"prospective net delta {prospective_delta:.2f} above "
                f"{limits.max_net_delta_abs:.2f}"
            )
        if abs(prospective_vega) > limits.max_net_vega_abs:
            blockers.append(
                f"prospective net vega {prospective_vega:.2f} above "
                f"{limits.max_net_vega_abs:.2f}"
            )
        if abs(prospective_theta) > limits.max_net_theta_abs:
            blockers.append(
                f"prospective net theta {prospective_theta:.2f} above "
                f"{limits.max_net_theta_abs:.2f}"
            )

    if dte <= limits.min_dte:
        warnings.append("contract is near the minimum DTE; theta is elevated")
    if candidate.spread_pct > limits.max_spread_pct * 0.8:
        warnings.append("spread is close to the maximum")
    if underlying_price > 0:
        delta_notional = (
            contracts * candidate.delta * candidate.multiplier * underlying_price
        )
        if abs(delta_notional) > account_check.equity * 0.5:
            warnings.append(
                f"delta notional ${delta_notional:,.2f} exceeds 50% of equity"
            )

    return CandidateCheck(
        allowed=not blockers and contracts >= limits.min_contracts,
        contracts=max(0, contracts),
        premium_per_contract=premium,
        estimated_fees=fee * max(0, contracts),
        estimated_cost=(premium + fee) * max(0, contracts),
        max_loss=(premium + fee) * max(0, contracts),
        spread_pct=candidate.spread_pct,
        dte=dte,
        blockers=blockers,
        warnings=warnings,
    )
