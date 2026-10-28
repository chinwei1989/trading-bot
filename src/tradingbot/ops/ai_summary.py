"""Generate a concise AI gist of the current paper book.

Jev is a typed-decision model, not a prose writer. This module asks Jev for
three typed classifications (posture, next paper action, dominant risk), then
combines those classifications with deterministic facts from the local paper
state. The UI labels the result as a Jev-classified gist so it is not mistaken
for free-form model prose.

The generation path is read-only with respect to trading: it never calls a
broker, updates a strategy, or changes paper state.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from tradingbot.ai.providers import JevProvider
from tradingbot.config import load_config
from tradingbot.data.store import load_bars

SPOT_LANES: dict[str, dict[str, str]] = {
    "Trend": {
        "state": "artifacts/paper_state.json",
        "performance": "artifacts/performance_trend.jsonl",
    },
    "XSMOM": {
        "state": "artifacts/paper_state_xsmom.json",
        "performance": "artifacts/performance_xsmom.jsonl",
    },
    "Breakout": {
        "state": "artifacts/paper_state_breakout.json",
        "performance": "artifacts/performance_breakout.jsonl",
    },
    "Reversal": {
        "state": "artifacts/paper_state_reversal.json",
        "performance": "artifacts/performance_reversal.jsonl",
    },
    "Meta": {
        "state": "artifacts/paper_state_meta.json",
        "performance": "artifacts/performance_meta.jsonl",
    },
    "Intraday": {
        "state": "artifacts/intraday/paper_state.json",
        "performance": "artifacts/intraday/performance.jsonl",
    },
    "AI agent": {
        "state": "artifacts/ai/paper_state.json",
        "performance": "artifacts/ai/performance.jsonl",
    },
    "AI squad": {
        "state": "artifacts/ai_squad/paper_state.json",
        "performance": "artifacts/ai_squad/performance.jsonl",
    },
    "SUI lab": {
        "state": "artifacts/sui/paper_state.json",
        "performance": "artifacts/sui/performance.jsonl",
    },
}

OPTION_STATES: dict[str, str] = {
    "Swing options": "artifacts/options_swing/paper_state.json",
    "AI options 30m": "artifacts/ai_options_30m/paper_state.json",
    "ETH options lab": "artifacts/ai_options_eth/paper_state.json",
    "BTC options lab": "artifacts/ai_options_btc_lab/paper_state.json",
}

SUMMARY_PATH = Path("artifacts/ai_summary/latest.json")


class AISummaryError(RuntimeError):
    """The gist could not be generated; no stale result is overwritten."""


def load_summary_env(root: Path) -> None:
    """Load only the Jev key from .env; never print or return it."""
    if os.getenv("TYPESAFE_API_KEY"):
        return
    env_path = root / ".env"
    if not env_path.exists():
        return
    values = dotenv_values(env_path)
    key = values.get("TYPESAFE_API_KEY")
    if key:
        os.environ["TYPESAFE_API_KEY"] = key


def _json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _last_performance(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    last: dict[str, Any] | None = None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if isinstance(row, dict):
                    last = row
    except (OSError, json.JSONDecodeError):
        return None
    return last


def _latest_prices(root: Path) -> tuple[dict[str, float], str]:
    path = root / "data" / "normalized" / "bars.parquet"
    if not path.exists():
        return {}, "?"
    bars = load_bars(path).sort("timestamp")
    if bars.is_empty():
        return {}, "?"
    last = bars.group_by("asset").tail(1)
    prices = {
        str(row["asset"]): float(row["close"])
        for row in last.iter_rows(named=True)
    }
    latest = bars["timestamp"].max()
    return prices, str(latest)[:10] if latest is not None else "?"


def _signed_money(value: float) -> str:
    return f"{'+' if value >= 0 else '-'}${abs(value):,.2f}"


def _signed_pct(value: float) -> str:
    return f"{value:+.2%}"


def _choice(answers: dict[str, Any], key: str, allowed: set[str]) -> str:
    answer = answers.get(key)
    value = str(answer.get("choice", "")) if isinstance(answer, dict) else ""
    return value if value in allowed else sorted(allowed)[0]


def _confidence(answers: dict[str, Any]) -> float:
    values = [
        float(answer.get("confidence", 0.0) or 0.0)
        for answer in answers.values()
        if isinstance(answer, dict)
    ]
    return max(0.0, min(1.0, sum(values) / len(values))) if values else 0.0


def _state(root: Path) -> dict[str, Any]:
    prices, as_of = _latest_prices(root)
    lane_rows: list[dict[str, Any]] = []
    position_rows: list[dict[str, Any]] = []
    for lane, spec in SPOT_LANES.items():
        state = _json(root / spec["state"]) or {}
        positions = state.get("positions") or {}
        initial = float(state.get("initial_cash", 10_000.0) or 10_000.0)
        perf = _last_performance(root / spec["performance"]) or {}
        try:
            equity = float(perf.get("equity", 0.0) or 0.0)
        except (TypeError, ValueError):
            equity = 0.0
        if equity <= 0:
            equity = float(state.get("cash", 0.0) or 0.0) + sum(
                float(pos.get("qty", 0.0) or 0.0) * prices.get(asset, 0.0)
                for asset, pos in positions.items()
            )
        lane_pnl = equity - initial
        lane_rows.append(
            {
                "lane": lane,
                "equity": round(equity, 2),
                "starting_cash": initial,
                "pnl": round(lane_pnl, 2),
                "pnl_pct": round(lane_pnl / initial, 6) if initial else 0.0,
                "positions": len(positions),
            }
        )
        for asset, pos in positions.items():
            qty = float(pos.get("qty", 0.0) or 0.0)
            if abs(qty) < 1e-12:
                continue
            price = prices.get(asset)
            entry_raw = pos.get("avg_entry_price")
            entry = (
                float(entry_raw)
                if entry_raw is not None and float(entry_raw) > 0
                else None
            )
            value = qty * price if price is not None else 0.0
            pnl = (
                (price - entry) * qty
                if price is not None and entry is not None
                else None
            )
            position_rows.append(
                {
                    "lane": lane,
                    "asset": asset,
                    "side": "long" if qty > 0 else "short",
                    "qty": round(qty, 6),
                    "entry": round(entry, 6) if entry is not None else None,
                    "cost": round(abs(qty) * entry, 2) if entry is not None else None,
                    "last_price": round(price, 8) if price is not None else None,
                    "value": round(value, 2),
                    "weight": round(value / equity, 8) if equity else 0.0,
                    "pnl": round(pnl, 2) if pnl is not None else None,
                    "pnl_pct": round(pnl / (abs(qty) * entry), 6)
                    if pnl is not None and entry
                    else None,
                }
            )

    option_rows: list[dict[str, Any]] = []
    for lane, path in OPTION_STATES.items():
        state = _json(root / path) or {}
        for instrument, holding in (state.get("holdings") or {}).items():
            qty = float(holding.get("qty", 0.0) or 0.0)
            if abs(qty) < 1e-12:
                continue
            mark = float(holding.get("mark_premium", 0.0) or 0.0)
            multiplier = float(holding.get("multiplier", 1.0) or 1.0)
            option_rows.append(
                {
                    "lane": lane,
                    "instrument": instrument,
                    "qty": qty,
                    "value": round(qty * mark * multiplier, 2),
                }
            )

    open_pnls = [
        float(row["pnl"])
        for row in position_rows
        if row.get("pnl") is not None
    ]
    costs = [
        float(row["cost"])
        for row in position_rows
        if row.get("cost") is not None
    ]
    gross = sum(abs(float(row["value"])) for row in position_rows)
    net = sum(float(row["value"]) for row in position_rows)
    open_pnl = sum(open_pnls)
    cost_basis = sum(costs)
    lane_pnl = sum(float(row["pnl"]) for row in lane_rows)
    lane_initial = sum(float(row["starting_cash"]) for row in lane_rows)
    sui = [row for row in position_rows if row["asset"] == "SUIUSDT"]
    readiness = _json(root / "artifacts" / "READINESS.json") or {}
    return {
        "as_of": as_of,
        "paper_only": True,
        "portfolio": {
            "gross_usd": round(gross, 2),
            "net_usd": round(net, 2),
            "open_pnl_usd": round(open_pnl, 2),
            "open_pnl_pct": round(open_pnl / cost_basis, 6)
            if cost_basis
            else 0.0,
            "lane_pnl_usd": round(lane_pnl, 2),
            "lane_pnl_pct": round(lane_pnl / lane_initial, 6)
            if lane_initial
            else 0.0,
            "positions": len(position_rows),
            "active_lanes": sum(1 for row in lane_rows if row["positions"]),
            "paper_accounts": len(lane_rows),
        },
        "spot_lanes": lane_rows,
        "positions": position_rows,
        "top_positions": sorted(
            position_rows, key=lambda row: abs(row["value"]), reverse=True
        )[:6],
        "sui": {
            "qty": round(sum(float(row["qty"]) for row in sui), 6),
            "value_usd": round(sum(float(row["value"]) for row in sui), 2),
            "pnl_usd": round(
                sum(float(row["pnl"]) for row in sui if row.get("pnl") is not None),
                2,
            ),
        },
        "options": {
            "open_contracts": len(option_rows),
            "value_usd": round(sum(float(row["value"]) for row in option_rows), 2),
        },
        "gates": {
            "spot_live": str(readiness.get("live_gate", "NO_GO")),
            "options_live": str(readiness.get("options_live_gate", "NO_GO")),
            "host": str(readiness.get("host_status", "UNKNOWN")),
        },
        "note": (
            "Independent paper accounts; aggregate values are illustrative and "
            "not one brokerage balance. No live order path."
        ),
    }


def _questions() -> dict[str, dict[str, Any]]:
    return {
        "posture": {
            "type": "choice",
            "instructions": (
                "Classify the overall posture of this paper-only crypto book. "
                "Use only the supplied state. Do not give financial advice."
            ),
            "criteria": {
                "constructive": "Net long, positive P&L, and contained risk.",
                "cautious": "Mixed/flat P&L, meaningful shorts, or concentration risk.",
                "defensive": "Negative P&L, elevated risk, or evidence gaps dominate.",
            },
        },
        "next_action": {
            "type": "choice",
            "instructions": (
                "Choose the most appropriate next action for the paper book. "
                "The deterministic policy layer owns sizing and execution."
            ),
            "criteria": {
                "hold": "Hold current paper exposures and monitor.",
                "trim": "Reduce gross or concentration risk.",
                "review": "Review the book before adding risk.",
                "add": "The risk budget supports selectively adding exposure.",
            },
        },
        "top_risk": {
            "type": "choice",
            "instructions": (
                "Identify the dominant near-term risk in this paper book. "
                "Use only the supplied state."
            ),
            "criteria": {
                "market_reversal": "Trend reversal or momentum failure.",
                "concentration": "Concentration or one-asset dependence.",
                "volatility": "Volatility or drawdown risk.",
                "execution": "Liquidity, execution, or data reliability risk.",
                "evidence": "Forward paper evidence is too short for confidence.",
            },
        },
    }


def _compose(
    state: dict[str, Any],
    answers: dict[str, Any],
    model: str,
    now: datetime,
) -> dict[str, Any]:
    posture = _choice(answers, "posture", {"constructive", "cautious", "defensive"})
    action = _choice(
        answers, "next_action", {"hold", "trim", "review", "add"}
    )
    risk = _choice(
        answers,
        "top_risk",
        {"market_reversal", "concentration", "volatility", "execution", "evidence"},
    )
    labels = {
        "constructive": "constructive",
        "cautious": "cautious",
        "defensive": "defensive",
        "hold": "hold and monitor",
        "trim": "trim risk",
        "review": "review before adding",
        "add": "add selectively",
        "market_reversal": "market reversal",
        "concentration": "concentration",
        "volatility": "volatility",
        "execution": "execution/data reliability",
        "evidence": "short forward evidence",
    }
    portfolio = state["portfolio"]
    sui = state["sui"]
    options = state["options"]
    gates = state["gates"]
    summary = (
        f"Jev reads the book as {labels[posture]} and marks the next paper "
        f"action as {labels[action]}. The dominant risk is "
        f"{labels[risk]}. "
        f"Across {portfolio['paper_accounts']} independent spot accounts, "
        f"gross is ${portfolio['gross_usd']:,.0f} and net is "
        f"${portfolio['net_usd']:,.0f}; open P&L is "
        f"{_signed_money(portfolio['open_pnl_usd'])} "
        f"({_signed_pct(portfolio['open_pnl_pct'])}), while lane P&L is "
        f"{_signed_money(portfolio['lane_pnl_usd'])} "
        f"({_signed_pct(portfolio['lane_pnl_pct'])})."
    )
    bullets = [
        f"{portfolio['positions']} open positions across "
        f"{portfolio['active_lanes']} active spot lanes.",
        f"SUI: {sui['qty']:,.1f} (~${sui['value_usd']:,.0f}), open P&L "
        f"{_signed_money(sui['pnl_usd'])}.",
        f"Options: {options['open_contracts']} open contracts; "
        f"spot live {gates['spot_live']}, options live {gates['options_live']}, "
        f"host {gates['host']}.",
        f"Paper data as of {state['as_of']}.",
    ]
    return {
        "headline": f"{labels[posture].title()} · {labels[action].title()}",
        "summary": summary,
        "bullets": bullets,
        "provider": "jev",
        "model": model,
        "method": "Jev typed classification + deterministic paper facts",
        "confidence": round(_confidence(answers), 4),
        "created_at": now.isoformat(),
        "data_as_of": state["as_of"],
        "paper_only": True,
        "answers": answers,
        "gates": gates,
        "state_note": state["note"],
    }


def build_ai_state_summary(
    root: Path,
    *,
    provider: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Generate and persist one Jev-classified, concise paper gist."""
    root = root.resolve()
    now = now or datetime.now(UTC)
    load_summary_env(root)
    state = _state(root)
    config = load_config(root / "config" / "ai_agent.yaml")
    chosen = provider or JevProvider(config.agent)
    try:
        answers, meta = chosen.ask(state, _questions())
    except Exception as exc:
        raise AISummaryError(
            f"Jev summary generation failed: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(answers, dict):
        raise AISummaryError("Jev summary returned no answers")
    model = str(meta.get("model", config.agent.model))
    payload = _compose(state, answers, model, now)
    out = root / SUMMARY_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    temp.replace(out)
    return payload


def load_ai_summary(root: Path) -> dict[str, Any] | None:
    return _json(root / SUMMARY_PATH)
