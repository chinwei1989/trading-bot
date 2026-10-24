"""Vercel-compatible read-only status dashboard.

The full Streamlit dashboard lives in ``streamlit_app.py``. Vercel's Python
function bundle cannot hold Streamlit plus its transitive dependencies under the
500 MB limit, so this entrypoint is deliberately small: stdlib + FastAPI, reading
a generated ``deploy/status.json`` snapshot.

Update the snapshot with ``scripts/export_deploy_status.py`` and redeploy to
refresh it. The snapshot is read-only and contains no credentials.
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

app = FastAPI(title="Trading Bot Status", docs_url=None, redoc_url=None)


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
        return "—"


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
    data = _status()
    gate = data.get("gate") or {}
    health = data.get("health") or {}
    gate_status = str(gate.get("status", "NO_GO"))
    gate_class = "good" if gate_status == "GO" else "bad"
    health_status = str(health.get("status", "N/A"))
    campaigns = data.get("campaigns") or {}
    squad = data.get("ai_squad") or {}
    squad_scorecard = data.get("ai_squad_scorecard") or {}
    options = data.get("options_evidence") or {}
    options_gate = data.get("options_live_gate") or {}
    readiness = data.get("readiness") or {}

    cards = []
    for name in (
        "trend",
        "xsmom",
        "breakout",
        "reversal",
        "meta",
        "ai",
        "intraday",
        "ai_options_30m",
    ):
        row = campaigns.get(name) or {}
        cards.append(
            f"<div class='card'><div class='label'>{html.escape(name.upper())}</div>"
            f"<div class='value'>{_money(row.get('equity'))}</div>"
            f"<div class='muted'>{int(row.get('days') or 0)} days</div></div>"
        )
    failed = ", ".join(str(x) for x in gate.get("failed", [])) or "none"
    campaigns_html = "".join(cards)
    squad_days = int(squad.get("days") or 0)
    squad_status = str(squad_scorecard.get("status", "not available"))
    squad_html = (
        "<div class='status'><span class='dot'></span>"
        f"<strong>AI squad: {_money(squad.get('equity'))}</strong>"
        f"<span class='muted'>{squad_days} days · scorecard "
        f"{html.escape(squad_status)}</span></div>"
    )
    paper = options.get("paper") or {}
    replay = options.get("replay") or {}
    options_status = str(options.get("status", "not available"))
    options_gate_status = str(options_gate.get("status", "NO_GO"))
    paper_days = int(paper.get("paper_days") or 0)
    options_html = (
        "<div class='status'><span class='dot'></span>"
        f"<strong>Options paper: {html.escape(options_status)}</strong>"
        f"<span class='muted'>{paper_days}/56 days / "
        f"{int(paper.get('fills') or 0)} fills / "
        f"live gate {html.escape(options_gate_status)}</span></div>"
        "<div class='status'><span class='dot'></span>"
        f"<strong>Free real-chain replay: {_money(replay.get('final_equity'))}</strong>"
        f"<span class='muted'>{int(replay.get('snapshots') or 0)} snapshots / "
        f"{float(replay.get('total_return') or 0):.2%} return / "
        "one day only, not evidence of edge</span></div>"
    )
    readiness_status = (
        f"paper_ready={readiness.get('paper_ready')} "
        f"live_ready={readiness.get('live_ready')}"
    )
    generated = html.escape(str(data.get("generated_at") or "not generated"))
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>Trading Bot — Read-only Status</title>
<style>
:root {{ color-scheme: dark; --bg:#070b16; --panel:#0f172a; --line:#1e293b; --text:#e2e8f0; --muted:#94a3b8; --good:#34d399; --bad:#f87171; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.5 Inter,system-ui,Segoe UI,sans-serif; }}
main {{ max-width: 980px; margin: 0 auto; padding: 48px 24px; }}
h1 {{ margin: 0 0 6px; font-size: 28px; }}
p {{ color: var(--muted); }}
.status {{ display:flex; gap:12px; align-items:center; margin:24px 0; padding:18px; background:var(--panel); border:1px solid var(--line); border-radius:14px; }}
.dot {{ width:10px; height:10px; border-radius:50%; background:var(--muted); }}
.good .dot, .dot.good {{ background:var(--good); }}
.bad .dot, .dot.bad {{ background:var(--bad); }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; }}
.card {{ padding:18px; background:var(--panel); border:1px solid var(--line); border-radius:14px; }}
.label {{ color:var(--muted); font-size:11px; letter-spacing:.12em; }}
.value {{ font-size:22px; font-weight:700; margin-top:6px; }}
.muted {{ color:var(--muted); font-size:12px; margin-top:4px; }}
footer {{ margin-top:32px; color:var(--muted); font-size:12px; border-top:1px solid var(--line); padding-top:18px; }}
a {{ color:#38bdf8; }}
</style>
</head>
<body>
<main>
<h1>Trading Bot — Read-only Status</h1>
<p>Vercel lite dashboard. No order controls. Snapshot generated: {generated}</p>
<div class="status {gate_class}"><span class="dot {gate_class}"></span>
<strong>Live-capital gate: {html.escape(gate_status)}</strong>
<span class="muted">Failed checks: {html.escape(failed)}</span></div>
<div class="grid">{campaigns_html}</div>
{squad_html}
{options_html}
<div class="status"><span class="dot"></span>
<strong>Campaign health: {html.escape(health_status)}</strong>
<span class="muted">Paper days required: 56 / {html.escape(readiness_status)}</span></div>
<footer>
Read-only snapshot. The full Streamlit dashboard is available locally with
<code>scripts/run_dashboard.ps1</code> or on a persistent container host.
No broker credentials or order actions exist in this app.
</footer>
</main>
</body>
</html>"""
    return HTMLResponse(page)
