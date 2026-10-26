"""Deterministic BTC/ETH swing-options paper lane.

The lane is deliberately simple and reproducible:

- daily trend filter: close > SMA50 > SMA200 for long, inverse for short;
- positive/negative 20-day momentum confirmation;
- long calls for long signals and long puts for short signals;
- 21-45 DTE, 0.40-0.60 delta, tight spread;
- explicit +50% profit target, -50% stop, 7-DTE exit, and time stop;
- no naked short options and no live broker.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

from tradingbot.config import AppConfig
from tradingbot.data.store import load_bars
from tradingbot.ops.heartbeat import write_heartbeat
from tradingbot.ops.performance import append_performance
from tradingbot.ops.risk_state import load_peak, save_peak
from tradingbot.options.account import (
    AccountCheck,
    OptionAccount,
    OptionCandidate,
    OptionLimits,
    check_account,
)
from tradingbot.options.audit import append_option_events
from tradingbot.options.broker import (
    OptionFill,
    OptionHolding,
    OptionSettlement,
    PaperOptionsBroker,
)
from tradingbot.options.deribit import DeribitPublicClient
from tradingbot.options.selector import Direction, SelectionResult, select_candidate


@dataclass(frozen=True)
class SwingSignal:
    underlying: str
    direction: Direction
    close: float
    sma50: float
    sma200: float
    momentum20: float
    reason: str


@dataclass(frozen=True)
class SwingExit:
    instrument: str
    underlying: str
    reason: str
    qty: int
    premium: float
    pnl: float
    status: str


@dataclass
class SwingCycleResult:
    status: str
    as_of: datetime
    signals: dict[str, SwingSignal]
    exits: list[SwingExit] = field(default_factory=list)
    fills: list[OptionFill] = field(default_factory=list)
    settlements: list[OptionSettlement] = field(default_factory=list)
    selections: list[SelectionResult] = field(default_factory=list)
    account_before: OptionAccount | None = None
    account_after: OptionAccount | None = None
    account_check: AccountCheck | None = None
    alerts: list[str] = field(default_factory=list)
    report_path: Path | None = None


def _resolve(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def build_swing_signals(
    bars: pl.DataFrame,
    *,
    assets: tuple[tuple[str, str], ...] = (("BTCUSDT", "BTC"), ("ETHUSDT", "ETH")),
) -> dict[str, SwingSignal]:
    """Build daily trend signals without look-ahead."""
    signals: dict[str, SwingSignal] = {}
    for symbol, underlying in assets:
        frame = bars.filter(pl.col("asset") == symbol).sort("timestamp")
        if frame.is_empty():
            signals[underlying] = SwingSignal(
                underlying, "flat", 0.0, 0.0, 0.0, 0.0, "no data"
            )
            continue
        closes = [float(value) for value in frame["close"].to_list()]
        close = closes[-1]
        if len(closes) < 200:
            signals[underlying] = SwingSignal(
                underlying, "flat", close, 0.0, 0.0, 0.0, "insufficient history"
            )
            continue
        sma50 = sum(closes[-50:]) / 50.0
        sma200 = sum(closes[-200:]) / 200.0
        momentum20 = close / closes[-21] - 1.0 if closes[-21] > 0 else 0.0
        if close > sma50 > sma200 and momentum20 > 0:
            direction: Direction = "long"
            reason = "close > SMA50 > SMA200 with positive 20d momentum"
        elif close < sma50 < sma200 and momentum20 < 0:
            direction = "short"
            reason = "close < SMA50 < SMA200 with negative 20d momentum"
        else:
            direction = "flat"
            reason = "trend and momentum not aligned"
        signals[underlying] = SwingSignal(
            underlying, direction, close, sma50, sma200, momentum20, reason
        )
    return signals


def _exit_reason(
    holding: OptionHolding,
    quote: OptionCandidate | None,
    signal: SwingSignal,
    *,
    now: datetime,
    limits: OptionLimits,
    profit_target_pct: float,
    stop_loss_pct: float,
    max_holding_days: int,
) -> str | None:
    dte = (holding.expiry - now.date()).days
    if dte <= limits.exit_dte:
        return "dte_exit"
    mark = quote.bid if quote is not None and quote.bid > 0 else holding.mark_premium
    if holding.entry_premium > 0:
        if mark >= holding.entry_premium * (1.0 + profit_target_pct):
            return "profit_target"
        if mark <= holding.entry_premium * (1.0 - stop_loss_pct):
            return "stop_loss"
    if holding.opened_on:
        try:
            opened = date.fromisoformat(holding.opened_on)
            if (now.date() - opened).days >= max_holding_days:
                return "time_stop"
        except ValueError:
            pass
    if signal.direction == "flat":
        return "trend_exit"
    expected_type = "call" if signal.direction == "long" else "put"
    if holding.option_type != expected_type:
        return "trend_reversal"
    return None


def _write_report(
    root: Path,
    result: SwingCycleResult,
    *,
    limits: OptionLimits,
) -> Path:
    out_dir = _resolve(root, Path("artifacts/options_swing/reports"))
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "pipeline": "options_swing",
        "status": result.status,
        "as_of": result.as_of.isoformat(),
        "signals": {key: asdict(signal) for key, signal in result.signals.items()},
        "exits": [asdict(exit_) for exit_ in result.exits],
        "fills": [asdict(fill) for fill in result.fills],
        "settlements": [asdict(settlement) for settlement in result.settlements],
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
        "account_before": (
            {
                "cash": result.account_before.cash,
                "equity": result.account_before.equity(),
                "legs": len(result.account_before.positions),
            }
            if result.account_before
            else None
        ),
        "account_after": (
            {
                "cash": result.account_after.cash,
                "equity": result.account_after.equity(),
                "legs": len(result.account_after.positions),
            }
            if result.account_after
            else None
        ),
        "limits": {
            "min_dte": limits.min_dte,
            "max_dte": limits.max_dte,
            "exit_dte": limits.exit_dte,
            "max_open_legs": limits.max_open_legs,
            "max_premium_per_trade_pct": limits.max_premium_per_trade_pct,
            "max_total_premium_pct": limits.max_total_premium_pct,
        },
        "alerts": result.alerts,
        "limitation": "Paper-only long-premium swing options; no live order path.",
    }
    json_path = out_dir / "latest.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    account_after = result.account_after
    if account_after is None:
        raise RuntimeError("cannot write swing report without account state")
    lines = [
        "# Options swing paper cycle",
        "",
        f"- Status: **{result.status}**",
        f"- As of: **{result.as_of.isoformat()}**",
        f"- Equity: **${account_after.equity():,.2f}**",
        f"- Cash: **${account_after.cash:,.2f}**",
        f"- Legs: **{len(account_after.positions)}**",
        "",
        "## Signals",
        "",
        "| Underlying | Direction | Close | Momentum 20d | Reason |",
        "|---|---|---:|---:|---|",
    ]
    for signal in result.signals.values():
        lines.append(
            f"| {signal.underlying} | {signal.direction} | "
            f"{signal.close:,.2f} | {signal.momentum20:.2%} | {signal.reason} |"
        )
    lines.extend(
        [
            "",
            "## Exits",
            "",
            "| Instrument | Reason | Qty | Premium | P&L |",
            "|---|---|---:|---:|---:|",
        ]
    )
    if result.exits:
        for exit_ in result.exits:
            lines.append(
                f"| {exit_.instrument} | {exit_.reason} | {exit_.qty} | "
                f"{exit_.premium:,.2f} | {exit_.pnl:,.2f} |"
            )
    else:
        lines.append("| — | none | — | — | — |")
    lines.extend(
        [
            "",
            "## Fills",
            "",
            "| Instrument | Side | Qty | Premium | Status |",
            "|---|---|---:|---:|---|",
        ]
    )
    if result.fills:
        for fill in result.fills:
            lines.append(
                f"| {fill.instrument} | {fill.side} | {fill.qty} | "
                f"{fill.premium:,.2f} | {fill.status} |"
            )
    else:
        lines.append("| — | — | — | — | none |")
    lines.extend(["", "No live order path is reachable from this lane.", ""])
    (out_dir / "latest.md").write_text("\n".join(lines), encoding="utf-8")
    return json_path


def run_options_swing_cycle(
    config: AppConfig,
    *,
    root: Path | None = None,
    chain: list[OptionCandidate] | None = None,
    bars: pl.DataFrame | None = None,
    now: datetime | None = None,
    signals_override: dict[str, SwingSignal] | None = None,
) -> SwingCycleResult:
    """Run one deterministic swing-options paper cycle."""
    root = root or Path.cwd()
    now = _to_utc(now or datetime.now(UTC))
    if config.broker.name != "paper" or not config.broker.paper:
        raise PermissionError("options swing lane must use a paper broker")

    kill_path = _resolve(root, config.risk.kill_switch_file)
    if kill_path.exists():
        raise PermissionError(f"kill switch active: {kill_path}")

    if bars is None:
        bars_path = _resolve(root, config.data.bars_path)
        if not bars_path.exists():
            raise FileNotFoundError(f"missing bars: {bars_path}")
        bars = load_bars(bars_path)
    completed = bars.filter(
        pl.col("timestamp").dt.date() < now.date()
    ).sort(["timestamp", "asset"])
    if completed.is_empty():
        raise RuntimeError("no completed daily bars available")
    as_of = completed["timestamp"].max()
    if not isinstance(as_of, datetime):
        raise RuntimeError("bars have no valid timestamp")
    as_of = _to_utc(as_of)
    signals = signals_override or build_swing_signals(completed)

    state_path = _resolve(root, config.broker.state_path)
    broker = PaperOptionsBroker(
        cash=config.broker.initial_cash,
        fee_bps=config.swing.fee_bps,
        state_path=state_path,
    )
    broker.load()
    peak_path = _resolve(root, config.risk.state_path)
    peak = load_peak(peak_path)
    current_equity = broker.account().equity()
    if peak is None:
        save_peak(peak_path, current_equity)
    elif (
        config.risk.auto_kill_on_drawdown
        and peak > 0
        and current_equity / peak - 1.0 < -config.risk.max_drawdown
    ):
        kill_path.parent.mkdir(parents=True, exist_ok=True)
        kill_path.write_text(
            f"drawdown {current_equity / peak - 1.0:.2%} breached "
            f"max {config.risk.max_drawdown:.2%}",
            encoding="utf-8",
        )
        raise PermissionError(
            f"swing drawdown limit breached; kill switch active: {kill_path}"
        )

    if chain is None:
        chain = DeribitPublicClient().fetch_chain(("BTC", "ETH"), now=now)
    if not chain:
        raise RuntimeError("Deribit returned no option chain")

    limits = config.swing.to_option_limits()
    quotes = {candidate.instrument: candidate for candidate in chain}
    underlying_prices = {
        "BTC": next(
            (signal.close for signal in signals.values() if signal.underlying == "BTC"),
            0.0,
        ),
        "ETH": next(
            (signal.close for signal in signals.values() if signal.underlying == "ETH"),
            0.0,
        ),
    }
    broker.mark_to_chain(chain)
    account_before = broker.account()
    settlements = broker.settle_expired(underlying_prices, today=now.date())
    alerts: list[str] = []
    for settlement in settlements:
        if settlement.status != "settled":
            alerts.append(f"{settlement.instrument}: {settlement.status}")

    exits: list[SwingExit] = []
    for instrument, holding in list(broker.holdings.items()):
        signal = signals.get(holding.underlying)
        if signal is None:
            continue
        quote = quotes.get(instrument)
        reason = _exit_reason(
            holding,
            quote,
            signal,
            now=now,
            limits=limits,
            profit_target_pct=config.swing.profit_target_pct,
            stop_loss_pct=config.swing.stop_loss_pct,
            max_holding_days=config.swing.max_holding_days,
        )
        if reason is None:
            continue
        if quote is None or quote.bid <= 0:
            alerts.append(f"{instrument}: {reason} but no bid to close")
            continue
        fill = broker.sell(quote, holding.qty, now=now)
        exits.append(
            SwingExit(
                instrument=instrument,
                underlying=holding.underlying,
                reason=reason,
                qty=holding.qty,
                premium=fill.premium,
                pnl=(fill.premium - holding.entry_premium) * holding.qty,
                status=fill.status,
            )
        )
        if fill.status != "filled":
            alerts.append(f"{instrument}: exit rejected: {fill.reason}")

    account = broker.account()
    account_check = check_account(account, limits, now=now)
    selections: list[SelectionResult] = []
    fills: list[OptionFill] = []
    if account_check.allowed:
        for underlying, signal in signals.items():
            if signal.direction == "flat":
                continue
            desired_type = "call" if signal.direction == "long" else "put"
            if any(
                holding.underlying == underlying
                and holding.option_type == desired_type
                for holding in broker.holdings.values()
            ):
                continue
            selection = select_candidate(
                broker.account(),
                chain,
                underlying=underlying,
                direction=signal.direction,
                limits=limits,
                underlying_price=underlying_prices.get(underlying, 0.0),
                now=now,
            )
            selections.append(selection)
            if selection.candidate is None or selection.candidate_check is None:
                alerts.extend(
                    f"{underlying}: {blocker}" for blocker in selection.blockers
                )
                continue
            contracts = min(
                config.swing.max_contracts, selection.candidate_check.contracts
            )
            if contracts <= 0:
                alerts.append(f"{underlying}: no contracts available")
                continue
            fill = broker.buy(selection.candidate, contracts, now=now)
            fills.append(fill)
            if fill.status != "filled":
                alerts.append(f"{underlying}: entry rejected: {fill.reason}")

    broker.save()
    account_after = broker.account()
    if account_after.equity() > (peak or 0.0):
        save_peak(peak_path, account_after.equity())
    if settlements or fills or exits:
        if not state_path.exists():
            state_path.parent.mkdir(parents=True, exist_ok=True)
        append_option_events(
            _resolve(root, Path("artifacts/options_swing/fills.jsonl")),
            as_of=as_of.isoformat(),
            equity=account_after.equity(),
            cash=account_after.cash,
            fills=fills,
            settlements=settlements,
        )
    result = SwingCycleResult(
        status="ok" if not alerts else "ok_with_alerts",
        as_of=as_of,
        signals=signals,
        exits=exits,
        fills=fills,
        settlements=settlements,
        selections=selections,
        account_before=account_before,
        account_after=account_after,
        account_check=account_check,
        alerts=alerts,
    )
    report_path = _write_report(root, result, limits=limits)
    result.report_path = report_path
    gross_exposure = (
        sum(position.premium_value() for position in account_after.positions)
        / max(account_after.equity(), 1e-9)
    )
    append_performance(
        _resolve(root, config.broker.performance_path),
        {
            "pipeline": "options_swing",
            "as_of": as_of.isoformat(),
            "signals": {key: signal.direction for key, signal in signals.items()},
            "equity": account_after.equity(),
            "cash": account_after.cash,
            "gross_exposure": gross_exposure,
            "n_orders": len(fills) + len(exits),
            "n_fills": sum(
                1 for fill in fills if fill.status == "filled"
            )
            + sum(1 for exit_ in exits if exit_.status == "filled"),
            "fees": sum(fill.fee for fill in fills),
            "positions": len(account_after.positions),
            "exits": len(exits),
        },
    )
    write_heartbeat(
        _resolve(root, config.broker.heartbeat_path),
        {
            "pipeline": "options_swing",
            "status": result.status,
            "equity": account_after.equity(),
            "cash": account_after.cash,
            "positions": len(account_after.positions),
            "signals": {key: signal.direction for key, signal in signals.items()},
        },
    )
    return result
