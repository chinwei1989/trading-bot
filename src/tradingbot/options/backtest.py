"""Event-driven options replay over recorded or synthetic chain snapshots.

The replay engine intentionally does not fetch data. A snapshot must contain the
chain and underlying prices that were available at its decision timestamp. This
makes look-ahead the caller's responsibility and keeps the engine deterministic.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from tradingbot.options.account import OptionCandidate, OptionLimits
from tradingbot.options.broker import OptionFill, PaperOptionsBroker
from tradingbot.options.pipeline import OptionsCycleResult, run_options_cycle
from tradingbot.options.selector import Direction


@dataclass(frozen=True)
class OptionSnapshot:
    timestamp: datetime
    chain: list[OptionCandidate]
    underlying_prices: dict[str, float]


SignalFn = Callable[[OptionSnapshot], dict[str, Direction]]


@dataclass
class ReplayCycle:
    timestamp: datetime
    equity: float
    cash: float
    open_legs: int
    fills: list[OptionFill] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)


@dataclass
class OptionReplayResult:
    cycles: list[ReplayCycle]
    final_equity: float
    total_return: float
    max_drawdown: float
    total_fills: int
    total_fees: float
    cycles_blocked: int


def _max_drawdown(equity: list[float]) -> float:
    best = 0.0
    peak = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            best = min(best, value / peak - 1.0)
    return best


def replay_options(
    snapshots: list[OptionSnapshot],
    signal: SignalFn,
    *,
    initial_cash: float = 10_000.0,
    limits: OptionLimits | None = None,
    fee_bps: float = 3.0,
    max_contracts: int = 1,
) -> OptionReplayResult:
    """Run the paper options cycle over snapshots in timestamp order.

    The signal function must use only the snapshot passed to it. This engine does
    not know whether the chain is historical or synthetic.
    """
    if not snapshots:
        raise ValueError("no option snapshots")
    ordered = sorted(snapshots, key=lambda item: item.timestamp)
    broker = PaperOptionsBroker(cash=initial_cash, fee_bps=fee_bps)
    cycles: list[ReplayCycle] = []
    seen: set[datetime] = set()
    total_fees = 0.0
    blocked = 0

    for snapshot in ordered:
        if snapshot.timestamp in seen:
            raise ValueError(f"duplicate snapshot timestamp: {snapshot.timestamp}")
        seen.add(snapshot.timestamp)
        directions = signal(snapshot)
        result: OptionsCycleResult = run_options_cycle(
            broker,
            snapshot.chain,
            directions,
            snapshot.underlying_prices,
            limits=limits,
            now=snapshot.timestamp,
            max_contracts=max_contracts,
        )
        account = result.account_after
        for fill in result.fills:
            total_fees += fill.fee
        if result.status == "blocked":
            blocked += 1
        cycles.append(
            ReplayCycle(
                timestamp=snapshot.timestamp,
                equity=account.equity(),
                cash=account.cash,
                open_legs=len(account.positions),
                fills=result.fills,
                alerts=result.alerts,
            )
        )

    equity = [cycle.equity for cycle in cycles]
    final = equity[-1]
    return OptionReplayResult(
        cycles=cycles,
        final_equity=final,
        total_return=final / initial_cash - 1.0 if initial_cash else 0.0,
        max_drawdown=_max_drawdown(equity),
        total_fills=sum(len(cycle.fills) for cycle in cycles),
        total_fees=total_fees,
        cycles_blocked=blocked,
    )
