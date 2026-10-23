"""Plot long-history paper replay vs backtest."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> tuple[list, list]:
    df = pd.read_csv(path, parse_dates=["timestamp"]).sort_values("timestamp")
    return df["timestamp"].tolist(), df["equity"].tolist()


def annotate(ax, metrics_path: Path, label: str) -> None:
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    m = payload.get("paper_replay", payload)
    ax.text(
        0.02,
        0.04,
        f"{label}\nCAGR {m['cagr']:.1%} · Sharpe {m['sharpe']:.2f} · MaxDD {m['max_dd']:.1%}",
        transform=ax.transAxes,
        fontsize=8,
        color="#37474F",
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.85),
    )


def main() -> int:
    fig, axes = plt.subplots(1, 2, figsize=(15, 5.5))

    cases = [
        (
            "12.1 years · BTC/LTC (Yahoo)",
            ROOT / "artifacts" / "long_history" / "paper_replay_trend_daily.csv",
            ROOT / "artifacts" / "long_history" / "backtest_trend_daily.csv",
            ROOT / "artifacts" / "long_history" / "paper_replay_trend_metrics.json",
        ),
        (
            "9.2 years · 8 crypto assets (Binance max history)",
            ROOT / "artifacts" / "max_history" / "paper_replay_trend_daily.csv",
            ROOT / "artifacts" / "max_history" / "backtest_trend_daily.csv",
            ROOT / "artifacts" / "max_history" / "paper_replay_trend_metrics.json",
        ),
    ]

    for ax, (title, replay_path, backtest_path, metrics_path) in zip(axes, cases, strict=True):
        rt, re = load(replay_path)
        bt, be = load(backtest_path)
        ax.plot(bt, be, color="#9E9E9E", lw=1.2, label="vectorized backtest")
        ax.plot(rt, re, color="#1565C0", lw=1.5, label="paper-broker replay")
        ax.set_title(title, fontsize=11, fontweight="bold")
        ax.set_ylabel("Equity (start = 10,000)")
        ax.grid(alpha=0.25)
        ax.legend(loc="upper left", fontsize=8)
        annotate(ax, metrics_path, "paper replay")

    fig.suptitle(
        "Long-history trend: paper-broker replay vs vectorized backtest",
        fontsize=14,
        fontweight="bold",
    )
    fig.text(
        0.5,
        0.01,
        "Next-open execution, 10 bps commission + 5 bps slippage per side, weekly rebalance. "
        "Yahoo data is research-grade, not exchange-grade.",
        ha="center",
        fontsize=8,
        color="#546E7A",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.94))
    out = ROOT / "docs" / "long_history.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=160, bbox_inches="tight", facecolor="white")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
