"""Read-only Streamlit dashboard for the deterministic and AI pipelines.

Run:
    uv run streamlit run src/tradingbot/ops/dashboard.py

The dashboard never places orders or changes config. It only reads reports,
performance history, heartbeats, and paper state. The deterministic campaign
and the AI-agent campaign are separate accounts with separate artifacts.
"""

from __future__ import annotations

import hmac
import html
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import plotly.graph_objects as go  # type: ignore[import-untyped]
import plotly.io as pio  # type: ignore[import-untyped]
import streamlit as st
import streamlit.components.v1 as components

from tradingbot.config import AppConfig, load_config
from tradingbot.ops.evaluation import build_report, write_report
from tradingbot.ops.heartbeat import read_heartbeat
from tradingbot.ops.office3d import build_office_html
from tradingbot.ops.options_evidence import build_options_evidence
from tradingbot.ops.readiness import build_readiness

ROOT = Path(__file__).resolve().parents[3]
pio.templates.default = "plotly_dark"
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

_NAV_ITEMS = [
    "Overview",
    "Deterministic",
    "Intraday",
    "AI agent",
    "AI squad",
    "AI options 30m",
    "Swing options",
    "Readiness",
    "Options evidence",
    "Options flow",
    "3D Office",
]

_PAGE_META = {
    "Overview": (
        "Operations overview",
        "A single read-only view of paper capital, live gates, and every execution lane.",
    ),
    "Deterministic": (
        "Deterministic sleeves",
        "Trend, XSMOM, breakout, reversal, and meta-allocation paper books.",
    ),
    "Intraday": (
        "Intraday paper",
        "Hourly signal horizon, separate paper account, and its own risk state.",
    ),
    "AI agent": (
        "AI agent",
        "Single-provider decision lane with deterministic policy and risk vetoes.",
    ),
    "AI squad": (
        "AI squad",
        "Eight role-scoped agents, a shared memo blackboard, and binding risk guards.",
    ),
    "AI options 30m": (
        "AI options 30m",
        "30-minute directional long-premium options paper lane.",
    ),
    "Swing options": (
        "Swing options",
        "Daily BTC/ETH trend signals expressed with 21-45 DTE long premium.",
    ),
    "Readiness": (
        "Readiness & live gates",
        "Code, host, paper evidence, and live-capital gates in one place.",
    ),
    "Options evidence": (
        "Options evidence",
        "Forward paper evidence and free real-chain replay quality.",
    ),
    "Options flow": (
        "Options flow",
        "A visualization of the planned 30-minute options workflow.",
    ),
    "3D Office": (
        "3D office",
        "The agent office rendered as an interactive Three.js floor.",
    ),
}

