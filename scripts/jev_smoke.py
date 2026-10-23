"""Run ten point-in-time dry decisions through the configured AI provider.

This is a smoke test, not a backtest and not paper evidence. With Jev selected
it costs a small number of input tokens and sends only market features/paper
context. No orders are sent.

Usage:
    uv run python scripts/jev_smoke.py
    uv run python scripts/jev_smoke.py --provider deterministic   # plumbing only
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, time
from pathlib import Path

from dotenv import load_dotenv

from tradingbot.ai.pipeline import run_ai_cycle
from tradingbot.config import load_config
from tradingbot.data.store import load_bars

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/ai_agent.yaml")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument(
        "--provider", choices=["jev", "openai_compatible", "deterministic"], default=None
    )
    args = parser.parse_args()

    config = load_config(ROOT / args.config)
    provider = args.provider or config.agent.provider
    if provider == "jev" and not os.getenv(config.agent.api_key_env):
        print(
            f"Jev is selected but {config.agent.api_key_env} is not set. "
            "Set it in the environment and rerun. Nothing was sent."
        )
        return 2

    bars_path = ROOT / config.data.bars_path
    bars = load_bars(bars_path)
    dates = bars["timestamp"].unique().sort().to_list()[-args.runs :]
    if not dates:
        print("no bars available")
        return 1
    if provider == "deterministic":
        print("WARNING: deterministic provider selected; this validates plumbing, not AI.")

    results = []
    for i, date in enumerate(dates, 1):
        as_of = datetime.combine(date.date(), time.max, tzinfo=UTC)
        print(f"[{i}/{len(dates)}] {as_of.date()} ...", flush=True)
        result = run_ai_cycle(
            config,
            root=ROOT,
            dry_run=True,
            provider_override=provider,
            as_of=as_of,
            fresh=True,
        )
        row = {
            "as_of": result.as_of,
            "status": result.status,
            "provider": result.provider,
            "model": result.model,
            "fallback": result.fallback,
            "regime": result.decision.regime if result.decision else None,
            "confidence": result.decision.confidence if result.decision else None,
            "gross": result.policy.gross if result.policy else None,
            "latency_ms": result.decision.latency_ms if result.decision else None,
            "alerts": result.alerts,
        }
        results.append(row)
        print(
            f"  provider={row['provider']} regime={row['regime']} "
            f"confidence={row['confidence']} gross={row['gross']}"
        )
        if result.status == "error":
            print("  provider error; stopping smoke run")
            break

    out_dir = ROOT / "artifacts" / "ai" / "smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    path = out_dir / f"jev_smoke_{stamp}.json"
    path.write_text(
        json.dumps(
            {
                "provider_requested": provider,
                "runs": len(results),
                "results": results,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"Saved: {path}")

    # Restore a current report after the historical dry runs.
    config.agent.provider = provider
    run_ai_cycle(
        config,
        root=ROOT,
        dry_run=True,
        provider_override=provider,
        fresh=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
