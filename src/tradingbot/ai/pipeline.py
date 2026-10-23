"""Separate AI-agent paper pipeline.

This module is intentionally isolated from the deterministic campaign:
different config, broker state, journal, performance history, reports, and
heartbeat. The only shared inputs are read-only market data and code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from tradingbot.ai.audit import append_decision, write_audit, write_report
from tradingbot.ai.context import build_context
from tradingbot.ai.decision import AgentDecision
from tradingbot.ai.policy import PolicyApplication, apply_policy
from tradingbot.ai.providers import (
    DecisionProvider,
    DeterministicProvider,
    build_provider,
)
from tradingbot.config import AppConfig
from tradingbot.data.store import load_bars
from tradingbot.execution.manager import OrderManager
from tradingbot.execution.orders import OrderJournal, plan_orders
from tradingbot.execution.paper import PaperBroker
from tradingbot.execution.state import OrderStateStore
from tradingbot.ops.heartbeat import write_heartbeat
from tradingbot.ops.performance import append_performance
from tradingbot.portfolio.risk import assert_safe


@dataclass
class AIPipelineResult:
    status: str
    as_of: str
    equity: float
    cash: float
    provider: str
    model: str
    fallback: bool
    decision: AgentDecision | None = None
    policy: PolicyApplication | None = None
    orders: list[Any] = field(default_factory=list)
    fills: list[Any] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    report_path: Path | None = None
    audit_path: Path | None = None


def _resolve(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def _completed_bars(bars: pl.DataFrame) -> pl.DataFrame:
    today = datetime.now(UTC).date()
    return bars.filter(pl.col("timestamp").dt.date() < today)


def _last_prices(bars: pl.DataFrame) -> dict[str, float]:
    last = bars.sort("timestamp").group_by("asset").tail(1)
    return {str(row["asset"]): float(row["close"]) for row in last.iter_rows(named=True)}


def _ai_dir(root: Path, config: AppConfig) -> Path:
    return _resolve(root, config.agent.artifacts_dir)


def _archive_for_reset(root: Path, config: AppConfig, ai_dir: Path) -> None:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    paths = [
        _resolve(root, config.broker.state_path),
        _resolve(root, config.broker.journal_path),
        _resolve(root, config.broker.order_state_path),
        _resolve(root, config.broker.performance_path),
        _resolve(root, config.broker.heartbeat_path),
        ai_dir / "decisions.jsonl",
    ]
    for path in paths:
        if path.exists():
            path.replace(path.with_name(f"{path.name}.bak-{stamp}"))


def _provider_for(config: AppConfig, override: str | None) -> DecisionProvider:
    if override:
        agent = config.agent.model_copy(update={"provider": override})
        return build_provider(agent)
    return build_provider(config.agent)


def _decision_payload(decision: AgentDecision) -> dict[str, Any]:
    return decision.model_dump(mode="json", exclude={"raw"})


def _policy_payload(policy: PolicyApplication) -> dict[str, Any]:
    return {
        "target_weights": {k: float(v) for k, v in policy.target_weights.items()},
        "gross": float(policy.gross),
        "turnover": float(policy.turnover),
        "notes": list(policy.notes),
    }


def _markdown(report: dict[str, Any]) -> str:
    account = report.get("account", {})
    decision = report.get("decision", {})
    policy = report.get("policy", {})
    lines = [
        "# AI agent paper decision",
        "",
        f"- As of: **{report.get('as_of')}**",
        f"- Status: **{report.get('status')}**",
        f"- Provider: **{report.get('provider')}** / `{report.get('model')}`",
        f"- Fallback: **{report.get('fallback')}**",
        f"- Regime: **{decision.get('regime')}**",
        f"- Confidence: **{decision.get('confidence', 0):.2%}**",
        f"- Equity: **${account.get('equity', 0):,.2f}**",
        f"- Cash: **${account.get('cash', 0):,.2f}**",
        "",
        "## Target weights",
        "",
        "| Asset | Target |",
        "|---|---:|",
    ]
    for asset, weight in sorted(policy.get("target_weights", {}).items()):
        lines.append(f"| {asset} | {weight:.2%} |")
    notes = policy.get("notes", [])
    if notes:
        lines.extend(["", "## Policy notes", ""])
        lines.extend(f"- {note}" for note in notes)
    alerts = report.get("alerts", [])
    if alerts:
        lines.extend(["", "## Alerts", ""])
        lines.extend(f"- {alert}" for alert in alerts)
    lines.extend(
        [
            "",
            "## Orders",
            "",
        ]
    )
    orders = report.get("orders", [])
    if not orders:
        lines.append("No orders.")
    else:
        lines.extend(
            [
                "| Asset | Side | Qty | Status |",
                "|---|---|---:|---|",
            ]
        )
        for order in orders:
            lines.append(
                f"| {order.get('asset')} | {order.get('side')} | "
                f"{float(order.get('qty', 0)):.8f} | {order.get('status')} |"
            )
    lines.extend(
        [
            "",
            f"Audit: `{report.get('audit_path', '')}`",
            "",
            "> The AI provider chooses direction/weights; the deterministic policy "
            "layer owns sizing, caps, cash, confidence gating, and turnover. "
            "This pipeline is paper-only.",
            "",
        ]
    )
    return "\n".join(lines)


def run_ai_cycle(
    config: AppConfig,
    *,
    root: Path | None = None,
    reset: bool = False,
    dry_run: bool = False,
    provider_override: str | None = None,
    as_of: datetime | None = None,
    fresh: bool = False,
) -> AIPipelineResult:
    root = root or Path.cwd()
    if not config.agent.enabled:
        raise PermissionError("agent.enabled is false in the AI pipeline config")
    if config.agent.paper_only and (
        config.broker.name != "paper" or not config.broker.paper
    ):
        raise PermissionError(
            "AI pipeline is paper-only; broker must be name=paper and paper=true"
        )
    ai_dir = _ai_dir(root, config)

    bars_path = _resolve(root, config.data.bars_path)
    if not bars_path.exists():
        raise FileNotFoundError(f"missing bars: {bars_path}")
    bars = _completed_bars(load_bars(bars_path))
    if as_of is not None:
        cutoff = as_of.astimezone(UTC) if as_of.tzinfo else as_of.replace(tzinfo=UTC)
        bars = bars.filter(pl.col("timestamp") <= cutoff)
    if bars.is_empty():
        raise RuntimeError("no completed bars available")
    as_of_ts = bars["timestamp"].max()
    if not isinstance(as_of_ts, datetime):
        raise RuntimeError("bars have no valid timestamp")
    as_of_iso = as_of_ts.isoformat()
    prices = _last_prices(bars)

    state_path = _resolve(root, config.broker.state_path)
    if reset:
        _archive_for_reset(root, config, ai_dir)

    broker = PaperBroker(
        cash=config.broker.initial_cash,
        prices=prices,
        commission_bps=config.backtest.cost_bps,
        slippage_bps=config.backtest.slippage_bps,
        allow_short=config.agent.policy.allow_short,
    )
    if not reset and not fresh:
        broker.load_state(state_path)
    account = broker.get_account()
    positions = broker.get_positions()
    position_qty = {asset: position.qty for asset, position in positions.items()}

    context = build_context(
        bars,
        cash=account.cash,
        equity=account.equity,
        positions=position_qty,
        policy=config.agent.policy,
        root=root,
        include_macro=config.agent.include_macro,
        include_sentiment=config.agent.include_sentiment,
        periods_per_year=config.backtest.periods_per_year,
    )

    alerts: list[str] = []
    requested_provider = provider_override or config.agent.provider
    if requested_provider == "squad":
        context["_squad_root"] = str(root)
    provider = _provider_for(config, provider_override)
    try:
        decision = provider.decide(context)
    except Exception as exc:
        if config.agent.fallback != "deterministic":
            alert = f"AI provider failed: {type(exc).__name__}: {exc}"
            account = broker.get_account()
            positions = broker.get_positions()
            current = {
                asset: float(
                    position.qty * prices.get(asset, position.avg_entry_price)
                    / max(account.equity, 1e-9)
                )
                for asset, position in positions.items()
            }
            policy = PolicyApplication(
                weights=pl.DataFrame(),
                target_weights=current,
                gross=sum(abs(value) for value in current.values()),
                turnover=0.0,
                notes=["Provider failure; no orders sent. Existing positions held."],
            )
            error_report: dict[str, Any] = {
                "pipeline": "ai_agent",
                "as_of": as_of_iso,
                "generated_at": datetime.now(UTC).isoformat(),
                "status": "error",
                "provider": requested_provider,
                "model": config.agent.model,
                "fallback": False,
                "data_age_days": int(context["market"]["data_age_days"]),
                "decision": {},
                "policy": _policy_payload(policy),
                "account": {
                    "equity": float(account.equity),
                    "cash": float(account.cash),
                    "positions": {
                        asset: {
                            "qty": float(position.qty),
                            "value": float(
                                position.qty
                                * prices.get(asset, position.avg_entry_price)
                            ),
                            "weight": current.get(asset, 0.0),
                        }
                        for asset, position in positions.items()
                    },
                },
                "orders": [],
                "alerts": [alert],
                "error": alert,
            }
            report_json, _ = write_report(
                root,
                report=error_report,
                markdown=_markdown(error_report),
                ai_dir=ai_dir,
            )
            append_decision(
                root,
                {
                    "as_of": as_of_iso,
                    "status": "error",
                    "provider": requested_provider,
                    "model": config.agent.model,
                    "fallback": False,
                    "regime": "neutral",
                    "confidence": 0.0,
                    "latency_ms": 0.0,
                    "target_weights": current,
                    "gross": sum(abs(value) for value in current.values()),
                    "turnover": 0.0,
                    "equity": float(account.equity),
                    "cash": float(account.cash),
                    "data_age_days": int(context["market"]["data_age_days"]),
                    "dry_run": dry_run,
                    "n_orders": 0,
                    "error": alert,
                },
                ai_dir=ai_dir,
            )
            write_heartbeat(
                _resolve(root, config.broker.heartbeat_path),
                {
                    "pipeline": "ai_agent",
                    "status": "error",
                    "provider": requested_provider,
                    "error": alert,
                    "as_of": as_of_iso,
                },
            )
            return AIPipelineResult(
                status="error",
                as_of=as_of_iso,
                equity=float(account.equity),
                cash=float(account.cash),
                provider=requested_provider,
                model=config.agent.model,
                fallback=False,
                policy=policy,
                alerts=[alert],
                report_path=report_json,
            )
        decision = DeterministicProvider().decide(context)
        alerts.append(
            "AI provider unavailable; deterministic fallback used — this is not an AI decision"
        )
        alerts.append(f"Provider error: {type(exc).__name__}: {exc}")

    policy = apply_policy(decision, context, config.agent.policy)
    kill_file = _resolve(root, config.risk.kill_switch_file)
    assert_safe(policy.weights, config.risk, kill_file=kill_file)

    data_age = int(context["market"]["data_age_days"])
    if data_age > 2:
        alerts.append(f"stale market data: {data_age} days old")
    if decision.fallback:
        alerts.append("decision came from the labelled fallback provider")

    orders: list[Any] = []
    fills: list[Any] = []
    if not dry_run:
        orders = plan_orders(
            policy.weights,
            account.equity,
            prices,
            positions,
            min_notional=config.broker.min_notional,
            allow_short=config.agent.policy.allow_short,
        )
        journal_path = _resolve(root, config.broker.journal_path)
        order_state_path = _resolve(root, config.broker.order_state_path)
        journal = OrderJournal(journal_path)
        state = OrderStateStore(order_state_path)
        manager = OrderManager(
            broker,
            state,
            journal,
            max_child_notional=config.broker.max_child_notional,
            max_children=config.broker.max_children,
        )
        manager.assert_reconciled()
        fills = manager.execute(orders)
        journal.close()
        state.close()
        broker.save_state(state_path)

    account = broker.get_account()
    positions = broker.get_positions()
    gross = sum(
        abs(position.qty) * prices.get(asset, position.avg_entry_price)
        for asset, position in positions.items()
    ) / max(account.equity, 1e-9)
    position_report = {
        asset: {
            "qty": float(position.qty),
            "value": float(position.qty * prices.get(asset, position.avg_entry_price)),
            "weight": float(
                position.qty * prices.get(asset, position.avg_entry_price)
                / max(account.equity, 1e-9)
            ),
        }
        for asset, position in positions.items()
    }

    request_payload = decision.raw.get("request", {}) if isinstance(decision.raw, dict) else {}
    response_payload = (
        decision.raw.get("response", decision.raw) if isinstance(decision.raw, dict) else {}
    )
    audit_path = write_audit(
        root,
        as_of=as_of_iso,
        provider=decision.provider,
        model=decision.model,
        request=request_payload if isinstance(request_payload, dict) else {},
        response=response_payload if isinstance(response_payload, dict) else {},
        decision=_decision_payload(decision),
        policy=_policy_payload(policy),
        orders=[
            {
                "asset": order.asset,
                "side": order.side,
                "qty": order.qty,
                "client_order_id": order.client_order_id,
                "reference_price": order.reference_price,
            }
            for order in orders
        ],
        fallback=decision.fallback,
        ai_dir=ai_dir,
    )

    report: dict[str, Any] = {
        "pipeline": "ai_agent",
        "as_of": as_of_iso,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "dry_run" if dry_run else "ok",
        "provider": decision.provider,
        "model": decision.model,
        "fallback": decision.fallback,
        "data_age_days": data_age,
        "decision": _decision_payload(decision),
        "policy": _policy_payload(policy),
        "account": {
            "equity": float(account.equity),
            "cash": float(account.cash),
            "gross_exposure": float(gross),
            "positions": position_report,
        },
        "orders": [
            {
                "asset": fill.asset,
                "side": fill.side,
                "qty": fill.qty,
                "filled_qty": fill.filled_qty,
                "avg_price": fill.avg_price,
                "status": fill.status,
                "message": fill.message,
            }
            for fill in fills
        ],
        "alerts": alerts,
        "audit_path": str(audit_path.relative_to(root)) if audit_path.is_relative_to(root) else str(audit_path),
    }
    report_json, _ = write_report(
        root, report=report, markdown=_markdown(report), ai_dir=ai_dir
    )
    append_decision(
        root,
        {
            "as_of": as_of_iso,
            "status": report["status"],
            "provider": decision.provider,
            "model": decision.model,
            "fallback": decision.fallback,
            "regime": decision.regime,
            "confidence": float(decision.confidence),
            "latency_ms": float(decision.latency_ms),
            "target_weights": {
                key: float(value) for key, value in policy.target_weights.items()
            },
            "gross": float(policy.gross),
            "turnover": float(policy.turnover),
            "equity": float(account.equity),
            "cash": float(account.cash),
            "data_age_days": data_age,
            "dry_run": dry_run,
            "n_orders": len(orders),
        },
        ai_dir=ai_dir,
    )

    if not dry_run:
        append_performance(
            _resolve(root, config.broker.performance_path),
            {
                "pipeline": "ai_agent",
                "provider": decision.provider,
                "model": decision.model,
                "fallback": decision.fallback,
                "regime": decision.regime,
                "confidence": float(decision.confidence),
                "equity": float(account.equity),
                "cash": float(account.cash),
                "gross_exposure": float(gross),
                "n_orders": len(orders),
                "n_fills": len(fills),
                "positions": len(positions),
            },
        )
        write_heartbeat(
            _resolve(root, config.broker.heartbeat_path),
            {
                "pipeline": "ai_agent",
                "status": "ok",
                "provider": decision.provider,
                "model": decision.model,
                "fallback": decision.fallback,
                "equity": float(account.equity),
                "cash": float(account.cash),
                "regime": decision.regime,
                "confidence": float(decision.confidence),
                "n_orders": len(orders),
                "n_fills": len(fills),
                "data_age_days": data_age,
                "as_of": as_of_iso,
            },
        )

    return AIPipelineResult(
        status=report["status"],
        as_of=as_of_iso,
        equity=float(account.equity),
        cash=float(account.cash),
        provider=decision.provider,
        model=decision.model,
        fallback=decision.fallback,
        decision=decision,
        policy=policy,
        orders=orders,
        fills=fills,
        alerts=alerts,
        report_path=report_json,
        audit_path=audit_path,
    )


def read_ai_report(
    root: Path | None = None,
    ai_dir: Path | None = None,
) -> dict[str, Any] | None:
    root = root or Path.cwd()
    path = (ai_dir or root / "artifacts" / "ai") / "reports" / "latest.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