_THEME_CSS = """
<style>
    :root {
        --tb-bg: #070b16;
        --tb-panel: rgba(15, 23, 42, 0.82);
        --tb-panel-solid: #0f172a;
        --tb-line: rgba(148, 163, 184, 0.16);
        --tb-text: #e2e8f0;
        --tb-muted: #94a3b8;
        --tb-cyan: #38bdf8;
        --tb-teal: #2dd4bf;
        --tb-green: #4ade80;
        --tb-amber: #fbbf24;
        --tb-red: #fb7185;
        --tb-purple: #c084fc;
    }
    html, body, [class*="css"] {
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .stApp {
        background:
            radial-gradient(1100px 600px at 12% -10%, rgba(56, 189, 248, 0.12), transparent 60%),
            radial-gradient(900px 550px at 95% 0%, rgba(192, 132, 252, 0.08), transparent 55%),
            var(--tb-bg);
    }
    [data-testid="stHeader"] {
        background: transparent;
    }
    [data-testid="stToolbar"], [data-testid="stDecoration"] {
        visibility: hidden;
        height: 0;
    }
    html, body, .stApp, [data-testid="stSidebar"] {
        overflow-x: hidden;
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #080e1a 0%, #0a1322 100%);
        border-right: 1px solid var(--tb-line);
    }
    [data-testid="stSidebar"] > div:first-child {
        padding-top: 1.1rem;
    }
    .block-container {
        max-width: 1480px;
        padding-top: 1.4rem;
        padding-bottom: 4rem;
    }
    #MainMenu, footer { visibility: hidden; }
    h1, h2, h3 { letter-spacing: -0.03em; }
    p, label, .stMarkdown { color: var(--tb-text); }
    .tb-brand {
        display: flex;
        align-items: center;
        gap: 0.7rem;
        padding: 0.1rem 0.2rem 1.25rem 0.2rem;
    }
    .tb-mark {
        width: 2.15rem;
        height: 2.15rem;
        border-radius: 0.7rem;
        display: grid;
        place-items: center;
        color: #06111f;
        font-weight: 900;
        letter-spacing: -0.08em;
        background: linear-gradient(135deg, var(--tb-cyan), var(--tb-teal));
        box-shadow: 0 8px 26px rgba(45, 212, 191, 0.22);
    }
    .tb-brand-name { font-weight: 800; font-size: 1.02rem; line-height: 1.1; }
    .tb-brand-sub { color: var(--tb-muted); font-size: 0.72rem; letter-spacing: 0.08em; text-transform: uppercase; }
    [data-testid="stSidebar"] label:has(input[type="radio"]) {
        padding: 0.18rem 0.35rem;
        border-radius: 0.5rem;
        transition: background 120ms ease, color 120ms ease;
    }
    [data-testid="stSidebar"] label:has(input[type="radio"]:hover) {
        background: rgba(148, 163, 184, 0.08);
    }
    [data-testid="stSidebar"] label:has(input[type="radio"]:checked) {
        background: rgba(56, 189, 248, 0.1);
        color: #bae6fd;
    }
    .tb-side-label {
        color: #64748b;
        font-size: 0.68rem;
        letter-spacing: 0.13em;
        text-transform: uppercase;
        font-weight: 700;
        padding: 0.8rem 0.2rem 0.35rem;
    }
    .tb-hero {
        position: relative;
        overflow: hidden;
        display: flex;
        align-items: flex-end;
        justify-content: space-between;
        gap: 1rem;
        padding: 1.55rem 1.7rem;
        margin-bottom: 1.1rem;
        border: 1px solid rgba(56, 189, 248, 0.18);
        border-radius: 1.15rem;
        background:
            linear-gradient(110deg, rgba(15, 23, 42, 0.96), rgba(8, 18, 33, 0.88)),
            radial-gradient(600px 300px at 80% 20%, rgba(56, 189, 248, 0.15), transparent 70%);
        box-shadow: 0 20px 70px rgba(0, 0, 0, 0.24);
    }
    .tb-hero::after {
        content: "";
        position: absolute;
        inset: 0;
        background: linear-gradient(90deg, transparent, rgba(56, 189, 248, 0.05), transparent);
        pointer-events: none;
    }
    .tb-eyebrow {
        color: var(--tb-teal);
        font-size: 0.68rem;
        text-transform: uppercase;
        letter-spacing: 0.16em;
        font-weight: 800;
        margin-bottom: 0.45rem;
    }
    .tb-title { font-size: clamp(1.55rem, 3vw, 2.5rem); font-weight: 850; line-height: 1.03; margin: 0; }
    .tb-subtitle { color: var(--tb-muted); max-width: 720px; margin: 0.55rem 0 0; font-size: 0.94rem; }
    .tb-hero-side {
        display: grid;
        grid-template-columns: repeat(2, max-content);
        justify-content: end;
        align-content: start;
        gap: 0.45rem;
        min-width: 230px;
    }
    @media (max-width: 650px) {
        .tb-hero-side { grid-template-columns: 1fr; justify-content: start; min-width: 0; }
    }
    .tb-chip {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        border: 1px solid var(--tb-line);
        background: rgba(15, 23, 42, 0.72);
        border-radius: 999px;
        padding: 0.35rem 0.65rem;
        font-size: 0.72rem;
        font-weight: 700;
        white-space: nowrap;
    }
    .tb-chip::before { content: ""; width: 0.4rem; height: 0.4rem; border-radius: 50%; background: currentColor; }
    .tb-good { color: var(--tb-green); border-color: rgba(74, 222, 128, 0.25); background: rgba(74, 222, 128, 0.08); }
    .tb-bad { color: var(--tb-red); border-color: rgba(251, 113, 133, 0.25); background: rgba(251, 113, 133, 0.08); }
    .tb-warn { color: var(--tb-amber); border-color: rgba(251, 191, 36, 0.25); background: rgba(251, 191, 36, 0.08); }
    .tb-neutral { color: var(--tb-muted); }
    .tb-info { color: var(--tb-cyan); border-color: rgba(56, 189, 248, 0.25); background: rgba(56, 189, 248, 0.08); }
    .tb-stat-grid {
        display: grid;
        grid-template-columns: repeat(6, minmax(0, 1fr));
        gap: 0.65rem;
        margin-bottom: 1.25rem;
    }
    .tb-stat {
        min-height: 4.1rem;
        border: 1px solid var(--tb-line);
        background: linear-gradient(180deg, rgba(15, 23, 42, 0.92), rgba(15, 23, 42, 0.68));
        border-radius: 0.85rem;
        padding: 0.8rem 0.85rem;
    }
    .tb-stat-label { color: #7c8ca3; font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.1em; font-weight: 750; }
    .tb-stat-value { color: var(--tb-text); font-size: 1.22rem; line-height: 1.25; font-weight: 800; margin-top: 0.25rem; }
    .tb-stat-detail { color: var(--tb-muted); font-size: 0.72rem; margin-top: 0.2rem; }
    .tb-section {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 1rem;
        margin: 1.35rem 0 0.7rem;
        padding-bottom: 0.45rem;
        border-bottom: 1px solid var(--tb-line);
    }
    .tb-section-title { font-size: 1.02rem; font-weight: 800; }
    .tb-section-sub { color: var(--tb-muted); font-size: 0.78rem; }
    .tb-page-head { margin: 0.1rem 0 1.15rem; }
    .tb-page-kicker { color: var(--tb-cyan); font-size: 0.66rem; letter-spacing: 0.14em; text-transform: uppercase; font-weight: 800; }
    .tb-page-title { font-size: 1.45rem; font-weight: 850; margin-top: 0.18rem; }
    .tb-page-sub { color: var(--tb-muted); font-size: 0.85rem; margin-top: 0.18rem; }
    .tb-lane-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.75rem; }
    .tb-lane {
        border: 1px solid var(--tb-line);
        border-radius: 0.9rem;
        padding: 0.95rem 1rem;
        background: linear-gradient(145deg, rgba(15, 23, 42, 0.92), rgba(9, 16, 29, 0.8));
        transition: border-color 120ms ease, transform 120ms ease;
    }
    .tb-lane:hover { border-color: rgba(56, 189, 248, 0.38); transform: translateY(-1px); }
    .tb-lane-top { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }
    .tb-lane-name { font-size: 0.88rem; font-weight: 800; }
    .tb-lane-value { font-size: 1.38rem; font-weight: 850; margin-top: 0.4rem; }
    .tb-lane-detail { color: var(--tb-muted); font-size: 0.73rem; margin-top: 0.25rem; }
    .tb-gate-list { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.5rem; }
    .tb-gate-list .tb-chip { font-weight: 600; }
    .tb-callout {
        border-left: 3px solid var(--tb-amber);
        padding: 0.5rem 0.75rem;
        background: rgba(251, 191, 36, 0.06);
        border-radius: 0 0.55rem 0.55rem 0;
        color: #d6c28c;
        font-size: 0.8rem;
        margin-top: 0.6rem;
    }
    [data-testid="stMetric"] {
        background: linear-gradient(180deg, rgba(15, 23, 42, 0.92), rgba(15, 23, 42, 0.68));
        border: 1px solid var(--tb-line);
        border-radius: 0.85rem;
        padding: 0.75rem 0.85rem;
    }
    [data-testid="stMetric"] {
        overflow: visible;
        padding: 0.65rem 0.6rem;
    }
    [data-testid="stMetricLabel"] {
        color: #8da0b8 !important;
        font-size: 0.63rem !important;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        white-space: normal !important;
        line-height: 1.2;
        min-height: 2.2em;
    }
    [data-testid="stMetricValue"] {
        color: var(--tb-text);
        font-weight: 800;
        font-size: clamp(0.95rem, 1.3vw, 1.3rem) !important;
        line-height: 1.15;
        white-space: normal !important;
        overflow: visible !important;
    }
    [data-testid="stMetric"] .stMarkdownEllipsis {
        white-space: normal !important;
        overflow: visible !important;
        text-overflow: clip !important;
    }
    [data-testid="stMetricValue"] p, [data-testid="stMetricLabel"] p {
        overflow-wrap: anywhere;
    }
    [data-testid="stDataFrame"] { border: 1px solid var(--tb-line); border-radius: 0.8rem; overflow: hidden; }
    .stButton > button {
        border-radius: 0.6rem;
        border: 1px solid rgba(56, 189, 248, 0.3);
        background: rgba(56, 189, 248, 0.1);
        color: #bae6fd;
        font-weight: 700;
    }
    .stButton > button:hover { border-color: var(--tb-cyan); background: rgba(56, 189, 248, 0.18); }
    div[data-testid="stAlert"] { border-radius: 0.8rem; border: 1px solid var(--tb-line); }
    @media (max-width: 1000px) {
        .tb-stat-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
        .tb-lane-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 650px) {
        .tb-hero { align-items: flex-start; flex-direction: column; padding: 1.2rem; }
        .tb-stat-grid, .tb-lane-grid { grid-template-columns: 1fr; }
    }
</style>
"""


