"""Read-only Streamlit dashboard for the deterministic and AI pipelines.

Run:
    uv run streamlit run src/tradingbot/ops/dashboard.py

The dashboard never places orders or changes config. It only reads reports,
performance history, heartbeats, and paper state. The deterministic campaign
and the AI-agent campaign are separate accounts with separate artifacts.
"""

from __future__ import annotations

import hmac
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import plotly.graph_objects as go  # type: ignore[import-untyped]
import streamlit as st
import streamlit.components.v1 as components

from tradingbot.config import AppConfig, load_config
from tradingbot.ops.evaluation import build_report, write_report
from tradingbot.ops.heartbeat import read_heartbeat
from tradingbot.ops.office3d import build_office_html
from tradingbot.ops.options_evidence import build_options_evidence
from tradingbot.ops.readiness import build_readiness

ROOT = Path(__file__).resolve().parents[3]
DET_CONFIGS = {
    "Crypto trend": "config/base.yaml",
    "Crypto XSMOM": "config/xsmom.yaml",
    "Crypto breakout": "config/breakout.yaml",
    "Crypto reversal": "config/reversal.yaml",
    "Crypto meta allocator": "config/meta.yaml",
    "US equities trend": "config/alpaca.yaml",
    "Long history BTC/LTC": "config/long_history.yaml",
    "Max history 8-asset": "config/max_history.yaml",
}
AI_CONFIG = "config/ai_agent.yaml"
AI_SQUAD_CONFIG = "config/ai_squad.yaml"
INTRADAY_CONFIG = "config/intraday_meta.yaml"
OPTIONS_FLOW_PATH = ROOT / "web" / "ai_options_flow.html"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _load_config(path: str) -> AppConfig | None:
    try:
        return load_config(ROOT / path)
    except Exception:
        return None


