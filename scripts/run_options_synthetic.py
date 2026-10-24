"""Synthetic 30m options replay smoke test.

This is a mechanics test: constant-vol Black-Scholes chains, a simple 200-bar
trend signal, and the deterministic paper options pipeline. It is not evidence
of a profitable strategy.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tradingbot.config import DataConfig
from tradingbot.data.intraday import refresh_recent_bars
from tradingbot.options.backtest import replay_options
from tradingbot.options.synthetic import (
    SyntheticChainConfig,
    build_snapshots,
    sma_direction_signal,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "options_synthetic"


def main() -> int:
    config = DataConfig(
        source="binance",
        market="spot",
        interval="30m",
        symbols=["BTCUSDT", "ETHUSDT"],
        bars_path=Path("data/normalized/bars_30m_synthetic.parquet"),
        raw_dir=Path("data/raw_intraday"),
        include_recent=False,
        recent_limit=1000,
    )
    bars = refresh_recent_bars(config, ROOT, limit=1000)
    snapshots = build_snapshots(
        bars,
        config=SyntheticChainConfig(
            iv=0.50,
            expiry_days=(7, 14, 30),
            spread_pct=0.02,
        ),
    )
    signal = sma_direction_signal(bars, lookback=200)
    result = replay_options(
        snapshots,
        signal,
        initial_cash=10_000.0,
        fee_bps=3.0,
        max_contracts=1,
    )
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "engine": "synthetic Black-Scholes options replay",
        "underlying_interval": "30m",
        "underlying_bars": bars.height,
        "snapshots": len(snapshots),
        "final_equity": result.final_equity,
        "total_return": result.total_return,
        "max_drawdown": result.max_drawdown,
        "total_fills": result.total_fills,
        "total_fees": result.total_fees,
        "cycles_blocked": result.cycles_blocked,
        "last_cycles": [
            {
                "timestamp": cycle.timestamp.isoformat(),
                "equity": cycle.equity,
                "cash": cycle.cash,
                "open_legs": cycle.open_legs,
                "alerts": cycle.alerts,
            }
            for cycle in result.cycles[-5:]
        ],
        "limitation": (
            "Constant IV, synthetic spreads, no venue data, no live execution. "
            "This proves plumbing, not profitability."
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "synthetic_replay.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"synthetic replay: snapshots={len(snapshots)} fills={result.total_fills} "
        f"equity=${result.final_equity:,.2f} return={result.total_return:.2%} "
        f"max_dd={result.max_drawdown:.2%} fees=${result.total_fees:,.2f}"
    )
    print(f"saved: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