def _tone(value: Any) -> str:
    text = str(value).upper()
    if text in {"GO", "READY", "PASS", "OK", "HEALTHY", "TRUE", "ACTIVE"}:
        return "good"
    if text in {"NO_GO", "DEGRADED", "FAIL", "ERROR", "FALSE", "OFFLINE"}:
        return "bad"
    if text in {"UNKNOWN", "MISSING", "STALE", "INSUFFICIENT"}:
        return "warn"
    return "neutral"


def _chip(label: str, value: Any, tone: str | None = None) -> str:
    css = tone or _tone(value)
    return (
        f'<span class="tb-chip tb-{css}">{html.escape(str(label))} '
        f"· {html.escape(str(value))}</span>"
    )


def _stat(label: str, value: Any, detail: str = "") -> str:
    return (
        '<div class="tb-stat">'
        f'<div class="tb-stat-label">{html.escape(str(label))}</div>'
        f'<div class="tb-stat-value">{html.escape(str(value))}</div>'
        f'<div class="tb-stat-detail">{html.escape(str(detail))}</div>'
        "</div>"
    )


def _section(title: str, subtitle: str = "") -> None:
    st.markdown(
        f'<div class="tb-section"><span class="tb-section-title">{html.escape(title)}</span>'
        f'<span class="tb-section-sub">{html.escape(subtitle)}</span></div>',
        unsafe_allow_html=True,
    )


