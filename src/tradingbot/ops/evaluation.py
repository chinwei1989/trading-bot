"""Live/paper evaluation: TCA, live-vs-backtest tracking, drift, and alerts."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import polars as pl

from tradingbot.config import AppConfig
from tradingbot.data.store import load_bars
from tradingbot.execution.orders import latest_weights
from tradingbot.ops.heartbeat import read_heartbeat
from tradingbot.ops.performance import load_performance
from tradingbot.portfolio.risk import enforce_limits
from tradingbot.strategies import build_strategy


def _resolve(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def _latest_prices(bars: pl.DataFrame) -> dict[str, float]:
    last = bars.sort("timestamp").group_by("asset").tail(1)
    return {r["asset"]: float(r["close"]) for r in last.iter_rows(named=True)}


def _paper_snapshot(config: AppConfig, root: Path) -> tuple[float, dict[str, float]]:
    path = _resolve(root, config.broker.state_path)
    if not path.exists():
        return 0.0, {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0.0, {}
    cash = float(payload.get("cash", 0.0))
    positions = {
        asset: float(pos.get("qty", 0.0))
        for asset, pos in payload.get("positions", {}).items()
    }
    return cash, positions


def load_journal(path: str | Path) -> pl.DataFrame:
    p = Path(path)
    if not p.exists():
        return pl.DataFrame()
    conn = sqlite3.connect(p)
    try:
        raw = pd.read_sql_query("SELECT * FROM orders", conn)
    except Exception:
        return pl.DataFrame()
    finally:
        conn.close()
    if raw.empty:
        return pl.DataFrame()
    df = pl.from_pandas(raw)
    if "reference_price" not in df.columns:
        df = df.with_columns(pl.lit(None).alias("reference_price"))
    if "ts" in df.columns and df["ts"].dtype == pl.Utf8:
        df = df.with_columns(
            pl.col("ts").str.to_datetime(time_zone="UTC", strict=False)
        )
    return df


def load_backtest_daily(config: AppConfig, strategy: str, root: Path) -> pl.DataFrame:
    path = _resolve(root, config.backtest.output_dir) / f"backtest_{strategy}_daily.csv"
    if not path.exists():
        return pl.DataFrame()
    df = pl.read_csv(path, try_parse_dates=True).sort("timestamp")
    return df.select(["timestamp", "equity"]).with_columns(
        pl.col("timestamp").cast(pl.Datetime("us")).dt.replace_time_zone("UTC")
    )


def compute_tca(
    journal: pl.DataFrame,
    bars: pl.DataFrame,
) -> dict[str, float]:
    if journal.is_empty() or "avg_price" not in journal.columns:
        return {"fills": 0.0, "weighted_slip_bps": 0.0, "median_slip_bps": 0.0,
                "p95_abs_slip_bps": 0.0, "notional": 0.0}
    fills = journal.filter(
        (pl.col("status").cast(pl.Utf8).str.to_lowercase() == "filled")
        & pl.col("avg_price").is_not_null()
    )
    if fills.is_empty():
        return {"fills": 0.0, "weighted_slip_bps": 0.0, "median_slip_bps": 0.0,
                "p95_abs_slip_bps": 0.0, "notional": 0.0}

    slips: list[float] = []
    notionals: list[float] = []
    for row in fills.iter_rows(named=True):
        ref = row.get("reference_price")
        if ref is None or float(ref) <= 0:
            # Older journal rows predate reference-price capture; do not
            # fabricate a benchmark from a later revised close.
            continue
        avg = float(row["avg_price"])
        sign = 1.0 if str(row["side"]).lower() == "buy" else -1.0
        slips.append(sign * (avg - float(ref)) / float(ref) * 10_000.0)
        notionals.append(abs(float(row.get("filled_qty") or 0.0) * avg))
    if not slips:
        return {"fills": 0.0, "weighted_slip_bps": 0.0, "median_slip_bps": 0.0,
                "p95_abs_slip_bps": 0.0, "notional": 0.0}
    s = np.asarray(slips)
    n = np.asarray(notionals)
    weight = n / n.sum() if n.sum() > 0 else np.ones_like(n) / len(n)
    return {
        "fills": float(len(s)),
        "weighted_slip_bps": float(np.sum(s * weight)),
        "median_slip_bps": float(np.median(s)),
        "p95_abs_slip_bps": float(np.quantile(np.abs(s), 0.95)),
        "notional": float(n.sum()),
    }


def signal_drift(
    config: AppConfig,
    bars: pl.DataFrame,
    cash: float,
    positions: dict[str, float],
    prices: dict[str, float],
) -> dict[str, Any]:
    strategy = build_strategy(config.strategy, config.backtest.periods_per_year)
    target = enforce_limits(strategy.generate_weights(bars).weights, config.risk)
    if target.is_empty():
        return {"drift": None, "target_gross": 0.0, "current_gross": 0.0}
    latest = latest_weights(target)
    target_map = {r["asset"]: float(r["weight"]) for r in latest.iter_rows(named=True)}
    equity = cash + sum(qty * prices.get(a, 0.0) for a, qty in positions.items())
    if equity <= 0:
        return {"drift": None, "target_gross": 0.0, "current_gross": 0.0}
    current_map = {
        a: qty * prices.get(a, 0.0) / equity for a, qty in positions.items()
    }
    assets = sorted(set(target_map) | set(current_map))
    drift = 0.5 * sum(abs(current_map.get(a, 0.0) - target_map.get(a, 0.0)) for a in assets)
    return {
        "drift": float(drift),
        "target_gross": float(sum(abs(v) for v in target_map.values())),
        "current_gross": float(sum(abs(v) for v in current_map.values())),
    }


def live_vs_backtest(
    performance: pl.DataFrame,
    backtest: pl.DataFrame,
    periods_per_year: int,
) -> dict[str, float]:
    if performance.is_empty() or backtest.is_empty():
        return {"observations": 0.0}
    perf = (
        performance.select(["timestamp", "equity"])
        .with_columns(pl.col("timestamp").dt.date().alias("date"))
        .group_by("date")
        .agg(pl.col("equity").last())
        .sort("date")
    )
    bt = (
        backtest.select(["timestamp", "equity"])
        .with_columns(pl.col("timestamp").dt.date().alias("date"))
        .group_by("date")
        .agg(pl.col("equity").last())
        .sort("date")
    )
    joined = perf.join(bt, on="date", suffix="_bt").drop_nulls().sort("date")
    if joined.height < 3:
        return {"observations": float(joined.height)}
    p = np.asarray(joined["equity"].to_numpy(), dtype=float)
    b = np.asarray(joined["equity_bt"].to_numpy(), dtype=float)
    p = p / p[0]
    b = b / b[0]
    pr = np.diff(p) / p[:-1]
    br = np.diff(b) / b[:-1]
    diff = pr - br
    corr = float(np.corrcoef(pr, br)[0, 1]) if pr.std() > 0 and br.std() > 0 else 0.0
    beta = float(np.cov(pr, br)[0, 1] / np.var(br)) if br.var() > 0 else 0.0
    return {
        "observations": float(joined.height),
        "tracking_difference": float(p[-1] / b[-1] - 1.0),
        "tracking_error": float(diff.std(ddof=1) * np.sqrt(periods_per_year)),
        "correlation": corr,
        "beta": beta,
    }


def rolling_metrics(performance: pl.DataFrame, periods_per_year: int) -> dict[str, Any]:
    if performance.is_empty() or performance.height < 2:
        return {"windows": {}}
    eq = np.asarray(performance.sort("timestamp")["equity"].to_numpy(), dtype=float)
    ret = np.diff(eq) / eq[:-1]
    out: dict[str, Any] = {"current_drawdown": 0.0, "windows": {}}
    peak = np.maximum.accumulate(eq)
    out["current_drawdown"] = float(eq[-1] / peak[-1] - 1.0)
    for window in (20, 60, 120):
        n = min(window, len(ret))
        if n < 5:
            continue
        r = ret[-n:]
        std = float(r.std(ddof=1))
        sharpe = float(r.mean() / std * np.sqrt(periods_per_year)) if std > 0 else 0.0
        sub = eq[-(n + 1):]
        sub_peak = np.maximum.accumulate(sub)
        max_dd = float((sub / sub_peak - 1.0).min())
        out["windows"][str(window)] = {"sharpe": sharpe, "max_dd": max_dd}
    return out


def order_health(journal: pl.DataFrame, days: int = 7) -> dict[str, float]:
    if journal.is_empty() or "ts" not in journal.columns:
        return {"total": 0.0, "filled": 0.0, "rejected": 0.0, "reject_rate": 0.0}
    ts = journal["ts"]
    if ts.dtype == pl.Utf8:
        journal = journal.with_columns(
            pl.col("ts").str.to_datetime(time_zone="UTC", strict=False)
        )
    cutoff = datetime.now(UTC) - timedelta(days=days)
    recent = journal.filter(pl.col("ts") >= cutoff)
    if recent.is_empty():
        return {"total": 0.0, "filled": 0.0, "rejected": 0.0, "reject_rate": 0.0}
    status = recent["status"].cast(pl.Utf8).str.to_lowercase()
    total = recent.height
    filled = int((status == "filled").sum())
    rejected = int((status == "rejected").sum())
    return {
        "total": float(total),
        "filled": float(filled),
        "rejected": float(rejected),
        "reject_rate": rejected / total if total else 0.0,
    }


def build_report(
    config: AppConfig,
    strategy: str,
    root: Path | None = None,
) -> dict[str, Any]:
    root = root or Path.cwd()
    config = config.model_copy(deep=True)
    config.strategy.name = strategy  # type: ignore[assignment]
    bars_path = _resolve(root, config.data.bars_path)
    if not bars_path.exists():
        raise FileNotFoundError(f"missing bars: {bars_path}")
    bars = load_bars(bars_path)
    prices = _latest_prices(bars)
    perf = load_performance(_resolve(root, config.broker.performance_path))
    bt = load_backtest_daily(config, strategy, root)
    journal = load_journal(_resolve(root, config.broker.journal_path))
    cash, positions = _paper_snapshot(config, root)
    heartbeat = read_heartbeat(_resolve(root, config.broker.heartbeat_path))
    if not positions and heartbeat:
        cash = float(heartbeat.get("cash") or 0.0)
        positions = {
            asset: float(qty)
            for asset, qty in (heartbeat.get("positions") or {}).items()
        }
    equity = cash + sum(qty * prices.get(a, 0.0) for a, qty in positions.items())

    bt_metrics: dict[str, Any] = {}
    bt_metrics_path = _resolve(root, config.backtest.output_dir) / f"backtest_{strategy}_metrics.json"
    if bt_metrics_path.exists():
        bt_metrics = json.loads(bt_metrics_path.read_text(encoding="utf-8"))

    latest_bar = cast(datetime, bars["timestamp"].max())
    data_age = (datetime.now(UTC).date() - latest_bar.date()).days
    hb_age = None
    if heartbeat and heartbeat.get("timestamp"):
        try:
            hb_age = (
                datetime.now(UTC) - datetime.fromisoformat(str(heartbeat["timestamp"]))
            ).total_seconds() / 86400
        except ValueError:
            hb_age = None

    tca = compute_tca(journal, bars)
    drift = signal_drift(config, bars, cash, positions, prices)
    tracking = live_vs_backtest(perf, bt, config.backtest.periods_per_year)
    rolling = rolling_metrics(perf, config.backtest.periods_per_year)
    health = order_health(journal)

    alerts: list[str] = []
    if data_age > 2:
        alerts.append(f"data stale: {data_age} days")
    if hb_age is None:
        alerts.append("heartbeat missing or unreadable")
    elif hb_age > 2:
        alerts.append(f"heartbeat stale: {hb_age:.1f} days")
    if health["reject_rate"] > 0.05 and health["total"] > 0:
        alerts.append(f"order reject rate {health['reject_rate']:.1%}")
    expected_slip = max(5.0, config.backtest.cost_bps + config.backtest.slippage_bps)
    if tca["fills"] > 0 and abs(tca["weighted_slip_bps"]) > 2 * expected_slip:
        alerts.append(f"TCA slippage {tca['weighted_slip_bps']:.1f} bps > 2x expected")
    if drift.get("drift") is not None and drift["drift"] > 0.25:
        alerts.append(f"signal drift {drift['drift']:.1%} > 25%")
    w60 = rolling.get("windows", {}).get("60")
    if w60 and w60["sharpe"] < 0:
        alerts.append(f"rolling 60d Sharpe {w60['sharpe']:.2f} < 0")
    if tracking.get("tracking_difference") is not None and abs(tracking["tracking_difference"]) > 0.05:
        alerts.append(f"live-vs-backtest gap {tracking['tracking_difference']:.1%} > 5%")
    if bt_metrics.get("max_dd"):
        limit = abs(float(bt_metrics["max_dd"])) * 1.5
        if rolling.get("current_drawdown", 0.0) < -limit:
            alerts.append(f"drawdown {rolling['current_drawdown']:.1%} > 1.5x backtest")

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "strategy": strategy,
        "config": {
            "broker": config.broker.name,
            "paper": config.broker.paper,
            "data_source": config.data.source,
        },
        "data": {
            "latest_bar": str(latest_bar),
            "age_days": data_age,
            "rows": bars.height,
            "assets": bars["asset"].n_unique(),
        },
        "account": {
            "equity": equity,
            "cash": cash,
            "positions": positions,
        },
        "heartbeat": heartbeat,
        "backtest_metrics": bt_metrics,
        "live_vs_backtest": tracking,
        "rolling": rolling,
        "tca": tca,
        "order_health": health,
        "signal_drift": drift,
        "alerts": alerts,
    }


def _md_table(rows: list[tuple[str, Any]]) -> str:
    lines = ["| metric | value |", "|---|---:|"]
    for key, value in rows:
        if isinstance(value, float):
            lines.append(f"| {key} | {value:,.4f} |")
        else:
            lines.append(f"| {key} | {value} |")
    return "\n".join(lines)


def write_report(
    report: dict[str, Any],
    root: Path | None = None,
) -> tuple[Path, Path]:
    root = root or Path.cwd()
    out_dir = root / "artifacts" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    strategy = str(report["strategy"])
    json_path = out_dir / f"evaluation_{strategy}.json"
    md_path = out_dir / f"evaluation_{strategy}.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    lines = [
        f"# Daily Evaluation — {strategy}",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## Account and data",
        "",
        _md_table(
            [
                ("equity", float(report["account"]["equity"])),
                ("cash", float(report["account"]["cash"])),
                ("positions", len(report["account"]["positions"])),
                ("latest bar", report["data"]["latest_bar"]),
                ("data age (days)", report["data"]["age_days"]),
            ]
        ),
        "",
        "## Live vs backtest",
        "",
        _md_table(list(report["live_vs_backtest"].items())),
        "",
        "## Rolling metrics",
        "",
    ]
    for window, metrics in report["rolling"].get("windows", {}).items():
        lines.append(f"- **{window}d**: " + ", ".join(f"{k}={v:.3f}" for k, v in metrics.items()))
    lines += [
        "",
        "## TCA / slippage",
        "",
        _md_table(list(report["tca"].items())),
        "",
        "## Order health (7d)",
        "",
        _md_table(list(report["order_health"].items())),
        "",
        "## Signal drift",
        "",
        _md_table(list(report["signal_drift"].items())),
        "",
        "## Alerts",
        "",
    ]
    if report["alerts"]:
        lines += [f"- {a}" for a in report["alerts"]]
    else:
        lines.append("- none")
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, json_path


def print_summary(report: dict[str, Any]) -> None:
    print(f"Evaluation: {report['strategy']}")
    print(
        f"  equity={report['account']['equity']:,.2f} "
        f"cash={report['account']['cash']:,.2f} "
        f"data_age={report['data']['age_days']}d"
    )
    print(f"  TCA fills={report['tca']['fills']:.0f} "
          f"weighted_slip={report['tca']['weighted_slip_bps']:.2f}bps")
    print(f"  signal_drift={report['signal_drift'].get('drift')}")
    print(f"  alerts={report['alerts'] or ['none']}")