def _latest_squad_run() -> tuple[Path, dict[str, Any]] | None:
    base = ROOT / "artifacts" / "ai_squad" / "squad"
    if not base.exists():
        return None
    manifests = sorted(
        base.glob("*/manifest.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for manifest in manifests:
        payload = _load_json(manifest)
        if payload:
            return manifest.parent, payload
    return None


def _choice_summary(choices: Any) -> str:
    if not isinstance(choices, dict):
        return ""
    notable = [
        f"{asset}={value}"
        for asset, value in choices.items()
        if value not in {"flat", "unavailable", "neutral", "approve", "allow"}
    ]
    selected = notable or [f"{asset}={value}" for asset, value in choices.items()]
    return ", ".join(selected[:8])


def _perf_frame(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        frame = pd.read_json(path, lines=True)
    except ValueError:
        return pd.DataFrame()
    if "timestamp" in frame.columns:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    return frame.sort_values("timestamp") if "timestamp" in frame.columns else frame


def _add_equity_trace(fig: go.Figure, path: Path, name: str, color: str, dash: str = "solid") -> None:
    frame = _perf_frame(path)
    if frame.empty or "equity" not in frame.columns:
        return
    fig.add_trace(
        go.Scatter(
            x=frame["timestamp"],
            y=frame["equity"],
            mode="lines+markers" if len(frame) <= 5 else "lines",
            name=name,
            line=dict(color=color, width=2, dash=dash),
        )
    )


def _metric_row(report: dict[str, Any] | None) -> dict[str, Any]:
    if not report:
        return {}
    account = report.get("account", {})
    data = report.get("data", {})
    tca = report.get("tca", {})
    drift = report.get("signal_drift", {})
    return {
        "equity": float(account.get("equity", 0.0)),
        "cash": float(account.get("cash", 0.0)),
        "data_age": data.get("age_days", "?"),
        "tca": float(tca.get("weighted_slip_bps", 0.0)),
        "drift": drift.get("drift"),
        "alerts": report.get("alerts", []),
    }


def _render_deterministic() -> None:
    label = st.sidebar.selectbox("Config", list(DET_CONFIGS))
    config = _load_config(DET_CONFIGS[label])
    if config is None:
        st.error(f"Could not load {DET_CONFIGS[label]}")
        return
    strategy_options = ["trend", "xsmom", "breakout", "reversal", "meta"]
    strategy = st.sidebar.selectbox(
        "Strategy",
        strategy_options,
        index=strategy_options.index(config.strategy.name)
        if config.strategy.name in strategy_options
        else 0,
    )
    if st.sidebar.button("Rebuild evaluation"):
        rebuilt = build_report(config, strategy, ROOT)
        write_report(rebuilt, ROOT)
        st.sidebar.success("Report rebuilt")

    report_path = ROOT / "artifacts" / "reports" / f"evaluation_{strategy}.json"
    report = _load_json(report_path)
    if report is None:
        st.warning("No evaluation report yet. Click 'Rebuild evaluation'.")
        return

    metrics = _metric_row(report)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Equity", f"${metrics.get('equity', 0):,.2f}")
    c2.metric("Cash", f"${metrics.get('cash', 0):,.2f}")
    c3.metric("Data age", f"{metrics.get('data_age', '?')}d")
    c4.metric("TCA slip", f"{metrics.get('tca', 0):.1f} bps")
    c5.metric("Signal drift", f"{(metrics.get('drift') or 0):.1%}")

    alerts = metrics.get("alerts", [])
    if alerts:
        st.error("Alerts: " + " · ".join(str(a) for a in alerts))
    else:
        st.success("No alerts.")

    perf_path = ROOT / config.broker.performance_path
    bt_path = ROOT / config.backtest.output_dir / f"backtest_{strategy}_daily.csv"
    fig = go.Figure()
    _add_equity_trace(fig, perf_path, "paper/live", "#1565C0")
    if bt_path.exists():
        try:
            bt = pd.read_csv(bt_path)
        except Exception:
            bt = pd.DataFrame()
        if "timestamp" in bt.columns and "equity" in bt.columns:
            bt["timestamp"] = pd.to_datetime(bt["timestamp"], utc=True)
            fig.add_trace(
                go.Scatter(
                    x=bt["timestamp"],
                    y=bt["equity"],
                    mode="lines",
                    name="backtest",
                    line=dict(color="#9E9E9E", width=1.2),
                )
            )
    fig.update_layout(
        title="Equity: paper/live vs backtest",
        height=420,
        margin=dict(l=20, r=20, t=40, b=20),
        hovermode="x unified",
    )
    st.plotly_chart(fig, width="stretch")

    left, right = st.columns(2)
    with left:
        st.subheader("Live vs backtest")
        st.json(report.get("live_vs_backtest", {}))
        st.subheader("Rolling metrics")
        st.json(report.get("rolling", {}))
    with right:
        st.subheader("TCA / slippage")
        st.json(report.get("tca", {}))
        st.subheader("Order health (7d)")
        st.json(report.get("order_health", {}))
        st.subheader("Signal drift")
        st.json(report.get("signal_drift", {}))

    st.subheader("Positions")
    positions = report.get("account", {}).get("positions", {})
    if positions:
        st.dataframe(
            pd.DataFrame(
                [{"asset": k, "qty": v} for k, v in positions.items()]
            ).sort_values("asset"),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No positions.")


def _render_ai() -> None:
    config = _load_config(AI_CONFIG)
    report = _load_json(ROOT / "artifacts" / "ai" / "reports" / "latest.json")
    if report is None:
        st.warning("No AI-agent report yet.")
        st.code(
            "powershell -ExecutionPolicy Bypass -File scripts/run_ai_pipeline.ps1",
            language="powershell",
        )
        st.caption(
            "Set TYPESAFE_API_KEY for Jev, or configure a local OpenAI-compatible "
            "endpoint in config/ai_agent.yaml. Without a provider the run is "
            "explicitly labelled as a deterministic fallback, not AI."
        )
        return

    account = report.get("account", {})
    decision = report.get("decision", {})
    policy = report.get("policy", {})
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("AI equity", f"${account.get('equity', 0):,.2f}")
    c2.metric("Cash", f"${account.get('cash', 0):,.2f}")
    c3.metric("Confidence", f"{float(decision.get('confidence', 0)):.1%}")
    c4.metric("Regime", str(decision.get("regime", "?")))
    c5.metric("Data age", f"{report.get('data_age_days', '?')}d")

    provider = report.get("provider", "?")
    model = report.get("model", "?")
    if report.get("status") == "error":
        st.error(
            "AI decision failed; no orders were sent. "
            f"{report.get('error', 'See the heartbeat for details.')}"
        )
    elif report.get("fallback"):
        st.warning(
            f"Fallback decision: `{provider}` / `{model}`. This is not an AI model. "
            "Configure TYPESAFE_API_KEY or a local LLM to use the AI path."
        )
    else:
        st.success(f"Decision provider: `{provider}` / `{model}`")
    if report.get("status") == "dry_run":
        st.info("This was a dry run: decisions and reports only, no orders.")
    if report.get("status") == "error":
        st.caption(
            "The AI pipeline fails closed: existing paper positions are held and "
            "no new orders are sent until the provider recovers."
        )
    alerts = report.get("alerts", [])
    if alerts:
        st.error("Alerts: " + " · ".join(str(a) for a in alerts))

    perf_path = ROOT / config.broker.performance_path if config else ROOT / "artifacts/ai/performance.jsonl"
    fig = go.Figure()
    _add_equity_trace(fig, perf_path, "AI agent paper", "#7B1FA2")
    _add_equity_trace(
        fig,
        ROOT / "artifacts" / "performance_trend.jsonl",
        "deterministic trend (reference)",
        "#1565C0",
        "dot",
    )
    fig.update_layout(
        title="AI-agent paper equity vs deterministic reference",
        height=420,
        margin=dict(l=20, r=20, t=40, b=20),
        hovermode="x unified",
    )
    st.plotly_chart(fig, width="stretch")

    scorecard = _load_json(ROOT / "artifacts" / "ai" / "reports" / "scorecard.json")
    if scorecard:
        st.subheader("AI scorecard")
        sm = scorecard.get("metrics", {})
        sp = scorecard.get("provider", {})
        sc1, sc2, sc3, sc4, sc5 = st.columns(5)
        sc1.metric("Days", f"{scorecard.get('n_days', 0)}")
        sc2.metric("Sharpe", f"{float(sm.get('sharpe', 0)):.2f}")
        sc3.metric("Max DD", f"{float(sm.get('max_dd', 0)):.1%}")
        sc4.metric("Fallback rate", f"{float(sp.get('fallback_rate', 0)):.0%}")
        sc5.metric(
            "TCA",
            f"{float(scorecard.get('tca', {}).get('weighted_slip_bps', 0)):.1f} bps",
        )
        if scorecard.get("status") != "ok":
            st.info(f"Scorecard status: {scorecard.get('status')}")
        for note in scorecard.get("notes", []):
            st.caption(f"- {note}")
    else:
        st.info("No AI scorecard yet. Run `uv run python -m tradingbot --config config/ai_agent.yaml ai-evaluate`.")

    st.subheader("Last decision")
    st.caption(
        f"As of {report.get('as_of', '?')} · policy turnover "
        f"{float(policy.get('turnover', 0)):.1%} · gross "
        f"{float(policy.get('gross', 0)):.1%}"
    )
    actions = decision.get("actions", [])
    target = policy.get("target_weights", {})
    if actions:
        rows = []
        for action in actions:
            rows.append(
                {
                    "asset": action.get("asset"),
                    "action": action.get("action"),
                    "confidence": float(action.get("confidence", 0)),
                    "target_weight": float(target.get(action.get("asset"), 0.0)),
                    "reason": action.get("reason", ""),
                }
            )
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    elif target:
        st.dataframe(
            pd.DataFrame(
                [{"asset": k, "target_weight": v} for k, v in target.items()]
            ).sort_values("asset"),
            width="stretch",
            hide_index=True,
        )

    notes = policy.get("notes", [])
    if notes:
        st.subheader("Policy notes")
        for note in notes:
            st.write(f"- {note}")

    left, right = st.columns(2)
    with left:
        st.subheader("Positions")
        positions = account.get("positions", {})
        if positions:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "asset": asset,
                            "qty": float(pos.get("qty", 0)),
                            "value": float(pos.get("value", 0)),
                            "weight": float(pos.get("weight", 0)),
                        }
                        for asset, pos in positions.items()
                    ]
                ).sort_values("asset"),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("No positions.")
    with right:
        st.subheader("Execution")
        orders = report.get("orders", [])
        if orders:
            st.dataframe(pd.DataFrame(orders), width="stretch", hide_index=True)
        else:
            st.info("No orders in this cycle.")
        st.caption(f"Audit: `{report.get('audit_path', '')}`")
        st.json(decision)

    st.caption(
        "AI chooses direction/weights. The deterministic policy layer owns sizing, "
        "caps, cash, confidence gating, and turnover. Paper only."
    )


def _render_ai_squad() -> None:
    config = _load_config(AI_SQUAD_CONFIG)
    report = _load_json(ROOT / "artifacts" / "ai_squad" / "reports" / "latest.json")
    if report is None:
        st.warning("No seven-agent AI squad report yet.")
        st.code(
            "powershell -ExecutionPolicy Bypass -File scripts/run_ai_squad.ps1",
            language="powershell",
        )
        st.caption(
            "The squad uses role-scoped Jev calls. The deterministic policy and "
            "risk checks still own sizing and execution."
        )
        return

    account = report.get("account", {})
    decision = report.get("decision", {})
    policy = report.get("policy", {})
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Squad equity", f"${account.get('equity', 0):,.2f}")
    c2.metric("Cash", f"${account.get('cash', 0):,.2f}")
    c3.metric("Confidence", f"{float(decision.get('confidence', 0)):.1%}")
    c4.metric("Regime", str(decision.get("regime", "?")))
    c5.metric("Data age", f"{report.get('data_age_days', '?')}d")
    c6.metric("Force rebalance", "yes" if decision.get("force_rebalance") else "no")

    provider = report.get("provider", "?")
    model = report.get("model", "?")
    if report.get("status") == "error":
        st.error(
            "Squad decision failed; no orders were sent. "
            f"{report.get('error', 'See the report and heartbeat.')}"
        )
    elif report.get("fallback"):
        st.warning(f"Fallback decision: `{provider}` / `{model}`. Not the AI squad.")
    else:
        st.success(f"Squad provider: `{provider}` / `{model}`")
    if report.get("status") == "dry_run":
        st.info("This was a dry run: decisions and reports only, no orders.")

    alerts = report.get("alerts", [])
    if alerts:
        st.error("Alerts: " + " | ".join(str(a) for a in alerts))

    perf_path = (
        ROOT / config.broker.performance_path
        if config
        else ROOT / "artifacts/ai_squad/performance.jsonl"
    )
    fig = go.Figure()
    _add_equity_trace(fig, perf_path, "AI squad paper", "#D81B60")
    _add_equity_trace(
        fig,
        ROOT / "artifacts" / "ai" / "performance.jsonl",
        "single-Jev paper",
        "#7B1FA2",
        "dot",
    )
    _add_equity_trace(
        fig,
        ROOT / "artifacts" / "performance_trend.jsonl",
        "deterministic trend (reference)",
        "#1565C0",
        "dot",
    )
    fig.update_layout(
        title="AI squad paper equity vs single-Jev and deterministic reference",
        height=420,
        margin=dict(l=20, r=20, t=40, b=20),
        hovermode="x unified",
    )
    st.plotly_chart(fig, width="stretch")

    scorecard = _load_json(
        ROOT / "artifacts" / "ai_squad" / "reports" / "scorecard.json"
    )
    if scorecard:
        st.subheader("Squad scorecard")
        sm = scorecard.get("metrics", {})
        sp = scorecard.get("provider", {})
        sc1, sc2, sc3, sc4, sc5 = st.columns(5)
        sc1.metric("Days", f"{scorecard.get('n_days', 0)}")
        sc2.metric("Sharpe", f"{float(sm.get('sharpe', 0)):.2f}")
        sc3.metric("Max DD", f"{float(sm.get('max_dd', 0)):.1%}")
        sc4.metric("Fallback rate", f"{float(sp.get('fallback_rate', 0)):.0%}")
        sc5.metric(
            "TCA",
            f"{float(scorecard.get('tca', {}).get('weighted_slip_bps', 0)):.1f} bps",
        )
        if scorecard.get("status") != "ok":
            st.info(f"Scorecard status: {scorecard.get('status')}")
        for note in scorecard.get("notes", []):
            st.caption(f"- {note}")

    latest = _latest_squad_run()
    if latest:
        run_dir, manifest = latest
        st.subheader("Latest squad blackboard")
        st.caption(
            f"Run `{manifest.get('run_id', run_dir.name)}` · "
            f"{len(manifest.get('agents', []))} agents · read-only memos"
        )
        memo_rows: list[dict[str, Any]] = []
        for stage, filename in (manifest.get("memos") or {}).items():
            memo = _load_json(run_dir / str(filename))
            if not memo:
                continue
            memo_rows.append(
                {
                    "agent": memo.get("agent", stage),
                    "stage": stage,
                    "regime": memo.get("regime", ""),
                    "confidence": float(memo.get("confidence", 0)),
                    "model": memo.get("model", ""),
                    "choices": _choice_summary(memo.get("choices", {})),
                }
            )
        if memo_rows:
            st.dataframe(
                pd.DataFrame(memo_rows), width="stretch", hide_index=True
            )
        st.caption(f"Blackboard: `{run_dir}`")
    else:
        st.info("No squad blackboard found yet.")

    st.subheader("Last decision")
    st.caption(
        f"As of {report.get('as_of', '?')} | policy turnover "
        f"{float(policy.get('turnover', 0)):.1%} | gross "
        f"{float(policy.get('gross', 0)):.1%}"
    )
    actions = decision.get("actions", [])
    target = policy.get("target_weights", {})
    if actions:
        rows = []
        for action in actions:
            rows.append(
                {
                    "asset": action.get("asset"),
                    "action": action.get("action"),
                    "confidence": float(action.get("confidence", 0)),
                    "target_weight": float(target.get(action.get("asset"), 0.0)),
                    "reason": action.get("reason", ""),
                }
            )
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    elif target:
        st.dataframe(
            pd.DataFrame(
                [{"asset": k, "target_weight": v} for k, v in target.items()]
            ).sort_values("asset"),
            width="stretch",
            hide_index=True,
        )

    notes = policy.get("notes", [])
    if notes:
        st.subheader("Policy notes")
        for note in notes:
            st.write(f"- {note}")

    left, right = st.columns(2)
    with left:
        st.subheader("Positions")
        positions = account.get("positions", {})
        if positions:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "asset": asset,
                            "qty": float(pos.get("qty", 0)),
                            "value": float(pos.get("value", 0)),
                            "weight": float(pos.get("weight", 0)),
                        }
                        for asset, pos in positions.items()
                    ]
                ).sort_values("asset"),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("No positions.")
    with right:
        st.subheader("Execution")
        orders = report.get("orders", [])
        if orders:
            st.dataframe(pd.DataFrame(orders), width="stretch", hide_index=True)
        else:
            st.info("No orders in this cycle.")
        st.caption(f"Audit: `{report.get('audit_path', '')}`")

    st.caption(
        "Eight role-scoped Jev calls share typed memos through a blackboard. "
        "Risk vetoes and execution blocks are enforced by deterministic code; "
        "sizing and paper execution remain outside the LLM. Paper only."
    )


