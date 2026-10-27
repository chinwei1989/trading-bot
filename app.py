"""Vercel-compatible read-only status dashboard.

The full Streamlit dashboard lives in ``streamlit_app.py``. Vercel's Python
function bundle cannot hold Streamlit plus its dependency tree under the 500 MB
limit, so this entrypoint is deliberately small: stdlib + FastAPI reading a
generated ``deploy/status.json`` snapshot.

Update the snapshot with ``scripts/export_deploy_status.py`` and redeploy.
The snapshot is read-only and contains no credentials.
"""

from __future__ import annotations

import base64
import hmac
import html
import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

ROOT = Path(__file__).resolve().parent
STATUS_PATH = ROOT / "deploy" / "status.json"

app = FastAPI(title="NOVA Trading Operations", docs_url=None, redoc_url=None)

LANES = {
    "trend": "Trend",
    "xsmom": "XSMOM",
    "breakout": "Breakout",
    "reversal": "Reversal",
    "meta": "Meta allocator",
    "ai": "AI agent",
    "intraday": "Intraday",
    "ai_options_30m": "Options 30m",
    "swing": "Swing options",
    "ai_options_eth": "ETH options lab",
    "ai_options_btc_lab": "BTC options lab",
}

CSS = """
<style>
:root {
  color-scheme: dark;
  --bg: #070b16;
  --panel: #0f172a;
  --panel-2: #0b1322;
  --line: rgba(148, 163, 184, .16);
  --text: #e2e8f0;
  --muted: #94a3b8;
  --cyan: #38bdf8;
  --teal: #2dd4bf;
  --green: #4ade80;
  --amber: #fbbf24;
  --red: #fb7185;
  --purple: #c084fc;
}
* { box-sizing: border-box; }
html { background: var(--bg); }
body {
  margin: 0;
  min-height: 100vh;
  color: var(--text);
  font: 14px/1.5 Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  background:
    radial-gradient(1000px 600px at 10% -10%, rgba(56,189,248,.14), transparent 60%),
    radial-gradient(900px 500px at 95% 0%, rgba(192,132,252,.10), transparent 55%),
    var(--bg);
}
main { max-width: 1180px; margin: 0 auto; padding: 30px 22px 50px; }
a { color: var(--cyan); }
.hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 24px;
  padding: 28px;
  border: 1px solid rgba(56,189,248,.18);
  border-radius: 20px;
  background: linear-gradient(110deg, rgba(15,23,42,.97), rgba(8,18,33,.9));
  box-shadow: 0 22px 70px rgba(0,0,0,.28);
}
.eyebrow { color: var(--teal); font-size: 10px; font-weight: 800; letter-spacing: .18em; text-transform: uppercase; }
h1 { margin: 8px 0 8px; font-size: clamp(30px, 5vw, 52px); letter-spacing: -.045em; line-height: .98; }
.sub { max-width: 660px; margin: 0; color: var(--muted); font-size: 14px; }
.hero-right { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; max-width: 430px; }
.chip {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 6px 10px; border: 1px solid var(--line); border-radius: 999px;
  background: rgba(15,23,42,.72); color: var(--muted);
  font-size: 10px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; white-space: nowrap;
}
.chip::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.good { color: var(--green); border-color: rgba(74,222,128,.26); background: rgba(74,222,128,.08); }
.bad { color: var(--red); border-color: rgba(251,113,133,.26); background: rgba(251,113,133,.08); }
.warn { color: var(--amber); border-color: rgba(251,191,36,.26); background: rgba(251,191,36,.08); }
.info { color: var(--cyan); border-color: rgba(56,189,248,.26); background: rgba(56,189,248,.08); }
.section { display: flex; align-items: baseline; justify-content: space-between; gap: 18px; margin: 30px 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--line); }
.section h2 { margin: 0; font-size: 17px; letter-spacing: -.02em; }
.section .sub { font-size: 12px; }
.stats { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; }
.stat, .lane { border: 1px solid var(--line); border-radius: 14px; background: linear-gradient(180deg, rgba(15,23,42,.94), rgba(15,23,42,.70)); }
.stat { padding: 14px; min-height: 84px; }
.stat-label, .lane-label { color: #7c8ca3; font-size: 9px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
.stat-value { margin-top: 7px; font-size: 20px; font-weight: 850; line-height: 1.1; }
.stat-note, .lane-note { color: var(--muted); font-size: 11px; margin-top: 5px; }
.lanes { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.lane { padding: 15px; }
.lane-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.lane-name { font-size: 13px; font-weight: 800; }
.lane-value { margin-top: 12px; font-size: 21px; font-weight: 850; letter-spacing: -.02em; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.panel { padding: 16px; border: 1px solid var(--line); border-radius: 14px; background: rgba(15,23,42,.72); }
.panel h3 { margin: 0 0 10px; font-size: 14px; }
.panel p { margin: 0 0 8px; color: var(--muted); font-size: 12px; }
.panel strong { color: var(--text); }
.failures { margin: 9px 0 0; padding: 0; list-style: none; display: flex; flex-wrap: wrap; gap: 5px; }
.failures li { color: var(--muted); font-size: 10px; border: 1px solid var(--line); border-radius: 999px; padding: 3px 7px; }
.warning { border-left: 3px solid var(--amber); background: rgba(251,191,36,.06); color: #d6c28c; padding: 9px 12px; border-radius: 0 10px 10px 0; font-size: 12px; margin-top: 12px; }
.footer { margin-top: 28px; padding-top: 16px; border-top: 1px solid var(--line); color: #64748b; font-size: 11px; }
.footer code { color: #94a3b8; }
@media (max-width: 980px) { .stats { grid-template-columns: repeat(3, minmax(0,1fr)); } .lanes { grid-template-columns: repeat(2, minmax(0,1fr)); } .hero { flex-direction: column; align-items: flex-start; } .hero-right { justify-content: flex-start; } }
@media (max-width: 650px) { .stats, .lanes, .two { grid-template-columns: 1fr; } main { padding: 18px 14px 36px; } .hero { padding: 20px; } }
</style>
"""