def _page_intro(view: str) -> None:
    title, subtitle = _PAGE_META.get(view, (view, ""))
    st.markdown(
        '<div class="tb-page-head">'
        '<div class="tb-page-kicker">PAPER OPERATIONS</div>'
        f'<div class="tb-page-title">{html.escape(title)}</div>'
        f'<div class="tb-page-sub">{html.escape(subtitle)}</div>'
        "</div>",
        unsafe_allow_html=True,
    )


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
    if "timestamp" not in frame.columns and "as_of" in frame.columns:
        frame["timestamp"] = pd.to_datetime(
            frame["as_of"], utc=True, errors="coerce"
        )
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


def _lane_card(
    name: str,
    equity: Any,
    detail: str,
    *,
    value: str | None = None,
    tone: str = "neutral",
) -> str:
    shown = value if value is not None else (f"${float(equity):,.2f}" if equity is not None else "NO REPORT")
    return (
        '<div class="tb-lane">'
        '<div class="tb-lane-top">'
        f'<span class="tb-lane-name">{html.escape(name)}</span>'
        f'<span class="tb-chip tb-{tone}">{"ON" if tone == "good" else "PAPER"}</span>'
        "</div>"
        f'<div class="tb-lane-value">{html.escape(shown)}</div>'
        f'<div class="tb-lane-detail">{html.escape(detail)}</div>'
        "</div>"
    )


