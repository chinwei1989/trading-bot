"""Toy trend backtest on downloaded Binance daily bars.

This is a smoke test, not a validated strategy. It demonstrates:
  - loading normalized Parquet,
  - a 200-day trend signal,
  - next-bar execution (no same-bar close fills),
  - transaction costs and turnover,
  - basic metrics and a chart.

Run:
    uv run python scripts/smoke_trend.py
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, cast

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl


def stats(returns: np.ndarray, periods_per_year: int = 365) -> dict[str, float]:
    r = returns[np.isfinite(returns)]
    if len(r) < 2:
        return {}
    equity = np.cumprod(1.0 + r)
    years = len(r) / periods_per_year
    cagr = equity[-1] ** (1.0 / years) - 1.0 if years > 0 else np.nan
    vol = r.std(ddof=1) * np.sqrt(periods_per_year)
    sharpe = (r.mean() / r.std(ddof=1) * np.sqrt(periods_per_year)) if r.std(ddof=1) > 0 else np.nan
    peak = np.maximum.accumulate(equity)
    drawdown = equity / peak - 1.0
    return {
        "total_return": equity[-1] - 1.0,
        "cagr": cagr,
        "vol": vol,
        "sharpe": sharpe,
        "max_dd": drawdown.min(),
        "n_days": float(len(r)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="data/normalized/spot_BTCUSDT_1d.parquet",
        help="normalized Parquet from download_binance_klines.py",
    )
    parser.add_argument("--lookback", type=int, default=200)
    parser.add_argument("--cost-bps", type=float, default=10.0, help="per side")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    path = Path(args.input)
    if not path.is_absolute():
        path = root / path
    if not path.exists():
        raise SystemExit(f"missing {path}; run scripts/download_binance_klines.py first")

    df = (
        pl.read_parquet(path)
        .sort("timestamp")
        .with_columns(
            # Open-to-open return: decide at close t, enter at open t+1,
            # earn from open t+1 to open t+2. No same-close fills.
            ret=(pl.col("open").shift(-1) / pl.col("open") - 1.0),
            sma=pl.col("close").rolling_mean(args.lookback),
        )
        .with_columns(
            signal=(pl.col("close") > pl.col("sma")).cast(pl.Float64),
        )
        .with_columns(
            # Trade on the next bar, never on the close that generated the signal.
            position=pl.col("signal").shift(1).fill_null(0.0),
        )
        .with_columns(
            turnover=(pl.col("position") - pl.col("position").shift(1)).abs().fill_null(0.0),
        )
        .with_columns(
            strat_ret=pl.col("position") * pl.col("ret")
            - pl.col("turnover") * (args.cost_bps / 10_000.0),
        )
        .drop_nulls(["ret", "sma"])
    )

    strat = stats(df["strat_ret"].to_numpy())
    bh = stats(df["ret"].to_numpy())

    print(f"File: {path}")
    print(f"Rows: {df.height:,} | {df['timestamp'].min()!s} -> {df['timestamp'].max()!s}")
    print(f"Trend: close > {args.lookback}d SMA | cost {args.cost_bps:.1f} bps/side")
    print()
    print(f"{'metric':<16}{'trend':>12}{'buy & hold':>14}")
    for key in ["total_return", "cagr", "vol", "sharpe", "max_dd"]:
        print(f"{key:<16}{strat.get(key, float('nan')):>12.3f}{bh.get(key, float('nan')):>14.3f}")
    exposure = float(cast(Any, df["position"].mean()))
    turnover = float(cast(Any, df["turnover"].sum())) / (df.height / 365)
    print(f"{'exposure':<16}{exposure:>12.3f}{1.0:>14.3f}")
    print(f"{'turnover/yr':<16}{turnover:>12.2f}{0.0:>14.2f}")

    # Chart
    eq_trend = (1.0 + df["strat_ret"]).cum_prod()
    eq_bh = (1.0 + df["ret"]).cum_prod()
    dd = eq_trend / eq_trend.cum_max() - 1.0

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )
    ax1.plot(df["timestamp"], eq_bh, label="Buy & hold", color="#888888", lw=1.2)
    ax1.plot(df["timestamp"], eq_trend, label=f"{args.lookback}d trend", color="#1f77b4", lw=1.6)
    ax1.set_ylabel("Equity (start = 1)")
    ax1.set_title("Smoke test: BTC daily trend (next-bar fills, costs included)")
    ax1.legend()
    ax1.grid(alpha=0.3)
    ax2.fill_between(df["timestamp"], dd, 0, color="#d62728", alpha=0.4)
    ax2.set_ylabel("Drawdown")
    ax2.grid(alpha=0.3)
    fig.tight_layout()

    out = root / "artifacts" / "smoke_trend.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=140)
    print(f"\nChart: {out}")

    print("\nNOTE: this is a toy. It has no walk-forward, no DSR/PBO, no funding,")
    print("and no survivorship handling. Do not trade it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