def _status() -> dict[str, Any]:
    try:
        payload = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"generated_at": None, "campaigns": {}, "gate": None, "health": None}
    return payload if isinstance(payload, dict) else {}


def _authorized(request: Request) -> bool:
    password = os.getenv("DASHBOARD_PASSWORD")
    if not password:
        return True
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
        _, supplied = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        return False
    return hmac.compare_digest(supplied, password)


def _guard(request: Request) -> None:
    if not _authorized(request):
        raise HTTPException(
            status_code=401,
            detail="authentication required",
            headers={"WWW-Authenticate": "Basic realm=dashboard"},
        )


def _money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "-"


def _short_time(value: Any) -> str:
    text = str(value or "?")
    return text[:16].replace("T", " ") if "T" in text else text


def _tone(value: Any) -> str:
    text = str(value).upper()
    if text in {"GO", "READY", "PASS", "OK", "HEALTHY", "TRUE", "ACTIVE"}:
        return "good"
    if text in {"NO_GO", "DEGRADED", "FAIL", "ERROR", "FALSE", "OFFLINE"}:
        return "bad"
    if text in {"UNKNOWN", "MISSING", "STALE", "INSUFFICIENT", "CHECK"}:
        return "warn"
    return "info"


def _chip(label: str, value: Any) -> str:
    return (
        f'<span class="chip {_tone(value)}">{html.escape(str(label))} '
        f"&middot; {html.escape(str(value))}</span>"
    )


def _stat(label: str, value: Any, note: str) -> str:
    return (
        '<div class="stat">'
        f'<div class="stat-label">{html.escape(label)}</div>'
        f'<div class="stat-value">{html.escape(str(value))}</div>'
        f'<div class="stat-note">{html.escape(note)}</div>'
        "</div>"
    )