def _render_overview() -> None:
    readiness = _load_json(ROOT / "artifacts" / "READINESS.json") or {}
    trend = _load_json(ROOT / "artifacts" / "reports" / "evaluation_trend.json")
    xsmom = _load_json(ROOT / "artifacts" / "reports" / "evaluation_xsmom.json")
    ai_agent = _load_json(ROOT / "artifacts" / "ai" / "reports" / "latest.json")
    ai_squad = _load_json(ROOT / "artifacts" / "ai_squad" / "reports" / "latest.json")
    ai_options = _load_json(
        ROOT / "artifacts" / "ai_options_30m" / "reports" / "latest.json"
    )
    eth_lab = _load_json(
        ROOT / "artifacts" / "ai_options_eth" / "reports" / "latest.json"
    )
    btc_lab = _load_json(
        ROOT / "artifacts" / "ai_options_btc_lab" / "reports" / "latest.json"
    )
    swing = _load_json(ROOT / "artifacts" / "options_swing" / "reports" / "latest.json")

    def account_equity(
        report: dict[str, Any] | None, path: tuple[str, ...] = ("account",)
    ) -> float | None:
        if not report:
            return None
        node: Any = report
        for key in path:
            if not isinstance(node, dict):
                return None
            node = node.get(key, {})
        value = node.get("equity") if isinstance(node, dict) else None
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def last_as_of(report: dict[str, Any] | None, *, options: bool = False) -> str:
        if not report:
            return "no report"
        value = report.get("as_of") or (report.get("paper", {}) or {}).get("as_of", "?")
        return str(value)[:16].replace("T", " ")

    lanes = [
        ("Trend", account_equity(trend), "Daily deterministic sleeve", "good" if trend else "warn"),
        ("XSMOM", account_equity(xsmom), "Daily cross-sectional sleeve", "good" if xsmom else "warn"),
        ("AI agent", account_equity(ai_agent), "Single-provider paper lane", "info" if ai_agent else "warn"),
        ("AI squad", account_equity(ai_squad), "Eight-agent paper lane", "info" if ai_squad else "warn"),
        ("Options 30m", account_equity(ai_options, ("paper", "account_after")), "AI long-premium evidence lane", "warn"),
        ("Swing options", account_equity(swing, ("account_after",)), "Deterministic 21-45 DTE lane", "warn"),
        ("ETH lab", account_equity(eth_lab, ("paper", "account_after")), "Isolated $10k ETH-only paper", "info"),
        ("BTC lab", account_equity(btc_lab, ("paper", "account_after")), "Isolated $100k BTC plumbing", "info"),
    ]
    reporting = sum(1 for lane in lanes if lane[1] is not None)
    last_swing = last_as_of(swing)
    paper_days = readiness.get("paper_days", "?")
    target_days = readiness.get("target_paper_days", 56)
    live_gate = readiness.get("live_gate", "NO_GO")
    options_gate = readiness.get("options_live_gate", "NO_GO")
    host = readiness.get("host_status", "UNKNOWN")
    paper = readiness.get("paper_ready", False)

    _section("Command center", "Read-only monitor · paper accounts are separate")
    st.markdown(
        '<div class="tb-stat-grid">'
        + _stat("Paper infrastructure", "READY" if paper else "CHECK", str(readiness.get("health_status", "unknown")))
        + _stat("Reporting lanes", f"{reporting} / {len(lanes)}", "latest account snapshots")
        + _stat("Paper evidence", f"{paper_days} / {target_days}", "days toward live gate")
        + _stat("Host", str(host), "scheduler and network")
        + _stat("Spot live", str(live_gate), "capital gate")
        + _stat("Options live", str(options_gate), "options gate")
        + "</div>",
        unsafe_allow_html=True,
    )

    _section("Lanes", "Separate books, separate risk state")
    st.markdown(
        '<div class="tb-lane-grid">'
        + "".join(_lane_card(name, equity, detail, tone=tone) for name, equity, detail, tone in lanes)
        + "</div>",
        unsafe_allow_html=True,
    )

    _section("Equity curves", "Latest paper equity by lane")
    fig = go.Figure()
    configs = {
        "Trend": "config/base.yaml",
        "XSMOM": "config/xsmom.yaml",
        "AI agent": "config/ai_agent.yaml",
        "AI squad": "config/ai_squad.yaml",
        "Options 30m": "config/ai_options_30m.yaml",
        "Swing options": "config/options_swing.yaml",
        "ETH lab": "config/ai_options_eth_paper.yaml",
        "BTC lab": "config/ai_options_btc_lab.yaml",
    }
    colors = {
        "Trend": "#38bdf8",
        "XSMOM": "#2dd4bf",
        "AI agent": "#c084fc",
        "AI squad": "#f472b6",
        "Options 30m": "#fbbf24",
        "Swing options": "#4ade80",
        "ETH lab": "#f59e0b",
        "BTC lab": "#94a3b8",
    }
    for name, path in configs.items():
        config = _load_config(path)
        if config:
            _add_equity_trace(
                fig,
                ROOT / config.broker.performance_path,
                name,
                colors[name],
            )
    if fig.data:
        fig.update_layout(
            height=390,
            margin=dict(l=12, r=12, t=20, b=12),
            hovermode="x unified",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(15,23,42,0.25)",
            legend=dict(orientation="h", y=-0.2),
        )
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("No performance history yet.")

    _section("Live-capital gates", "A GO requires every check; no button here can enable it")
    gate_left, gate_right = st.columns(2)
    with gate_left:
        spot = _load_json(ROOT / "artifacts" / "LIVE_GATE.json")
        if spot:
            failed = spot.get("failed", [])
            st.markdown(
                f'<div class="tb-lane"><div class="tb-lane-top">'
                f'<span class="tb-lane-name">Spot gate</span>{_chip("STATUS", spot.get("status", "?"))}</div>'
                f'<div class="tb-lane-detail">Failed: {html.escape(", ".join(map(str, failed[:5])) or "none")}</div></div>',
                unsafe_allow_html=True,
            )
        else:
            st.info("Spot gate report missing.")
    with gate_right:
        options = _load_json(ROOT / "artifacts" / "OPTIONS_LIVE_GATE.json")
        if options:
            failed = options.get("failed", [])
            st.markdown(
                f'<div class="tb-lane"><div class="tb-lane-top">'
                f'<span class="tb-lane-name">Options gate</span>{_chip("STATUS", options.get("status", "?"))}</div>'
                f'<div class="tb-lane-detail">Failed: {html.escape(", ".join(map(str, failed[:5])) or "none")}</div></div>',
                unsafe_allow_html=True,
            )
        else:
            st.info("Options gate report missing.")

    alerts: list[str] = []
    for label, report in (
        ("AI agent", ai_agent),
        ("AI squad", ai_squad),
        ("Options 30m", ai_options),
        ("Swing options", swing),
        ("ETH lab", eth_lab),
        ("BTC lab", btc_lab),
    ):
        if not report:
            continue
        for alert in report.get("alerts", [])[:2]:
            alerts.append(f"{label}: {alert}")
    if readiness.get("host_blockers"):
        alerts.extend(str(item) for item in readiness.get("host_blockers", [])[:2])
    if alerts:
        st.markdown(
            '<div class="tb-callout">Needs attention: '
            + html.escape(" | ".join(alerts[:4]))
            + "</div>",
            unsafe_allow_html=True,
        )
    st.caption(f"Swing options last report: {last_swing} · all values are paper-only.")


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
    c5.metric("Drift", f"{(metrics.get('drift') or 0):.1%}")

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
        st.warning("No eight-agent AI squad report yet.")
        st.code(
            "powershell -ExecutionPolicy Bypass -File scripts/run_ai_squad.ps1",
            language="powershell",
        )
        st.caption(
            "The squad uses eight role-scoped Jev calls. The deterministic policy and "
            "risk checks still own sizing and execution."
        )
        return

    account = report.get("account", {})
    decision = report.get("decision", {})
    policy = report.get("policy", {})
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Equity", f"${account.get('equity', 0):,.2f}")
    c2.metric("Cash", f"${account.get('cash', 0):,.2f}")
    c3.metric("Confidence", f"{float(decision.get('confidence', 0)):.1%}")
    c4.metric("Regime", str(decision.get("regime", "?")))
    c5.metric("Age", f"{report.get('data_age_days', '?')}d")
    c6.metric("Rebalance", "yes" if decision.get("force_rebalance") else "no")

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


