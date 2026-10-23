"""Generate the 3D agent-office visualization from real paper artifacts."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from tradingbot.config import load_config
from tradingbot.ops.heartbeat import read_heartbeat
from tradingbot.ops.performance import load_performance

ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = Path(__file__).with_name("office_template.html")
VENDOR = ROOT / "web" / "vendor"


AGENT_SPECS: list[dict[str, Any]] = [
    {
        "id": "head_trading",
        "name": "Priya",
        "role": "Head of Trading",
        "config": "config/base.yaml",
        "report": "evaluation_trend.json",
        "position": [-12.0, -4.0],
        "floor": 1,
        "room": "Live Trading Room",
        "squad": "trading",
        "manager": "meta",
        "accent": "#22d3ee",
        "shirt": "#0e7490",
        "skin": "#c98c63",
        "hair": "#2a1b12",
        "standing": True,
        "speech": "Four sleeves, one trading floor",
        "badge": True,
    },
    {
        "id": "trend",
        "name": "Maya",
        "role": "Trend Agent",
        "config": "config/base.yaml",
        "report": "evaluation_trend.json",
        "position": [-8.5, -4.0],
        "floor": 1,
        "room": "Live Trading Room",
        "squad": "trading",
        "manager": "head_trading",
        "accent": "#38bdf8",
        "shirt": "#1d4ed8",
        "skin": "#e8b48a",
        "hair": "#241a16",
        "standing": False,
        "speech": "Watching the 200-day trend",
    },
    {
        "id": "xsmom",
        "name": "Leo",
        "role": "XSMOM Agent",
        "config": "config/xsmom.yaml",
        "report": "evaluation_xsmom.json",
        "position": [-4.5, -4.0],
        "floor": 1,
        "room": "Live Trading Room",
        "squad": "trading",
        "manager": "head_trading",
        "accent": "#2dd4bf",
        "shirt": "#0f766e",
        "skin": "#d79a6a",
        "hair": "#151515",
        "standing": False,
        "speech": "Ranking cross-sectional momentum",
    },
    {
        "id": "breakout",
        "name": "Nina",
        "role": "Breakout Agent",
        "config": "config/breakout.yaml",
        "report": "evaluation_breakout.json",
        "position": [-0.5, -4.0],
        "floor": 1,
        "room": "Live Trading Room",
        "squad": "trading",
        "manager": "head_trading",
        "accent": "#fb923c",
        "shirt": "#c2410c",
        "skin": "#f0c19a",
        "hair": "#4a2a1a",
        "standing": False,
        "speech": "Waiting for a 55-day break",
    },
    {
        "id": "reversal",
        "name": "Omar",
        "role": "Reversal Agent",
        "config": "config/reversal.yaml",
        "report": "evaluation_reversal.json",
        "position": [3.5, -4.0],
        "floor": 1,
        "room": "Live Trading Room",
        "squad": "trading",
        "manager": "head_trading",
        "accent": "#f87171",
        "shirt": "#991b1b",
        "skin": "#b97a52",
        "hair": "#121212",
        "standing": False,
        "speech": "Looking for an oversold snapback",
    },
    {
        "id": "execution",
        "name": "Sam",
        "role": "Execution Agent",
        "config": "config/base.yaml",
        "report": "evaluation_trend.json",
        "position": [7.0, -4.0],
        "floor": 1,
        "room": "Live Trading Room",
        "squad": "risk",
        "manager": "chief_risk",
        "accent": "#f472b6",
        "shirt": "#9d174d",
        "skin": "#dfa77d",
        "hair": "#1a1512",
        "standing": False,
        "speech": "Slicing, retrying, reconciling",
        "clipboard": True,
    },
    {
        "id": "head_research",
        "name": "Noah",
        "role": "Head of Research & AI",
        "config": "config/ai_agent.yaml",
        "report": "ai/latest.json",
        "position": [-12.0, 0.5],
        "floor": 1,
        "room": "Research Lab",
        "squad": "research",
        "manager": "meta",
        "accent": "#a3e635",
        "shirt": "#3f6212",
        "skin": "#d69a6a",
        "hair": "#1c1917",
        "standing": True,
        "speech": "Turning research into evidence",
        "badge": True,
    },
    {
        "id": "ai",
        "name": "Jev",
        "role": "AI Decision Agent",
        "config": "config/ai_agent.yaml",
        "report": "ai/latest.json",
        "position": [-8.5, 1.0],
        "floor": 1,
        "room": "AI Lab",
        "squad": "research",
        "manager": "head_research",
        "accent": "#a78bfa",
        "shirt": "#5b21b6",
        "skin": "#e7b48e",
        "hair": "#1f1b2e",
        "standing": False,
        "speech": "Typed decisions, confidence gated",
        "headset": True,
    },
    {
        "id": "data",
        "name": "Kai",
        "role": "Data Engineer",
        "config": "config/base.yaml",
        "report": "evaluation_trend.json",
        "position": [-12.0, 3.8],
        "floor": 1,
        "room": "Data Lab",
        "squad": "research",
        "manager": "head_research",
        "accent": "#a3e635",
        "shirt": "#3f6212",
        "skin": "#d69a6a",
        "hair": "#1c1917",
        "standing": False,
        "speech": "Checking bar freshness and gaps",
    },
    {
        "id": "meta",
        "name": "Ava",
        "role": "Portfolio Director",
        "config": "config/meta.yaml",
        "report": "evaluation_meta.json",
        "position": [12.2, -8.0],
        "floor": 1,
        "room": "Director Room",
        "squad": "executive",
        "manager": None,
        "accent": "#e879f9",
        "shirt": "#6b21a8",
        "skin": "#e5b08a",
        "hair": "#24121c",
        "standing": True,
        "speech": "One portfolio, one risk budget",
        "badge": True,
    },
    {
        "id": "chief_risk",
        "name": "Elena",
        "role": "Chief Risk Officer",
        "config": "config/base.yaml",
        "report": "evaluation_trend.json",
        "position": [14.0, 1.5],
        "floor": 1,
        "room": "Risk Office",
        "squad": "risk",
        "manager": "meta",
        "accent": "#facc15",
        "shirt": "#854d0e",
        "skin": "#c98c63",
        "hair": "#2a1b12",
        "standing": True,
        "speech": "No GO without evidence",
        "badge": True,
    },
    {
        "id": "risk",
        "name": "Rhea",
        "role": "Risk Manager",
        "config": "config/base.yaml",
        "report": "evaluation_trend.json",
        "position": [10.8, 1.5],
        "floor": 1,
        "room": "Risk Office",
        "squad": "risk",
        "manager": "chief_risk",
        "accent": "#facc15",
        "shirt": "#854d0e",
        "skin": "#c98c63",
        "hair": "#2a1b12",
        "standing": True,
        "speech": "Hard limits, kill switch, live gate",
        "badge": True,
    },
]


_WEATHER_CACHE: tuple[float, dict[str, Any]] | None = None


def _singapore_environment() -> dict[str, Any]:
    """Singapore local time plus optional free Open-Meteo current weather."""
    global _WEATHER_CACHE
    now = datetime.now(UTC)
    local = now + timedelta(hours=8)
    hour = local.hour
    if 5 <= hour < 7:
        phase = "dawn"
    elif 7 <= hour < 17:
        phase = "day"
    elif 17 <= hour < 20:
        phase = "dusk"
    else:
        phase = "night"
    weather = "sunny"
    temperature: float | None = None
    source = "clock"
    if _WEATHER_CACHE is not None:
        stamp, cached = _WEATHER_CACHE
        if now.timestamp() - stamp < 600:
            return cached
    try:
        response = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": 1.3521,
                "longitude": 103.8198,
                "current": "temperature_2m,weather_code,is_day",
                "timezone": "Asia/Singapore",
            },
            timeout=2.5,
        )
        response.raise_for_status()
        current = response.json().get("current", {})
        code = int(current.get("weather_code", 0))
        temperature = float(current["temperature_2m"]) if current.get("temperature_2m") is not None else None
        if code in {0, 1}:
            weather = "sunny"
        elif code in {2, 3, 45, 48}:
            weather = "cloudy"
        else:
            weather = "rain"
        source = "open-meteo"
    except Exception:
        # Stable fallback so the office still varies without a network.
        weather = ("sunny", "cloudy", "rain")[(local.toordinal() + hour // 6) % 3]
    payload = {
        "timezone": "Asia/Singapore",
        "local_time": local.strftime("%Y-%m-%d %H:%M"),
        "hour": hour,
        "phase": phase,
        "weather": weather,
        "temperature_c": temperature,
        "source": source,
    }
    _WEATHER_CACHE = (now.timestamp(), payload)
    return payload


def _resolve(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def _json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _spark(path: Path) -> list[float]:
    try:
        perf = load_performance(path)
    except Exception:
        return [1.0, 1.0]
    if perf.is_empty() or "equity" not in perf.columns:
        return [1.0, 1.0]
    values = [float(value) for value in perf["equity"].tail(28).to_list()]
    return values if len(values) >= 2 else [values[0], values[0]] if values else [1.0, 1.0]


def _heartbeat(config_path: Path, root: Path) -> dict[str, Any] | None:
    try:
        config = load_config(config_path)
    except Exception:
        return None
    return read_heartbeat(_resolve(root, config.broker.heartbeat_path))


def _status_for_report(report: dict[str, Any] | None, heartbeat: dict[str, Any] | None) -> str:
    if report is None:
        return "offline"
    if heartbeat and heartbeat.get("status") == "error":
        return "error"
    if report.get("alerts"):
        return "warning"
    if heartbeat and heartbeat.get("status") == "ok":
        return "active"
    return "idle"


def _agent_payload(
    spec: dict[str, Any],
    root: Path,
    gate: dict[str, Any] | None,
    trend_report: dict[str, Any] | None,
) -> dict[str, Any]:
    agent_id = spec["id"]
    report_path = root / "artifacts" / "reports" / spec["report"]
    if spec["report"].startswith("ai/"):
        report_path = root / "artifacts" / "ai" / "reports" / "latest.json"
    report = _json(report_path)
    config_path = root / spec["config"]
    heartbeat = _heartbeat(config_path, root)
    status = _status_for_report(report, heartbeat)
    equity = 0.0
    pnl = 0.0
    metric = "—"
    detail = spec["speech"]
    spark = [1.0, 1.0]

    if agent_id == "ai":
        report = _json(root / "artifacts" / "ai" / "reports" / "latest.json")
        status = "offline"
        if report:
            status = "error" if report.get("status") == "error" else "warning" if report.get("fallback") else "active"
            account = report.get("account", {})
            equity = float(account.get("equity", 0.0))
            pnl = equity / 10_000.0 - 1.0
            decision = report.get("decision", {})
            metric = f"{decision.get('regime', '?')} · {float(decision.get('confidence', 0)):.0%}"
            detail = f"Jev {report.get('model', '?')} · {report.get('status', '?')}"
            spark = _spark(root / "artifacts" / "ai" / "performance.jsonl")
    elif agent_id == "risk":
        gate_status = (gate or {}).get("status", "NO_GO")
        status = "active" if gate_status == "GO" else "warning"
        metric = gate_status
        failed = (gate or {}).get("failed", [])
        detail = "All hard gates pass" if gate_status == "GO" else f"{len(failed)} gate failures"
        spark = [1.0, 1.0, 1.0, 1.0]
    elif agent_id == "execution":
        reports = [
            _json(root / "artifacts" / "reports" / f"evaluation_{name}.json")
            for name in ("trend", "xsmom", "breakout", "meta")
        ]
        fills = sum(float((item or {}).get("tca", {}).get("fills", 0)) for item in reports)
        slip_values = [
            float((item or {}).get("tca", {}).get("weighted_slip_bps", 0))
            for item in reports
            if item
        ]
        metric = f"{fills:.0f} fills"
        detail = f"{sum(slip_values) / len(slip_values):.1f} bps avg slip" if slip_values else "No fills yet"
        status = "active" if fills else "idle"
        spark = [1.0, 1.0, 1.0]
    elif agent_id == "data":
        data = (trend_report or {}).get("data", {})
        age = data.get("age_days")
        metric = f"{age}d old" if age is not None else "no data"
        assets = data.get("assets")
        detail = f"{assets} assets · {data.get('rows', '?')} rows" if assets else "Waiting for data"
        status = "active" if isinstance(age, int) and age <= 2 else "warning"
        spark = [1.0, 1.0, 1.0]
    elif report:
        account = report.get("account", {})
        equity = float(account.get("equity", 0.0))
        pnl = equity / 10_000.0 - 1.0
        metric = f"${equity:,.0f}"
        tca = report.get("tca", {})
        detail = f"TCA {float(tca.get('weighted_slip_bps', 0)):.1f} bps"
        if agent_id == "reversal" and not account.get("positions"):
            status = "idle"
            detail = "No oversold setup; staying patient"
        if report.get("alerts"):
            status = "warning"
        spark = _spark(_resolve(root, load_config(config_path).broker.performance_path))

    return {
        **spec,
        "status": status,
        "equity": equity,
        "pnl_pct": pnl,
        "metric": metric,
        "detail": detail,
        "spark": spark,
        "heartbeat": heartbeat or {},
    }


def _last_equity(path: Path, start: float = 10_000.0) -> tuple[float, float]:
    try:
        perf = load_performance(path)
    except Exception:
        return start, 0.0
    if perf.is_empty() or "equity" not in perf.columns:
        return start, 0.0
    equity = float(perf["equity"].tail(1).to_list()[0])
    return equity, equity / start - 1.0


def _competition(root: Path) -> dict[str, Any]:
    quant_equity, quant_return = _last_equity(root / "artifacts" / "performance_meta.jsonl")
    agent_equity, agent_return = _last_equity(root / "artifacts" / "ai" / "performance.jsonl")
    winner = "quant" if quant_return > agent_return else "agents" if agent_return > quant_return else "tie"
    return {
        "round": "Paper challenge - start $10,000 each",
        "winner": winner,
        "teams": [
            {
                "id": "quant",
                "name": "Quant Floor",
                "short": "Quant",
                "floor": 0,
                "equity": quant_equity,
                "return_pct": quant_return,
                "color": "#38bdf8",
                "status": "deterministic",
            },
            {
                "id": "agents",
                "name": "Agent Floor",
                "short": "Agents",
                "floor": 1,
                "equity": agent_equity,
                "return_pct": agent_return,
                "color": "#a78bfa",
                "status": "Jev + agent office",
            },
        ],
    }


def build_office_data(root: Path | None = None) -> dict[str, Any]:
    root = root or ROOT
    gate = _json(root / "artifacts" / "LIVE_GATE.json")
    trend_report = _json(root / "artifacts" / "reports" / "evaluation_trend.json")
    agents = [
        _agent_payload(spec, root, gate, trend_report) for spec in AGENT_SPECS
    ]
    counts: dict[str, int] = {}
    for agent in agents:
        counts[agent["status"]] = counts.get(agent["status"], 0) + 1
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "title": "The Agent Office",
        "subtitle": "Two levels - quant workflow below - agent office above - read-only",
        "gate": (gate or {}).get("status", "NO_GO"),
        "gate_failed": (gate or {}).get("failed", []),
        "counts": counts,
        "environment": _singapore_environment(),
        "competition": _competition(root),
        "floors": [
            {
                "id": "workflow",
                "name": "Level 1 - Quant Workflow",
                "short": "Workflow",
                "accent": "#38bdf8",
                "rooms": ["Data Lake", "Feature Lab", "Backtest Grid", "Risk Vault", "Meta Table", "Execution Gateway", "Evaluation", "Quant Meeting", "Quant Pantry", "Quant Fun"],
                "waypoints": [],
            },
            {
                "id": "agents",
                "name": "Level 2 - Agent Office",
                "short": "Agents",
                "accent": "#a78bfa",
                "rooms": [
                    "Trading Bullpen", "AI Lab", "Data Lab", "Discussion Room",
                    "Meeting Room", "Director Room", "Risk Office", "Guest Room",
                    "Pantry", "Entertainment", "Lobby", "WC",
                ],
                "waypoints": [
                    [-12, 6], [-5, 7], [1, 7], [5, 7],
                    [0, 2.5], [-12, 3.5], [12, 2], [6, -1], [-2, -1],
                ],
            },
        ],
        "squads": [
            {
                "id": "trading",
                "name": "Trading Squad",
                "manager": "head_trading",
                "members": ["trend", "xsmom", "breakout", "reversal"],
                "floor": 1,
                "color": "#38bdf8",
            },
            {
                "id": "research",
                "name": "Research & AI",
                "manager": "head_research",
                "members": ["ai", "data"],
                "floor": 1,
                "color": "#a78bfa",
            },
            {
                "id": "risk",
                "name": "Risk & Execution",
                "manager": "chief_risk",
                "members": ["risk", "execution"],
                "floor": 1,
                "color": "#facc15",
            },
            {
                "id": "executive",
                "name": "Office of the Director",
                "manager": "meta",
                "members": ["meta"],
                "floor": 1,
                "color": "#e879f9",
            },
        ],
        "agents": agents,
    }


def build_office_html(root: Path | None = None) -> str:
    root = root or ROOT
    template = TEMPLATE.read_text(encoding="utf-8")
    data = build_office_data(root)
    payload = json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/")
    three = (VENDOR / "three.min.js").read_text(encoding="utf-8")
    orbit = (VENDOR / "OrbitControls.js").read_text(encoding="utf-8")
    return (
        template.replace("__THREE_JS__", three)
        .replace("__ORBIT_JS__", orbit)
        .replace("__OFFICE_DATA__", payload)
    )