def _lane(name: str, row: dict[str, Any]) -> str:
    equity = row.get("equity")
    days = int(row.get("days") or 0)
    mode = str(row.get("mode") or "paper")
    tone = "good" if equity is not None else "warn"
    value = _money(equity) if equity is not None else "NO REPORT"
    return (
        '<div class="lane">'
        '<div class="lane-top">'
        f'<span class="lane-name">{html.escape(name)}</span>'
        f'<span class="chip {tone}">{html.escape(mode.upper())}</span>'
        "</div>"
        f'<div class="lane-value">{value}</div>'
        f'<div class="lane-note">{days} recorded day{"s" if days != 1 else ""}</div>'
        "</div>"
    )


def _task(host: dict[str, Any], name: str) -> dict[str, Any]:
    for task in host.get("tasks", []):
        if task.get("name") == name:
            return task
    return {}


def _page(data: dict[str, Any]) -> str:
    gate = data.get("gate") or {}
    health = data.get("health") or {}
    readiness = data.get("readiness") or {}
    host = data.get("host_readiness") or {}
    campaigns = data.get("campaigns") or {}
    squad = data.get("ai_squad") or {}
    squad_scorecard = data.get("ai_squad_scorecard") or {}
    options = data.get("options_evidence") or {}
    options_gate = data.get("options_live_gate") or {}
    options_paper = options.get("paper") or {}
    replay = options.get("replay") or {}
    swing = data.get("options_swing_report") or {}
    canary = data.get("testnet_canary") or {}
    swing_task = _task(host, "TradingBotOptionsSwing")
    canary_task = _task(host, "TradingBotDeribitCanary")

    gate_status = str(gate.get("status", "NO_GO"))
    options_gate_status = str(options_gate.get("status", "NO_GO"))
    paper_ready = "READY" if readiness.get("paper_ready") else "CHECK"
    paper_days = int(readiness.get("paper_days") or 0)
    target_days = int(readiness.get("target_paper_days") or 56)
    host_status = str(host.get("status") or readiness.get("host_status") or "UNKNOWN")
    failed = ", ".join(str(item) for item in gate.get("failed", [])) or "none"
    options_failed = ", ".join(str(item) for item in options_gate.get("failed", [])) or "none"
    reporting = sum(
        1 for key in LANES if (campaigns.get(key) or {}).get("equity") is not None
    )

    lane_html = "".join(
        _lane(label, campaigns.get(key) or {})
        for key, label in LANES.items()
    )
    stats_html = "".join(
        [
            _stat("Paper infrastructure", paper_ready, str(health.get("status", "unknown"))),
            _stat("Reporting lanes", f"{reporting} / {len(LANES)}", "latest snapshots"),
            _stat("Paper evidence", f"{paper_days} / {target_days}", "days toward live gate"),
            _stat("Host", host_status, "scheduler and network"),
            _stat("Spot live", gate_status, "capital gate"),
            _stat("Options live", options_gate_status, "options gate"),
        ]
    )

    swing_signals = swing.get("signals") or {}
    swing_account = swing.get("account_after") or {}
    swing_signal_text = " &middot; ".join(
        f"{html.escape(str(key))}: {html.escape(str(value.get('direction', '?')))}"
        for key, value in swing_signals.items()
    ) or "no signals"
    swing_exits = len(swing.get("exits") or [])
    swing_fills = len(swing.get("fills") or [])
    swing_as_of = html.escape(str(swing.get("as_of") or "no report")[:16].replace("T", " "))
    swing_task_text = (
        f"task {html.escape(str(swing_task.get('state', '?')))} &middot; "
        f"last result {html.escape(str(swing_task.get('last_result', '?')))} &middot; "
        f"next {html.escape(_short_time(swing_task.get('next_run')))}"
        if swing_task
        else "task status unavailable"
    )

    canary_ok = "PASS" if canary.get("ok") else "FAIL"
    canary_final = canary.get("final_reconcile") or {}
    if not isinstance(canary_final, dict):
        canary_final = {}
    canary_open = len(canary_final.get("open_orders") or [])
    canary_positions = len(canary_final.get("local_positions") or {})
    canary_text = (
        f"mode {html.escape(str(canary.get('mode', '?')))} &middot; "
        f"last result {html.escape(str(canary_task.get('last_result', '?')))}"
        if canary else "no canary report"
    )

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>NOVA - Trading Operations</title>
{CSS}
</head>
<body>
<main>
<section class="hero">
  <div>
    <div class="eyebrow">NOVA &middot; PAPER OPERATIONS</div>
    <h1>Trading<br>Operations</h1>
    <p class="sub">Deterministic sleeves, AI research lanes, crypto options, and hard risk gates. Read-only command surface.</p>
  </div>
  <div class="hero-right">
    {_chip("Paper", paper_ready)}
    {_chip("Host", host_status)}
    {_chip("Spot", gate_status)}
    {_chip("Options", options_gate_status)}
    {_chip("Evidence", f"{paper_days}/{target_days}")}
  </div>