def _options_task_status(name: str) -> dict[str, Any] | None:
    host = _load_json(ROOT / "artifacts" / "HOST_READINESS.json")
    if not host:
        return None
    return next(
        (item for item in host.get("tasks", []) if item.get("name") == name),
        None,
    )


def _render_ai_options_report(
    report_path: Path,
    config_path: str,
    artifacts_dir: Path,
    *,
    task_name: str,
    description: str,
) -> None:
    st.caption(description)
    task = _options_task_status(task_name)
    if task:
        st.caption(
            f"Scheduled task: `{task.get('state', '?')}` · "
            f"last result `{task.get('last_result', '?')}` · "
            f"next `{task.get('next_run', '?')}`"
        )
    report = _load_json(report_path)
    if report is None:
        st.warning("No report for this options account yet.")
        st.code(
            f"uv run python -m tradingbot --config {config_path} ai-options-run",
            language="powershell",
        )
        return
    paper = report.get("paper", {})
    account = paper.get("account_after", {})
    check = paper.get("account_check", {})
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Equity", f"${float(account.get('equity', 0)):,.2f}")
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
    diagnostics = report.get("diagnostics") or {}
    reasons = diagnostics.get("why") or []
    if reasons:
        st.warning("No-fill diagnostics: " + " | ".join(str(item) for item in reasons))
    checks = diagnostics.get("hypothetical_checks") or []
    if checks:
        with st.expander("Hypothetical contract checks"):
            st.dataframe(pd.DataFrame(checks), width="stretch", hide_index=True)

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
    heartbeat = read_heartbeat(artifacts_dir / "heartbeat.json")
    if heartbeat:
        st.json(heartbeat)


def _render_ai_options() -> None:
    st.write(
        "The canonical evidence account trades BTC and ETH together. The two "
        "labs are isolated paper accounts used for scope testing; they never "
        "change the 56-day evidence account."
    )
    active_tab, eth_tab, btc_tab = st.tabs(
        [
            "Evidence account · BTC + ETH",
            "ETH-only lab · $10k",
            "BTC contract lab · $100k",
        ]
    )
    with active_tab:
        _render_ai_options_report(
            ROOT / "artifacts" / "ai_options_30m" / "reports" / "latest.json",
            "config/ai_options_30m.yaml",
            ROOT / "artifacts" / "ai_options_30m",
            task_name="TradingBotAIOptions30m",
            description=(
                "Canonical 56-day paper evidence account. Both underlyings, "
                "unchanged risk limits."
            ),
        )
    with eth_tab:
        _render_ai_options_report(
            ROOT / "artifacts" / "ai_options_eth" / "reports" / "latest.json",
            "config/ai_options_eth_paper.yaml",
            ROOT / "artifacts" / "ai_options_eth",
            task_name="TradingBotAIOptionsEth",
            description=(
                "Isolated $10k ETH-only paper lane. The AI must still approve "
                "the direction; no forced trades. Not part of the evidence count."
            ),
        )
    with btc_tab:
        _render_ai_options_report(
            ROOT / "artifacts" / "ai_options_btc_lab" / "reports" / "latest.json",
            "config/ai_options_btc_lab.yaml",
            ROOT / "artifacts" / "ai_options_btc_lab",
            task_name="TradingBotAIOptionsBtcLab",
            description=(
                "Isolated $100k BTC-only paper lab for contract affordability "
                "and execution plumbing. Not real capital and not evidence."
            ),
        )


