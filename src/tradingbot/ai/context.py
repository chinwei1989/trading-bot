"""Point-in-time market context handed to an AI decision provider.

The context contains only information available at or before the decision
timestamp. No future bars, revised closes, or post-decision sentiment are used.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from tradingbot.config import AgentPolicyConfig


def _pct_change(values: np.ndarray, periods: int) -> float | None:
    if len(values) <= periods or values[-periods - 1] <= 0:
        return None
    return float(values[-1] / values[-periods - 1] - 1.0)


def _annualized_vol(values: np.ndarray, window: int, periods_per_year: int = 365) -> float | None:
    if len(values) < 3:
        return None
    window_values = values[-(window + 1) :]
    rets = np.diff(np.log(window_values))
    rets = rets[np.isfinite(rets)]
    if len(rets) < 2:
        return None
    return float(np.std(rets, ddof=1) * math.sqrt(periods_per_year))


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _asset_features(group: pl.DataFrame, periods_per_year: int) -> dict[str, Any] | None:
    group = group.sort("timestamp")
    close = group["close"].to_numpy().astype(float)
    if len(close) < 3 or close[-1] <= 0:
        return None
    last = float(close[-1])
    sma = {
        window: float(np.mean(close[-min(window, len(close)) :]))
        for window in (20, 50, 200)
    }
    vol_20 = _annualized_vol(close, 20, periods_per_year)
    vol_60 = _annualized_vol(close, 60, periods_per_year)
    high_60 = float(np.max(close[-min(60, len(close)) :]))
    volume = group["volume"].to_numpy().astype(float)
    volume_z = None
    if len(volume) >= 21:
        recent = volume[-21:-1]
        std = float(np.std(recent, ddof=1))
        if std > 1e-12:
            volume_z = float((volume[-1] - float(np.mean(recent))) / std)

    return {
        "close": last,
        "return_1d": _pct_change(close, 1),
        "return_5d": _pct_change(close, 5),
        "return_20d": _pct_change(close, 20),
        "return_60d": _pct_change(close, 60),
        "return_120d": _pct_change(close, 120),
        "sma_20": sma[20],
        "sma_50": sma[50],
        "sma_200": sma[200],
        "px_vs_sma_20": last / sma[20] - 1.0 if sma[20] else None,
        "px_vs_sma_50": last / sma[50] - 1.0 if sma[50] else None,
        "px_vs_sma_200": last / sma[200] - 1.0 if sma[200] else None,
        "vol_20d": vol_20,
        "vol_60d": vol_60,
        "drawdown_60d": last / high_60 - 1.0 if high_60 else None,
        "volume_z_20d": volume_z,
        "trend_up": bool(last > sma[200]),
        "trend_up_50": bool(last > sma[50]),
        "history_days": len(close),
    }


def _macro_snapshot(root: Path, as_of: datetime) -> dict[str, Any]:
    path = root / "data" / "normalized" / "macro.parquet"
    if not path.exists():
        return {"available": False}
    try:
        macro = pl.read_parquet(path)
    except Exception:
        return {"available": False}
    required = {"timestamp", "series", "value"}
    if not required.issubset(macro.columns):
        return {"available": False}
    frame = macro.filter(pl.col("timestamp") <= as_of).sort("timestamp")
    series: dict[str, Any] = {}
    for sid, group in frame.group_by("series", maintain_order=True):
        name = str(sid[0])
        values = group.sort("timestamp")["value"].to_numpy().astype(float)
        if len(values) == 0:
            continue
        recent = values[-252:]
        std = float(np.std(recent, ddof=1)) if len(recent) > 1 else 0.0
        z = float((values[-1] - float(np.mean(recent))) / std) if std > 1e-12 else 0.0
        change_20 = (
            float(values[-1] - values[-21]) if len(values) > 21 else None
        )
        series[name] = {
            "last": float(values[-1]),
            "z_1y": z,
            "change_20": change_20,
        }

    risk_score = 0.0
    if "VIXCLS" in series:
        risk_score += max(-1.0, min(1.0, float(series["VIXCLS"]["z_1y"]))) * 0.5
    if "BAMLH0A0HYM2" in series:
        risk_score += max(-1.0, min(1.0, float(series["BAMLH0A0HYM2"]["z_1y"]))) * 0.3
    if "T10Y2Y" in series:
        risk_score -= 0.2 if float(series["T10Y2Y"]["last"]) < 0 else 0.0
    return {
        "available": True,
        "series": series,
        "risk_score": max(-1.0, min(1.0, risk_score)),
        "interpretation": (
            "risk_off" if risk_score > 0.5 else "risk_on" if risk_score < -0.2 else "neutral"
        ),
    }


def _sentiment_snapshot(root: Path, as_of: datetime) -> dict[str, Any]:
    path = root / "data" / "normalized" / "sentiment.parquet"
    if not path.exists():
        return {"available": False}
    try:
        frame = pl.read_parquet(path)
    except Exception:
        return {"available": False}
    required = {"timestamp", "asset", "score"}
    if not required.issubset(frame.columns):
        return {"available": False}
    cutoff = as_of.timestamp() - 7 * 86_400
    recent = frame.filter(pl.col("timestamp") <= as_of)
    if recent.is_empty():
        return {"available": False}
    recent = recent.with_columns(pl.col("timestamp").dt.epoch("s").alias("_epoch")).filter(
        pl.col("_epoch") >= cutoff
    )
    if recent.is_empty():
        return {"available": False}
    grouped = recent.group_by("asset").agg(
        pl.col("score").mean().alias("mean"),
        pl.col("score").count().alias("count"),
    )
    return {
        "available": True,
        "window_days": 7,
        "assets": {
            str(row["asset"]): {
                "mean": float(row["mean"]),
                "count": int(row["count"]),
            }
            for row in grouped.iter_rows(named=True)
        },
    }


def build_context(
    bars: pl.DataFrame,
    *,
    cash: float,
    equity: float,
    positions: dict[str, float],
    policy: AgentPolicyConfig,
    root: Path,
    include_macro: bool = True,
    include_sentiment: bool = True,
    periods_per_year: int = 365,
) -> dict[str, Any]:
    """Build a JSON-serializable, point-in-time market snapshot."""
    if bars.is_empty():
        raise ValueError("cannot build context from empty bars")
    bars = bars.sort("timestamp")
    as_of = bars["timestamp"].max()
    if not isinstance(as_of, datetime):
        as_of = datetime.now(UTC)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)
    as_of = as_of.astimezone(UTC)

    assets: dict[str, Any] = {}
    prices: dict[str, float] = {}
    for (asset,), group in bars.group_by(["asset"], maintain_order=True):
        features = _asset_features(group, periods_per_year)
        if features is None:
            continue
        assets[str(asset)] = features
        prices[str(asset)] = float(features["close"])
    if not assets:
        raise ValueError("no assets with sufficient price history")

    universe = sorted(assets)
    current_weights: dict[str, float] = {}
    if equity > 0:
        for asset in universe:
            qty = float(positions.get(asset, 0.0))
            current_weights[asset] = qty * prices[asset] / equity

    breadth = sum(1 for a in universe if assets[a].get("trend_up")) / len(universe)
    data_age_days = max(0, (datetime.now(UTC) - as_of).days)
    context: dict[str, Any] = {
        "as_of": as_of.isoformat(),
        "universe": universe,
        "assets": assets,
        "portfolio": {
            "cash": float(cash),
            "equity": float(equity),
            "positions": {a: float(q) for a, q in positions.items() if abs(q) > 1e-12},
            "current_weights": {a: float(w) for a, w in current_weights.items()},
        },
        "market": {
            "breadth_above_sma200": breadth,
            "assets_above_sma200": sum(1 for a in universe if assets[a].get("trend_up")),
            "assets_total": len(universe),
            "data_age_days": data_age_days,
        },
        "constraints": policy.model_dump(),
        "instructions": {
            "objective": (
                "Choose long/flat exposure for each asset, or provide target weights. "
                "Respect the constraints and avoid unnecessary turnover."
            ),
            "risk_policy": (
                "This is a paper portfolio. The deterministic policy layer may clip, "
                "scale, or reject the decision."
            ),
        },
    }
    if include_macro:
        context["macro"] = _macro_snapshot(root, as_of)
    if include_sentiment:
        context["sentiment"] = _sentiment_snapshot(root, as_of)
    return context