</section>

<div class="section"><h2>Command center</h2><span class="sub">Snapshot generated {html.escape(_short_time(data.get("generated_at")))}</span></div>
<div class="stats">{stats_html}</div>

<div class="section"><h2>Lanes</h2><span class="sub">Separate paper accounts</span></div>
<div class="lanes">{lane_html}</div>

<div class="section"><h2>Live-capital gates</h2><span class="sub">A GO requires every check</span></div>
<div class="two">
  <div class="panel">
    <h3>Spot gate {_chip("status", gate_status)}</h3>
    <p>Failed checks:</p>
    <ul class="failures">{"".join(f"<li>{html.escape(str(item))}</li>" for item in gate.get("failed", [])) or "<li>none</li>"}</ul>
  </div>
  <div class="panel">
    <h3>Options gate {_chip("status", options_gate_status)}</h3>
    <p>Failed checks:</p>
    <ul class="failures">{"".join(f"<li>{html.escape(str(item))}</li>" for item in options_gate.get("failed", [])) or "<li>none</li>"}</ul>
  </div>
</div>

<div class="section"><h2>AI and options</h2><span class="sub">Paper execution only</span></div>
<div class="two">
  <div class="panel">
    <h3>AI squad</h3>
    <p><strong>{_money(squad.get("equity"))}</strong> &middot; {int(squad.get("days") or 0)} days</p>
    <p>Scorecard: {html.escape(str(squad_scorecard.get("status", "not available")))}</p>
    <p>Options paper: <strong>{html.escape(str(options.get("status", "not available")))}</strong> &middot; {paper_days}/56 days &middot; {int(options_paper.get("fills") or 0)} fills</p>
    <p>Free replay: {_money(replay.get("final_equity"))} &middot; {int(replay.get("snapshots") or 0)} snapshots &middot; one day only</p>
  </div>
  <div class="panel">
    <h3>Swing options</h3>
    <p><strong>{_money(swing_account.get("equity"))}</strong> &middot; {swing_signal_text}</p>
    <p>As of {swing_as_of} &middot; fills {swing_fills} &middot; exits {swing_exits}</p>
    <p>{swing_task_text}</p>
  </div>
</div>

<div class="section"><h2>Testnet canary</h2><span class="sub">Operational validation only, not evidence</span></div>
<div class="panel">
  <h3>Deribit testnet canary {_chip("status", canary_ok)}</h3>
  <p>{canary_text}</p>
  <p>Open orders: {canary_open} &middot; nonzero positions: {canary_positions}</p>
</div>

<div class="warning">This Vercel page is a read-only snapshot. It cannot place orders. The full Streamlit operations console runs locally or on a persistent host.</div>
<footer class="footer">
  Read-only snapshot. Full dashboard: <code>uv run streamlit run src/tradingbot/ops/dashboard.py</code><br>
  Spot failures: {html.escape(failed)}<br>
  Options failures: {html.escape(options_failed)}
</footer>
</main>
</body>
</html>"""
    return page


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
def api_status(request: Request) -> JSONResponse:
    _guard(request)
    return JSONResponse(_status())


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    _guard(request)
    return HTMLResponse(_page(_status()))