def _render_options_swing() -> None:
    config = _load_config("config/options_swing.yaml")
    report = _load_json(ROOT / "artifacts" / "options_swing" / "reports" / "latest.json")
    task = None
    host = _load_json(ROOT / "artifacts" / "HOST_READINESS.json")
    if host:
        task = next(
            (
                item
                for item in host.get("tasks", [])
                if item.get("name") == "TradingBotOptionsSwing"
            ),
            None,
        )

    st.caption(
        "Read-only BTC/ETH long-premium swing paper lane. Daily trend/momentum "
        "signal, 21-45 DTE contracts, explicit profit/stop/DTE exits."
    )
    if task:
        st.caption(
            f"Scheduled task: `{task.get('state', '?')}` · "
            f"last result `{task.get('last_result', '?')}` · "
            f"next `{task.get('next_run', '?')}`"
        )
    if report is None:
        st.warning("No swing-options report yet.")
        st.code(
            "uv run python -m tradingbot --config config/options_swing.yaml options-swing-run",
            language="powershell",
        )
        return

    account = report.get("account_after") or {}
    signals = report.get("signals") or {}
    exits = report.get("exits") or []
    fills = report.get("fills") or []
    alerts = report.get("alerts") or []
    status = str(report.get("status", "?"))
    if status == "ok":
        st.success(f"Cycle status: {status}")
    else:
        st.warning(f"Cycle status: {status}")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Equity", f"${float(account.get('equity', 0)):,.2f}")
    c2.metric("Cash", f"${float(account.get('cash', 0)):,.2f}")
    c3.metric("Legs", f"{int(account.get('legs', 0))}")
    c4.metric(
        "Signals",
        " · ".join(
            f"{key}={value.get('direction')}" for key, value in signals.items()
        ),
    )
    c5.metric("As of", str(report.get("as_of", "?"))[:10])

    st.caption(
        f"Report generated `{report.get('as_of', '?')}` · "
        f"paper only · no live order path"
    )
    if alerts:
        st.error("Alerts: " + " | ".join(str(item) for item in alerts))

    st.write("**Signals**")
    if signals:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "underlying": key,
                        "direction": value.get("direction"),
                        "close": value.get("close"),
                        "SMA50": value.get("sma50"),
                        "SMA200": value.get("sma200"),
                        "20d momentum": value.get("momentum20"),
                        "reason": value.get("reason"),
                    }
                    for key, value in signals.items()
                ]
            ),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No signals in this cycle.")

    left, right = st.columns(2)
    with left:
        st.write("**Exits**")
        if exits:
            st.dataframe(pd.DataFrame(exits), width="stretch", hide_index=True)
        else:
            st.info("No exits in this cycle.")
    with right:
        st.write("**Fills**")
        if fills:
            st.dataframe(pd.DataFrame(fills), width="stretch", hide_index=True)
        else:
            st.info("No fills in this cycle.")

    if config:
        perf_path = ROOT / config.broker.performance_path
        if perf_path.exists():
            try:
                perf = pd.read_json(perf_path, lines=True)
            except ValueError:
                perf = pd.DataFrame()
            if not perf.empty:
                perf["as_of"] = pd.to_datetime(perf["as_of"], utc=True, errors="coerce")
                perf = perf.sort_values("as_of")
                fig = go.Figure(
                    go.Scatter(
                        x=perf["as_of"],
                        y=perf["equity"],
                        mode="lines+markers",
                        name="swing paper",
                        line=dict(color="#2dd4bf", width=2),
                    )
                )
                fig.update_layout(
                    title="Swing options equity",
                    height=320,
                    margin=dict(l=20, r=20, t=40, b=20),
                    hovermode="x unified",
                )
                st.plotly_chart(fig, width="stretch")

        state = _load_json(ROOT / config.broker.state_path)
        st.write("**Current paper positions**")
        positions = (state or {}).get("positions", {})
        if positions:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "instrument": key,
                            "qty": value.get("qty"),
                            "entry premium": value.get("entry_premium"),
                            "opened on": value.get("opened_on", "—"),
                            "expiry": value.get("expiry"),
                        }
                        for key, value in positions.items()
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("No open paper positions.")

    st.caption(
        "This view reads only. It cannot place an order, change policy, or "
        "enable live trading."
    )