def _render_ai_options() -> None:
    report = _load_json(
        ROOT / "artifacts" / "ai_options_30m" / "reports" / "latest.json"
    )
    if report is None:
        st.warning("No 30m AI options report yet.")
        st.code(
            "uv run python -m tradingbot --config config/ai_options_30m.yaml "
            "ai-options-run",
            language="powershell",
        )
        return
    paper = report.get("paper", {})
    account = paper.get("account_after", {})
    check = paper.get("account_check", {})
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Options equity", f"${float(account.get('equity', 0)):,.2f}")
    c2.metric("Cash", f"${float(account.get('cash', 0)):,.2f}")
    c3.metric("Legs", f"{int(account.get('legs', 0))}")
    c4.metric("Regime", str(report.get("regime", "?")))
    c5.metric("Confidence", f"{float(report.get('confidence', 0)):.1%}")
    st.caption(
        f"Provider `{report.get('provider', '?')}` / `{report.get('model', '?')}` · "
        f"as of `{report.get('as_of', '?')}` · "
        f"available premium ${float(check.get('available_premium', 0)):,.2f} · "
        f"max new trade ${float(check.get('max_new_trade_premium', 0)):,.2f}"
    )
    st.write("**Directions**")
    directions = report.get("directions", {})
    if directions:
        st.dataframe(
            pd.DataFrame(
                [{"underlying": key, "direction": value} for key, value in directions.items()]
            ),
            width="stretch",
            hide_index=True,
        )
    st.write("**Paper fills**")
    fills = paper.get("fills", [])
    if fills:
        st.dataframe(pd.DataFrame(fills), width="stretch", hide_index=True)
    else:
        st.info("No option fills in this cycle.")
    st.write("**Selector decisions**")
    selections = paper.get("selections", [])
    if selections:
        st.dataframe(pd.DataFrame(selections), width="stretch", hide_index=True)
    else:
        st.info("No new contract selection.")
    blockers = check.get("blockers", [])
    if blockers:
        st.error("Portfolio gate: " + " | ".join(str(item) for item in blockers))
    warnings = check.get("warnings", [])
    if warnings:
        st.warning("Portfolio warnings: " + " | ".join(str(item) for item in warnings))
    st.caption(
        "Paper-only long-premium crypto options. Deribit data is converted to a "
        "USD-marked approximation. No live broker is reachable."
    )
    heartbeat = read_heartbeat(ROOT / "artifacts/ai_options_30m/heartbeat.json")
    if heartbeat:
        st.json(heartbeat)


