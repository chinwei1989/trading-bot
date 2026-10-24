"""Paper-only 30m AI options cycle.

The AI squad produces a direction per BTC/ETH. A deterministic selector turns
that direction into a long-premium call or put, then the existing option gates,
paper broker, expiry handling, and audit trail take over. No live broker is
reachable from this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from tradingbot.ai.audit import append_decision, write_report
from tradingbot.ai.context import build_context
from tradingbot.ai.decision import AgentDecision
from tradingbot.ai.providers import build_provider
from tradingbot.config import AppConfig
from tradingbot.data.intraday import completed_bars, refresh_recent_bars
from tradingbot.data.store import load_bars
from tradingbot.ops.heartbeat import write_heartbeat
from tradingbot.ops.performance import append_performance
from tradingbot.ops.risk_state import load_peak, save_peak
from tradingbot.options.account import OptionLimits
from tradingbot.options.audit import append_option_events
from tradingbot.options.broker import (
    OptionFill,
    OptionSettlement,
    PaperOptionsBroker,
)
from tradingbot.options.deribit import DeribitPublicClient
from tradingbot.options.pipeline import result_payload, run_options_cycle
from tradingbot.options.selector import Direction
from tradingbot.options.signals import directions_from_decision


@dataclass
class AIOptionsResult:
    status: str
    as_of: str
    equity: float
    cash: float
    provider: str
    model: str
    directions: dict[str, Direction]
    decision: AgentDecision | None = None
    paper: dict[str, Any] | None = None
    report_path: Path | None = None


def _resolve(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def _last_prices(bars: pl.DataFrame) -> dict[str, float]:
    last = bars.sort("timestamp").group_by("asset").tail(1)
    return {str(row["asset"]): float(row["close"]) for row in last.iter_rows(named=True)}


def _options_context(broker: PaperOptionsBroker, chain_count: int) -> dict[str, Any]:
    account = broker.account()
    return {
        "cash": account.cash,
        "equity": account.equity(),
        "premium_at_risk": account.premium_at_risk(),
        "legs": [
            {
                "instrument": position.instrument,
                "underlying": position.underlying,
                "type": position.option_type,
                "qty": position.qty,
                "strike": position.strike,
                "expiry": position.expiry.isoformat(),
                "mark": position.mark_premium,
                "delta": position.delta,
                "vega": position.vega,
                "theta": position.theta,
            }
            for position in account.positions
        ],
        "chain_count": chain_count,
        "long_premium_only": True,
    }


def run_ai_options_cycle(
    config: AppConfig,
    *,
    root: Path | None = None,
    dry_run: bool = False,
    reset: bool = False,
    provider_override: str | None = None,
    decision_provider: Any | None = None,
    chain_provider: Any | None = None,
    refresh: bool = True,
    now: datetime | None = None,
) -> AIOptionsResult:
    root = root or Path.cwd()
    if not config.agent.enabled:
        raise PermissionError("agent.enabled is false")
    if config.agent.paper_only and (
        config.broker.name != "paper" or not config.broker.paper
    ):
        raise PermissionError("AI options lane must use a paper broker")
    kill_path = _resolve(root, config.risk.kill_switch_file)
    if kill_path.exists():
        raise PermissionError(f"kill switch active: {kill_path}")

    if refresh and config.data.interval != "1d" and config.data.source == "binance":
        refresh_recent_bars(config.data, root, limit=config.data.recent_limit)
    bars_path = _resolve(root, config.data.bars_path)
    if not bars_path.exists():
        raise FileNotFoundError(f"missing bars: {bars_path}")
    bars = completed_bars(load_bars(bars_path), config.data.interval)
    if now is not None:
        cutoff = now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)
        bars = bars.filter(pl.col("timestamp") <= cutoff)
    if bars.is_empty():
        raise RuntimeError("no completed bars available")
    as_of = bars["timestamp"].max()
    if not isinstance(as_of, datetime):
        raise RuntimeError("bars have no valid timestamp")
    as_of = as_of.astimezone(UTC) if as_of.tzinfo else as_of.replace(tzinfo=UTC)
    as_of_iso = as_of.isoformat()
    prices = _last_prices(bars)

    state_path = _resolve(root, config.broker.state_path)
    broker = PaperOptionsBroker(
        cash=config.broker.initial_cash,
        fee_bps=3.0,
        state_path=state_path,
    )
    if not reset:
        broker.load()

    risk_peak_path = _resolve(root, config.risk.state_path)
    peak = load_peak(risk_peak_path)
    current_equity = broker.account().equity()
    if peak is None:
        if not dry_run:
            save_peak(risk_peak_path, current_equity)
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
            f"options drawdown limit breached; kill switch active: {kill_path}"
        )

    chain_client = chain_provider or DeribitPublicClient()
    chain = chain_client.fetch_chain(("BTC", "ETH"), now=as_of)
    if not chain:
        raise RuntimeError("Deribit returned no option chain")

    context = build_context(
        bars,
        cash=broker.account().cash,
        equity=broker.account().equity(),
        positions={},
        policy=config.agent.policy,
        root=root,
        include_macro=config.agent.include_macro,
        include_sentiment=config.agent.include_sentiment,
        periods_per_year=config.backtest.periods_per_year,
    )
    context["options"] = _options_context(broker, len(chain))

    provider = decision_provider or build_provider(
        config.agent.model_copy(update={"provider": provider_override})
        if provider_override
        else config.agent
    )
    decision = provider.decide(context)
    directions = directions_from_decision(
        decision,
        {"BTCUSDT": "BTC", "ETHUSDT": "ETH"},
    )
    paper: dict[str, Any]
    cycle_fills: list[OptionFill] = []
    cycle_settlements: list[OptionSettlement] = []
    total_fees = 0.0
    if dry_run:
        paper = {
            "status": "dry_run",
            "directions": directions,
            "chain_count": len(chain),
            "account": {
                "cash": broker.account().cash,
                "equity": broker.account().equity(),
            },
        }
    else:
        limits = OptionLimits()
        cycle = run_options_cycle(
            broker,
            chain,
            directions,
            {"BTC": prices.get("BTCUSDT", 0.0), "ETH": prices.get("ETHUSDT", 0.0)},
            limits=limits,
            now=as_of,
            max_contracts=1,
        )
        broker.save()
        paper = result_payload(cycle)
        cycle_fills = cycle.fills
        cycle_settlements = cycle.settlements
        total_fees = sum(fill.fee for fill in cycle_fills)

    ai_dir = _resolve(root, config.agent.artifacts_dir)
    ai_dir.mkdir(parents=True, exist_ok=True)
    if not dry_run:
        append_option_events(
            ai_dir / "fills.jsonl",
            as_of=as_of_iso,
            equity=broker.account().equity(),
            cash=broker.account().cash,
            fills=cycle_fills,
            settlements=cycle_settlements,
        )
    report_status = "dry_run" if dry_run else "ok"
    report: dict[str, Any] = {
        "pipeline": "ai_options",
        "as_of": as_of_iso,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": report_status,
        "provider": decision.provider,
        "model": decision.model,
        "regime": decision.regime,
        "confidence": decision.confidence,
        "directions": directions,
        "paper": paper,
        "alerts": [],
        "limitation": (
            "Paper-only long-premium options; Deribit data is converted to a "
            "USD-marked approximation. No live order path."
        ),
    }
    markdown = (
        "# AI options paper cycle\n\n"
        f"- As of: **{as_of_iso}**\n"
        f"- Provider: **{decision.provider} / {decision.model}**\n"
        f"- Regime: **{decision.regime}**\n"
        f"- Confidence: **{decision.confidence:.1%}**\n"
        f"- Directions: `{json.dumps(directions)}`\n"
        f"- Paper status: **{paper.get('status', 'unknown')}**\n"
    )
    report_path, _ = write_report(root, report=report, markdown=markdown, ai_dir=ai_dir)
    append_decision(
        root,
        {
            "as_of": as_of_iso,
            "status": report["status"],
            "provider": decision.provider,
            "model": decision.model,
            "regime": decision.regime,
            "confidence": decision.confidence,
            "directions": directions,
            "paper_status": paper.get("status"),
            "equity": paper.get("account_after", {}).get("equity")
            if not dry_run
            else broker.account().equity(),
            "cash": paper.get("account_after", {}).get("cash")
            if not dry_run
            else broker.account().cash,
            "dry_run": dry_run,
        },
        ai_dir=ai_dir,
    )
    account = broker.account()
    if not dry_run:
        save_peak(risk_peak_path, max(peak or 0.0, account.equity()))
        append_performance(
            _resolve(root, config.broker.performance_path),
            {
                "pipeline": "ai_options",
                "as_of": as_of_iso,
                "provider": decision.provider,
                "model": decision.model,
                "regime": decision.regime,
                "confidence": decision.confidence,
                "equity": account.equity(),
                "cash": account.cash,
                "gross_exposure": 0.0,
                "n_orders": len(paper.get("fills", [])),
                "n_fills": len(paper.get("fills", [])),
                "fees": total_fees,
                "positions": len(account.positions),
                "directions": directions,
            },
        )
    write_heartbeat(
        _resolve(root, config.broker.heartbeat_path),
        {
            "pipeline": "ai_options",
            "status": "ok",
            "provider": decision.provider,
            "model": decision.model,
            "equity": account.equity(),
            "cash": account.cash,
            "regime": decision.regime,
            "confidence": decision.confidence,
            "n_orders": len(paper.get("fills", [])) if not dry_run else 0,
            "positions": len(account.positions),
            "as_of": as_of_iso,
        },
    )
    return AIOptionsResult(
        status=report_status,
        as_of=as_of_iso,
        equity=account.equity(),
        cash=account.cash,
        provider=decision.provider,
        model=decision.model,
        directions=directions,
        decision=decision,
        paper=paper,
        report_path=report_path,
    )