def _render_readiness() -> None:
    readiness = build_readiness(ROOT)
    st.caption(
        "Read-only operational summary. Paper readiness and live readiness are "
        "separate. No view or button can place an order."
    )
    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    c1.metric("Code", str(readiness["code_status"]))
    c2.metric("Health", str(readiness["health_status"]))
    c3.metric("Host", str(readiness["host_status"]))
    c4.metric("Spot", str(readiness["live_gate"]))
    c5.metric("Options", str(readiness["options_live_gate"]))
    c6.metric("Evidence", str(readiness["options_status"]))
    c7.metric(
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
        st.write("**Failed spot live-gate checks**")
        st.dataframe(
            pd.DataFrame([{"check": item} for item in failed]),
            width="stretch",
            hide_index=True,
        )
    options_failed = readiness.get("options_live_gate_failed", [])
    if options_failed:
        st.write("**Failed options live-gate checks**")
        st.dataframe(
            pd.DataFrame([{"check": item} for item in options_failed]),
            width="stretch",
            hide_index=True,
        )
    host_blockers = readiness.get("host_blockers", [])
    if host_blockers:
        st.write("**Host recommendations**")
        for item in host_blockers:
            st.caption(f"• {item}")
    st.caption(
        "Run `uv run python scripts/self_eval.py` to refresh code, health, and "
        "live-gate checks."
    )


def _render_options_evidence() -> None:
    evidence = build_options_evidence(ROOT)
    paper = evidence.get("paper", {})
    squad = evidence.get("squad", {})
    replay = evidence.get("replay") or {}
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
    c1.metric("Days", f"{paper.get('paper_days', 0)}")
    c2.metric("Cycles", f"{paper.get('cycles', 0)}")
    c3.metric("Flat", f"{paper.get('flat_cycles', 0)}")
    c4.metric("Fills", f"{paper.get('fills', 0)}")
    c5.metric("Equity", f"${float(paper.get('final_equity', 0)):,.2f}")
    c6.metric("Drawdown", f"{float(paper.get('max_drawdown', 0)):.2%}")

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
    c1.metric("Equity", f"${equity:,.2f}")
    c2.metric("Cash", f"${cash:,.2f}")
    c3.metric(
        "Gross",
        f"{float(latest['gross_exposure']):.1%}" if latest is not None else "0.0%",
    )
    c4.metric("Positions", f"{len(positions)}")
    c5.metric(
        "As of",
        str(latest["timestamp"])[:16].replace("T", " ") if latest is not None else "n/a",
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
        title="Intraday equity",
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


def _readiness_snapshot() -> dict[str, Any]:
    return _load_json(ROOT / "artifacts" / "READINESS.json") or {}


def _render_shell_header(readiness: dict[str, Any]) -> None:
    paper = "READY" if readiness.get("paper_ready") else "CHECK"
    host = readiness.get("host_status", "UNKNOWN")
    spot = readiness.get("live_gate", "NO_GO")
    options = readiness.get("options_live_gate", "NO_GO")
    paper_days = readiness.get("paper_days", "?")
    target_days = readiness.get("target_paper_days", 56)
    st.markdown(
        '<div class="tb-hero">'
        "<div>"
        '<div class="tb-eyebrow">NOVA · PAPER OPERATIONS</div>'
        '<div class="tb-title">Trading Operations</div>'
        '<div class="tb-subtitle">'
        "Deterministic sleeves, AI research lanes, crypto options, and hard risk "
        "gates — one read-only command surface."
        "</div></div>"
        '<div class="tb-hero-side">'
        + _chip("PAPER", paper)
        + _chip("HOST", host)
        + _chip("LIVE", spot)
        + _chip("OPTIONS", options)
        + _chip("EVIDENCE", f"{paper_days}/{target_days}")
        + "</div></div>",
        unsafe_allow_html=True,
    )


def _render_sidebar(readiness: dict[str, Any]) -> tuple[str, str]:
    with st.sidebar:
        st.markdown(
            '<div class="tb-brand">'
            '<div class="tb-mark">N</div>'
            '<div><div class="tb-brand-name">NOVA</div>'
            '<div class="tb-brand-sub">Trading operations</div></div></div>',
            unsafe_allow_html=True,
        )
        st.markdown('<div class="tb-side-label">Environment</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="tb-gate-list">'
            + _chip("Paper", "READY" if readiness.get("paper_ready") else "CHECK")
            + _chip("Live", readiness.get("live_gate", "NO_GO"))
            + _chip("Host", readiness.get("host_status", "UNKNOWN"))
            + "</div>",
            unsafe_allow_html=True,
        )
        st.markdown('<div class="tb-side-label">Workspace</div>', unsafe_allow_html=True)
        view = st.radio(
            "Workspace",
            _NAV_ITEMS,
            index=0,
            label_visibility="collapsed",
        )
        st.markdown('<div class="tb-side-label">Session</div>', unsafe_allow_html=True)
        refresh_label = st.selectbox(
            "Auto-refresh",
            ["Off", "30 seconds", "60 seconds", "5 minutes"],
            index=0,
        )
        st.caption("Read-only reload. No order controls.")
        st.markdown('<div class="tb-side-label">Boundary</div>', unsafe_allow_html=True)
        st.caption(
            "Paper only. Live capital remains gated by evidence, host readiness, "
            "and separate credentials."
        )
    return view, refresh_label


st.set_page_config(
    page_title="NOVA · Trading Operations",
    layout="wide",
)
st.markdown(_THEME_CSS, unsafe_allow_html=True)

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

readiness = _readiness_snapshot()
_render_shell_header(readiness)
view, refresh_label = _render_sidebar(readiness)
if view != "Overview":
    _page_intro(view)


def _render_selected(selected: str) -> None:
    if selected == "Overview":
        _render_overview()
    elif selected == "Deterministic":
        _render_deterministic()
    elif selected == "AI agent":
        _render_ai()
    elif selected == "Intraday":
        _render_intraday()
    elif selected == "AI squad":
        _render_ai_squad()
    elif selected == "AI options 30m":
        _render_ai_options()
    elif selected == "Swing options":
        _render_options_swing()
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
        _render_overview()


if refresh_label == "Off":
    _render_selected(view)
else:
    seconds = {"30 seconds": 30, "60 seconds": 60, "5 minutes": 300}[refresh_label]

    @st.fragment(run_every=f"{seconds}s")
    def _live_view() -> None:
        _render_selected(view)

    _live_view()