def _render_readiness() -> None:
    readiness = build_readiness(ROOT)
    st.subheader("Readiness")
    st.caption(
        "Read-only operational summary. Paper readiness and live readiness are "
        "separate. No view or button can place an order."
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Code checks", str(readiness["code_status"]))
    c2.metric("Campaign health", str(readiness["health_status"]))
    c3.metric("Live gate", str(readiness["live_gate"]))
    c4.metric("Options evidence", str(readiness["options_status"]))
    c5.metric(
        "Paper days",
        f"{readiness['paper_days']} / {readiness['target_paper_days']}",
    )
    if readiness["paper_ready"]:
        st.success("Paper infrastructure is healthy.")
    else:
        st.warning("Paper infrastructure is not fully healthy.")
    if readiness["live_ready"]:
        st.success("Live gate is GO.")
    else:
        st.error("Live gate is NO_GO. Live trading is blocked.")
    st.write("**Blockers**")
    for blocker in readiness["blockers"]:
        st.caption(f"• {blocker}")
    failed = readiness.get("live_gate_failed", [])
    if failed:
        st.write("**Failed live-gate checks**")
        st.dataframe(
            pd.DataFrame([{"check": item} for item in failed]),
            width="stretch",
            hide_index=True,
        )
    st.caption(
        "Run `uv run python scripts/self_eval.py` to refresh code, health, and "
        "live-gate checks."
    )


def _render_options_evidence() -> None:
    evidence = build_options_evidence(ROOT)
    paper = evidence.get("paper", {})
    squad = evidence.get("squad", {})
    replay = evidence.get("replay") or {}
    st.subheader("Options evidence")
    st.caption(
        "Read-only summary of the forward paper lane and the free real-chain "
        "replay. This page never places an order or changes policy."
    )
    status = str(evidence.get("status", "?"))
    if status != "target_days_reached":
        st.warning(
            f"Evidence status: {status}. "
            f"Forward paper days: {paper.get('paper_days', 0)} / "
            f"{evidence.get('target_paper_days', 56)}."
        )
    for warning in evidence.get("warnings", []):
        st.caption(f"• {warning}")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Paper days", f"{paper.get('paper_days', 0)}")
    c2.metric("Cycles", f"{paper.get('cycles', 0)}")
    c3.metric("Flat cycles", f"{paper.get('flat_cycles', 0)}")
    c4.metric("Fills", f"{paper.get('fills', 0)}")
    c5.metric("Equity", f"${float(paper.get('final_equity', 0)):,.2f}")
    c6.metric("Max drawdown", f"{float(paper.get('max_drawdown', 0)):.2%}")

    st.write("**Forward paper**")
    st.caption(
        f"Coverage: {paper.get('cycles', 0)} / {paper.get('expected_cycles', 0)} "
        f"expected 30m slots · risk-off cycles: {paper.get('risk_off_cycles', 0)} "
        f"· orders: {paper.get('orders', 0)}"
    )
    cycles = paper.get("cycle_rows", [])
    if cycles:
        frame = pd.DataFrame(cycles)
        if "directions" in frame.columns:
            frame["directions"] = frame["directions"].apply(
                lambda value: json.dumps(value, sort_keys=True)
            )
        st.dataframe(frame, width="stretch", hide_index=True)
    else:
        st.info("No forward paper cycles recorded.")

    st.write("**Squad controls**")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Squad runs", f"{squad.get('runs', 0)}")
    c2.metric("Risk vetoes", f"{squad.get('risk_veto_assets', 0)}")
    c3.metric("Execution blocks", f"{squad.get('execution_block_assets', 0)}")
    c4.metric("Chair flat runs", f"{squad.get('chair_flat_runs', 0)}")
    latest = squad.get("latest")
    if latest:
        st.json(latest)

    st.write("**Free real-chain replay**")
    if replay:
        r1, r2, r3, r4, r5 = st.columns(5)
        r1.metric("Date", str(replay.get("chain_date", "?")))
        r2.metric("Snapshots", f"{int(replay.get('snapshots') or 0)}")
        r3.metric("Fills", f"{int(replay.get('total_fills') or 0)}")
        r4.metric("Return", f"{float(replay.get('total_return') or 0):.2%}")
        r5.metric("Max drawdown", f"{float(replay.get('max_drawdown') or 0):.2%}")
        st.caption(
            "One free Tardis first-day sample. Tardis is a paid vendor; this "
            "is not a continuous backtest and not evidence of edge."
        )
    else:
        st.info("No free real-chain replay artifact found.")


def _render_intraday() -> None:
    config = _load_config(INTRADAY_CONFIG)
    perf_path = (
        ROOT / config.broker.performance_path
        if config
        else ROOT / "artifacts/intraday/performance.jsonl"
    )
    heartbeat_path = (
        ROOT / config.broker.heartbeat_path
        if config
        else ROOT / "artifacts/intraday/heartbeat.json"
    )
    state_path = (
        ROOT / config.broker.state_path
        if config
        else ROOT / "artifacts/intraday/paper_state.json"
    )
    perf = _perf_frame(perf_path)
    heartbeat = read_heartbeat(heartbeat_path)
    state = _load_json(state_path)

    st.subheader("Deterministic intraday paper lane")
    st.caption(
        "Runs on completed 1h bars. The hourly task refreshes recent Binance "
        "bars, rebalances trend/breakout/reversal/XSMOM through the meta "
        "allocator, and trades the separate paper account. Paper only."
    )
    if perf.empty and state is None:
        st.warning("No intraday performance or paper state yet.")
        st.code(
            "powershell -ExecutionPolicy Bypass -File scripts/run_intraday_cycle.ps1",
            language="powershell",
        )
        return

    latest = perf.iloc[-1] if not perf.empty else None
    cash = float(state.get("cash", 0.0)) if state else 0.0
    positions = state.get("positions", {}) if state else {}
    equity = float(latest["equity"]) if latest is not None else cash
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Intraday equity", f"${equity:,.2f}")
    c2.metric("Cash", f"${cash:,.2f}")
    c3.metric(
        "Gross exposure",
        f"{float(latest['gross_exposure']):.1%}" if latest is not None else "0.0%",
    )
    c4.metric("Positions", f"{len(positions)}")
    c5.metric(
        "Latest bar",
        str(latest["timestamp"]) if latest is not None else "n/a",
    )
    if latest is not None:
        st.caption(
            f"Last cycle: {latest['timestamp']} | orders "
            f"{int(latest.get('n_orders', 0))} | fills "
            f"{int(latest.get('n_fills', 0))}"
        )

    fig = go.Figure()
    _add_equity_trace(fig, perf_path, "Intraday meta paper", "#00897B")
    fig.update_layout(
        title="Hourly intraday paper equity",
        height=420,
        margin=dict(l=20, r=20, t=40, b=20),
        hovermode="x unified",
    )
    st.plotly_chart(fig, width="stretch")

    left, right = st.columns(2)
    with left:
        st.subheader("Positions")
        if positions:
            st.dataframe(
                pd.DataFrame(
                    [
                        {"asset": asset, "qty": float(pos.get("qty", 0))}
                        for asset, pos in positions.items()
                    ]
                ).sort_values("asset"),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("No positions.")
    with right:
        st.subheader("Heartbeat")
        if heartbeat:
            st.json(heartbeat)
        else:
            st.info("No heartbeat yet.")

    st.caption(
        "This lane is separate from the daily campaign and its 56-day evidence. "
        "Hourly signal horizons are unvalidated; transaction costs can dominate."
    )


def _render_both() -> None:
    sleeve_configs = {
        "Trend": "config/base.yaml",
        "XSMOM": "config/xsmom.yaml",
        "Breakout": "config/breakout.yaml",
        "Reversal": "config/reversal.yaml",
        "Meta": "config/meta.yaml",
    }
    configs = {name: _load_config(path) for name, path in sleeve_configs.items()}
    trend_config = configs["Trend"]
    xsmom_config = configs["XSMOM"]
    ai_config = _load_config(AI_CONFIG)
    ai_squad_config = _load_config(AI_SQUAD_CONFIG)
    reports = {
        name: _load_json(
            ROOT / "artifacts" / "reports" / f"evaluation_{name.lower()}.json"
        )
        for name in sleeve_configs
    }
    reports["AI agent"] = _load_json(
        ROOT / "artifacts" / "ai" / "reports" / "latest.json"
    )
    reports["AI squad"] = _load_json(
        ROOT / "artifacts" / "ai_squad" / "reports" / "latest.json"
    )

    st.subheader("Paper sleeves + separate AI lanes")
    cols = st.columns(3)
    for col, (name, report) in zip(cols, list(reports.items())[:3], strict=True):
        if report is None:
            col.metric(name, "no report")
            continue
        account = report.get("account", {})
        col.metric(name, f"${account.get('equity', 0):,.2f}")
        if name == "AI agent":
            decision = report.get("decision", {})
            col.caption(
                f"{report.get('provider', '?')} · {decision.get('regime', '?')} · "
                f"{float(decision.get('confidence', 0)):.0%} confidence"
            )
        else:
            tca = report.get("tca", {}).get("weighted_slip_bps", 0)
            col.caption(f"TCA {float(tca):.1f} bps")

    fig = go.Figure()
    if trend_config:
        _add_equity_trace(
            fig, ROOT / trend_config.broker.performance_path, "Deterministic trend", "#1565C0"
        )
    if xsmom_config:
        _add_equity_trace(
            fig, ROOT / xsmom_config.broker.performance_path, "Deterministic XSMOM", "#00897B"
        )
    extra_colors = {
        "Breakout": "#F57C00",
        "Reversal": "#C62828",
        "Meta": "#6A1B9A",
    }
    for name, color in extra_colors.items():
        config = configs.get(name)
        if config:
            _add_equity_trace(
                fig,
                ROOT / config.broker.performance_path,
                f"Deterministic {name}",
                color,
            )
    if ai_config:
        _add_equity_trace(
            fig, ROOT / ai_config.broker.performance_path, "AI agent paper", "#7B1FA2"
        )
    if ai_squad_config:
        _add_equity_trace(
            fig,
            ROOT / ai_squad_config.broker.performance_path,
            "AI squad paper",
            "#D81B60",
        )
    fig.update_layout(
        title="Separate paper accounts",
        height=430,
        margin=dict(l=20, r=20, t=40, b=20),
        hovermode="x unified",
    )
    st.plotly_chart(fig, width="stretch")

    rows: list[dict[str, Any]] = []
    for name, report in reports.items():
        if report is None:
            rows.append({"pipeline": name, "equity": None, "cash": None, "alerts": "no report"})
            continue
        account = report.get("account", {})
        alerts = report.get("alerts", [])
        rows.append(
            {
                "pipeline": name,
                "equity": float(account.get("equity", 0)),
                "cash": float(account.get("cash", 0)),
                "alerts": "; ".join(str(a) for a in alerts) if alerts else "none",
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    ai_report = reports["AI agent"]
    if ai_report is None:
        st.warning(
            "AI pipeline has not run yet. Use `scripts/run_ai_pipeline.ps1` "
            "after configuring Jev or a local LLM."
        )
    else:
        decision = ai_report.get("decision", {})
        policy = ai_report.get("policy", {})
        st.subheader("AI decision")
        if ai_report.get("status") == "error":
            st.error("Last AI decision failed; no orders were sent.")
        elif ai_report.get("fallback"):
            st.warning("Last AI decision used the labelled deterministic fallback.")
        st.write(
            f"Provider **{ai_report.get('provider', '?')}** / "
            f"`{ai_report.get('model', '?')}` · regime **{decision.get('regime', '?')}** · "
            f"confidence **{float(decision.get('confidence', 0)):.1%}** · "
            f"target gross **{float(policy.get('gross', 0)):.1%}**"
        )
        target = policy.get("target_weights", {})
        positive = {k: v for k, v in target.items() if abs(float(v)) > 1e-9}
        if positive:
            st.dataframe(
                pd.DataFrame(
                    [{"asset": k, "target_weight": float(v)} for k, v in positive.items()]
                ).sort_values("asset"),
                width="stretch",
                hide_index=True,
            )

    squad_report = reports["AI squad"]
    if squad_report is None:
        st.warning(
            "AI squad has not run yet. Use `scripts/run_ai_squad.ps1` after "
            "configuring Jev."
        )
    else:
        squad_account = squad_report.get("account", {})
        squad_decision = squad_report.get("decision", {})
        squad_policy = squad_report.get("policy", {})
        st.subheader("AI squad")
        if squad_report.get("status") == "error":
            st.error("Last AI squad decision failed; no orders were sent.")
        st.write(
            f"Provider **{squad_report.get('provider', '?')}** / "
            f"`{squad_report.get('model', '?')}` | regime "
            f"**{squad_decision.get('regime', '?')}** | confidence "
            f"**{float(squad_decision.get('confidence', 0)):.1%}** | "
            f"force rebalance **{bool(squad_decision.get('force_rebalance'))}**"
        )
        sq1, sq2, sq3 = st.columns(3)
        sq1.metric("Squad equity", f"${squad_account.get('equity', 0):,.2f}")
        sq2.metric("Cash", f"${squad_account.get('cash', 0):,.2f}")
        sq3.metric("Target gross", f"{float(squad_policy.get('gross', 0)):.1%}")

    gate = _load_json(ROOT / "artifacts" / "LIVE_GATE.json")
    if gate:
        if gate.get("status") == "GO":
            st.success("Live-capital gate: GO")
        else:
            st.error(
                f"Live-capital gate: {gate.get('status', 'NO_GO')} — "
                + ", ".join(str(item) for item in gate.get("failed", [])[:4])
            )

    st.subheader("Heartbeats")
    heartbeat_rows: list[dict[str, Any]] = []
    heartbeat_configs = [
        (f"Deterministic {name}", config) for name, config in configs.items()
    ] + [("AI agent", ai_config), ("AI squad", ai_squad_config)]
    for name, config in heartbeat_configs:
        if not config:
            continue
        payload = read_heartbeat(ROOT / config.broker.heartbeat_path)
        heartbeat_rows.append(
            {
                "pipeline": name,
                "status": (payload or {}).get("status", "no heartbeat"),
                "as_of": (payload or {}).get("as_of", ""),
                "equity": (payload or {}).get("equity"),
                "provider": (payload or {}).get("provider", ""),
            }
        )
    st.dataframe(pd.DataFrame(heartbeat_rows), width="stretch", hide_index=True)

    st.caption(
        "Each deterministic sleeve, the single-Jev AI lane, and the seven-agent "
        "AI squad have separate configs, broker state, journals, performance files, "
        "and kill switches. The meta sleeve is the consolidated portfolio. "
        "Dashboard is read-only."
    )


def _render_options_flow() -> None:
    if not OPTIONS_FLOW_PATH.exists():
        st.warning("Options flow simulation is missing.")
        return
    st.caption(
        "Simulation of the planned 30m crypto-options flow. This is a design "
        "visualization, not a live order path."
    )
    components.html(
        OPTIONS_FLOW_PATH.read_text(encoding="utf-8"),
        height=1050,
        scrolling=False,
    )


st.set_page_config(
    page_title="Trading Bot - Multi-Sleeve + AI Squad + Intraday",
    layout="wide",
)

# Optional access gate for hosted deployments. Local use is unchanged when the
# environment variable is absent. Set DASHBOARD_PASSWORD in the host's secret
# manager; never commit it.
_expected_password = os.getenv("DASHBOARD_PASSWORD")
if _expected_password and not st.session_state.get("dashboard_authenticated"):
    st.title("Trading Bot — restricted dashboard")
    st.caption("Read-only. Enter the dashboard password to continue.")
    _entered = st.text_input("Dashboard password", type="password")
    if st.button("Unlock"):
        if hmac.compare_digest(_entered, _expected_password):
            st.session_state.dashboard_authenticated = True
            st.rerun()
        st.error("Invalid password.")
    st.stop()

st.title("Trading Bot - Multi-Sleeve + AI Squad + Intraday")
st.caption(
    "Read-only. Separate daily paper sleeves, an hourly intraday paper lane, and "
    "two isolated AI lanes. No order controls. The AI paths have no broker "
    "credentials and cannot bypass the risk policy."
)

view = st.sidebar.radio(
    "Pipeline",
    [
        "Both",
        "Deterministic",
        "Intraday",
        "AI agent",
        "AI squad",
        "AI options 30m",
        "Readiness",
        "Options evidence",
        "Options flow",
        "3D Office",
    ],
    index=0,
)
refresh_label = st.sidebar.selectbox(
    "Auto-refresh",
    ["Off", "30 seconds", "60 seconds", "5 minutes"],
    index=0,
)
st.sidebar.caption("Auto-refresh only reloads read data; it never places orders.")


def _render_selected(selected: str) -> None:
    if selected == "Deterministic":
        _render_deterministic()
    elif selected == "AI agent":
        _render_ai()
    elif selected == "Intraday":
        _render_intraday()
    elif selected == "AI squad":
        _render_ai_squad()
    elif selected == "AI options 30m":
        _render_ai_options()
    elif selected == "Readiness":
        _render_readiness()
    elif selected == "Options evidence":
        _render_options_evidence()
    elif selected == "Options flow":
        _render_options_flow()
    elif selected == "3D Office":
        try:
            components.html(build_office_html(ROOT), height=900, scrolling=False)
        except Exception as exc:
            st.error(f"Could not build the 3D office: {type(exc).__name__}: {exc}")
            st.code("uv run python scripts/build_office3d.py")
    else:
        _render_both()


if refresh_label == "Off":
    _render_selected(view)
else:
    seconds = {"30 seconds": 30, "60 seconds": 60, "5 minutes": 300}[refresh_label]

    @st.fragment(run_every=f"{seconds}s")
    def _live_view() -> None:
        _render_selected(view)

    _live_view()
