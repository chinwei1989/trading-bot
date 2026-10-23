"""Draw the trading-bot architecture diagram.

Run:
    uv run python scripts/draw_architecture.py

Outputs:
    docs/architecture.png
    docs/architecture.svg
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs"

COLORS = {
    "source": ("#ECEFF1", "#546E7A"),
    "data": ("#E3F2FD", "#1565C0"),
    "research": ("#F3E5F5", "#6A1B9A"),
    "runtime": ("#E8F5E9", "#2E7D32"),
    "ops": ("#FFF3E0", "#EF6C00"),
    "safety": ("#FFEBEE", "#C62828"),
    "ink": "#1A1A1A",
    "muted": "#546E7A",
}


def box(
    ax,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    subtitle: str = "",
    kind: str = "data",
    fontsize: float = 9,
    title_size: float = 9.5,
) -> None:
    face, edge = COLORS[kind]
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.02,rounding_size=0.08",
        linewidth=1.3,
        edgecolor=edge,
        facecolor=face,
        zorder=2,
    )
    ax.add_patch(patch)
    text = title
    if subtitle:
        text += "\n" + subtitle
    ax.text(
        x + w / 2,
        y + h / 2,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        color=COLORS["ink"],
        linespacing=1.25,
        zorder=3,
    )
    ax.text(
        x + 0.08,
        y + h - 0.08,
        "",
        ha="left",
        va="top",
        fontsize=title_size,
    )


def arrow(
    ax,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    color: str = "#37474F",
    style: str = "-|>",
    lw: float = 1.3,
    ls: str = "-",
    rad: float = 0.0,
    label: str | None = None,
    label_offset: tuple[float, float] = (0.0, 0.12),
    fontsize: float = 8,
) -> None:
    arrow_patch = FancyArrowPatch(
        (x1, y1),
        (x2, y2),
        arrowstyle=style,
        mutation_scale=11,
        linewidth=lw,
        color=color,
        linestyle=ls,
        shrinkA=3,
        shrinkB=3,
        connectionstyle=f"arc3,rad={rad}",
        zorder=1,
    )
    ax.add_patch(arrow_patch)
    if label:
        ax.text(
            (x1 + x2) / 2 + label_offset[0],
            (y1 + y2) / 2 + label_offset[1],
            label,
            ha="center",
            va="center",
            fontsize=fontsize,
            color=color,
            bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=1.2),
            zorder=4,
        )


def main() -> int:
    fig, ax = plt.subplots(figsize=(16, 10))
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 10)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.text(
        0.4,
        9.72,
        "Crypto + US Equity Trading Bot — System Architecture",
        fontsize=18,
        fontweight="bold",
        color=COLORS["ink"],
    )
    ax.text(
        0.4,
        9.42,
        "Research and execution are separate. Research can never send orders; "
        "only the runtime path, through the risk engine, can.",
        fontsize=9.5,
        color=COLORS["muted"],
    )

    # ------------------------------------------------------------------ sources
    ax.text(0.4, 9.05, "1. External sources and venues", fontsize=11, fontweight="bold")
    sources = [
        ("Binance Vision / API", "crypto bars"),
        ("Alpaca", "US stocks / ETFs"),
        ("ccxt venues", "crypto execution"),
        ("FRED / SEC / GDELT", "macro, filings, news"),
        ("X / Reddit / news", "optional sentiment"),
    ]
    sx = [0.4, 3.5, 6.6, 9.7, 12.8]
    sw = 2.8
    sy, sh = 8.35, 0.62
    for (title, subtitle), x in zip(sources, sx, strict=True):
        box(ax, x, sy, sw, sh, title, subtitle, "source", fontsize=8.8)

    # --------------------------------------------------------------------- data
    ax.text(0.4, 7.82, "2. Data plane", fontsize=11, fontweight="bold")
    data = [
        ("Ingest adapters", "retry · cache · checksum"),
        ("Raw Parquet", "immutable + SHA256"),
        ("Normalized Parquet", "UTC · schema · dedupe"),
        ("DuckDB + quality", "PIT joins · audits"),
    ]
    dx = [0.4, 4.35, 8.3, 12.25]
    dw = 3.7
    dy, dh = 6.95, 0.65
    for (title, subtitle), x in zip(data, dx, strict=True):
        box(ax, x, dy, dw, dh, title, subtitle, "data", fontsize=8.8)

    for (_, _), x in zip(sources, sx, strict=True):
        arrow(ax, x + sw / 2, sy, x + sw / 2, dy + dh)
    for x in dx[:-1]:
        arrow(ax, x + dw, dy + dh / 2, dx[dx.index(x) + 1], dy + dh / 2)

    # ---------------------------------------------------------------- research panel
    rx, ry, rw, rh = 0.4, 3.5, 7.3, 3.0
    ax.add_patch(
        FancyBboxPatch(
            (rx, ry),
            rw,
            rh,
            boxstyle="round,pad=0.02,rounding_size=0.10",
            linewidth=1.2,
            edgecolor="#B39DDB",
            facecolor="#FAF7FD",
            zorder=0,
        )
    )
    ax.text(rx + 0.2, ry + 0.15, "3. Research and validation (offline)", fontsize=11,
            fontweight="bold", color=COLORS["research"][1])

    box(ax, 0.7, 5.50, 2.0, 0.60, "PIT feature store", "bars · vol · momentum", "research", fontsize=8.4)
    box(ax, 3.0, 5.50, 2.0, 0.60, "Strategies", "Trend · XSMOM", "research", fontsize=8.4)
    box(ax, 5.3, 5.50, 2.1, 0.60, "Portfolio + risk", "vol target · caps", "research", fontsize=8.4)
    box(ax, 0.7, 4.20, 3.0, 0.60, "Backtester", "next-open · costs", "research", fontsize=8.4)
    box(ax, 4.1, 4.20, 3.3, 0.60, "Validation", "walk-forward · DSR · PBO", "research", fontsize=8.4)

    arrow(ax, 2.7, 5.80, 3.0, 5.80, color="#6A1B9A")
    arrow(ax, 5.0, 5.80, 5.3, 5.80, color="#6A1B9A")
    arrow(ax, 5.6, 5.50, 3.7, 4.80, color="#6A1B9A", rad=-0.08)
    arrow(ax, 3.7, 4.50, 4.1, 4.50, color="#6A1B9A")

    # ----------------------------------------------------------------- runtime panel
    tx, ty, tw, th = 8.0, 3.5, 7.6, 3.0
    ax.add_patch(
        FancyBboxPatch(
            (tx, ty),
            tw,
            th,
            boxstyle="round,pad=0.02,rounding_size=0.10",
            linewidth=1.2,
            edgecolor="#A5D6A7",
            facecolor="#F5FBF5",
            zorder=0,
        )
    )
    ax.text(tx + 3.2, ty + 0.15, "4. Runtime and execution (daily)", fontsize=11,
            fontweight="bold", color=COLORS["runtime"][1])

    box(ax, 8.3, 5.50, 1.6, 0.60, "Scheduler", "once / loop", "runtime", fontsize=8.2)
    box(ax, 10.1, 5.50, 1.6, 0.60, "Signal", "completed bar", "runtime", fontsize=8.2)
    box(ax, 11.9, 5.50, 1.7, 0.60, "Risk engine", "limits + auto-kill", "runtime", fontsize=8.2)
    box(ax, 13.8, 5.50, 1.6, 0.60, "Order planner", "idempotent IDs", "runtime", fontsize=8.2)
    box(ax, 8.3, 4.20, 2.4, 0.60, "Broker factory", "Paper · Alpaca · ccxt", "runtime", fontsize=8.2)
    box(ax, 11.0, 4.20, 2.5, 0.60, "Journal + reconcile", "SQLite · drift check", "runtime", fontsize=8.2)

    arrow(ax, 9.9, 5.80, 10.1, 5.80, color="#2E7D32")
    arrow(ax, 11.7, 5.80, 11.9, 5.80, color="#2E7D32")
    arrow(ax, 13.6, 5.80, 13.8, 5.80, color="#2E7D32")
    arrow(ax, 14.6, 5.50, 10.7, 4.80, color="#2E7D32", rad=-0.10)
    arrow(ax, 10.7, 4.50, 11.0, 4.50, color="#2E7D32")

    # data -> research/runtime
    arrow(ax, 2.9, dy, 2.4, 6.10, color="#1565C0", rad=0.0)
    arrow(ax, 10.15, dy, 9.1, 6.10, color="#1565C0", rad=0.0)

    # validation gate
    arrow(ax, 7.45, 4.50, 8.25, 5.47, color="#C62828", style="-|>", lw=1.5, ls="--",
          label="GO / NO-GO", label_offset=(0.0, 0.18), fontsize=7.8)

    # --------------------------------------------------------------------- ops row
    ax.text(0.4, 2.95, "5. Operations and safety", fontsize=11, fontweight="bold")
    box(ax, 0.4, 1.75, 2.7, 0.72, "Kill / flatten", "emergency stop", "safety", fontsize=8.6)
    box(ax, 3.3, 1.75, 3.2, 0.72, "Live gate", "confirm + env + non-paper", "safety", fontsize=8.6)
    box(ax, 8.2, 1.75, 2.2, 0.72, "Heartbeat", "JSON status", "ops", fontsize=8.6)
    box(ax, 10.6, 1.75, 2.2, 0.72, "Alerts", "Telegram (optional)", "ops", fontsize=8.6)
    box(ax, 13.0, 1.75, 2.3, 0.72, "Status CLI", "positions · PnL", "ops", fontsize=8.6)

    arrow(ax, 12.2, 4.20, 9.3, 2.47, color="#EF6C00", rad=0.05, label="writes", fontsize=7.5)
    arrow(ax, 10.4, 2.11, 10.6, 2.11, color="#EF6C00")
    arrow(ax, 12.8, 2.11, 13.0, 2.11, color="#EF6C00")
    arrow(ax, 6.5, 2.11, 8.3, 4.20, color="#C62828", ls="--", lw=1.5,
          label="unlock", label_offset=(0.05, 0.15), fontsize=7.5)

    # legend
    ax.plot([0.4, 0.9], [1.05, 1.05], color="#37474F", lw=1.5)
    ax.text(0.98, 1.05, "data / control flow", fontsize=8, va="center", color=COLORS["muted"])
    ax.plot([3.2, 3.7], [1.05, 1.05], color="#C62828", lw=1.5, ls="--")
    ax.text(3.78, 1.05, "live gate / safety", fontsize=8, va="center", color=COLORS["muted"])
    ax.text(
        0.4,
        0.62,
        "Research is offline. Runtime consumes only frozen/validated configs. "
        "All orders pass through the risk engine; the live gate is independent of strategy logic.",
        fontsize=8,
        color=COLORS["muted"],
    )

    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / "architecture.png", dpi=180, bbox_inches="tight", facecolor="white")
    fig.savefig(OUT / "architecture.svg", bbox_inches="tight", facecolor="white")
    print(f"Wrote {OUT / 'architecture.png'}")
    print(f"Wrote {OUT / 'architecture.svg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
