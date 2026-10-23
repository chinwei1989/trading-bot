"""Feature engineering and weight construction helpers."""

from __future__ import annotations

import math

import numpy as np
import polars as pl

from tradingbot.data.store import asset_columns


def returns(close: pl.DataFrame) -> pl.DataFrame:
    """Simple close-to-close returns for a timestamp x asset frame."""
    cols = asset_columns(close)
    return close.with_columns([pl.col(c).pct_change().alias(c) for c in cols])


def rolling_vol(returns_wide: pl.DataFrame, window: int, periods_per_year: int) -> pl.DataFrame:
    cols = asset_columns(returns_wide)
    return returns_wide.with_columns(
        [
            (pl.col(c).rolling_std(window) * math.sqrt(periods_per_year)).alias(c)
            for c in cols
        ]
    )


def sma(close: pl.DataFrame, window: int) -> pl.DataFrame:
    cols = asset_columns(close)
    return close.with_columns([pl.col(c).rolling_mean(window).alias(c) for c in cols])


def momentum(close: pl.DataFrame, lookback: int, skip: int = 0) -> pl.DataFrame:
    """Return from t-lookback-skip to t-skip."""
    cols = asset_columns(close)
    return close.with_columns(
        [(pl.col(c).shift(skip) / pl.col(c).shift(lookback + skip) - 1.0).alias(c) for c in cols]
    )


def atr(bars: pl.DataFrame, window: int) -> pl.DataFrame:
    """Average true range in long format."""
    frame = bars.sort(["asset", "timestamp"]).with_columns(
        pl.col("close").shift(1).over("asset").alias("_prev_close")
    )
    frame = frame.with_columns(
        pl.max_horizontal(
            pl.col("high") - pl.col("low"),
            (pl.col("high") - pl.col("_prev_close")).abs(),
            (pl.col("low") - pl.col("_prev_close")).abs(),
        ).alias("_tr")
    )
    frame = frame.with_columns(
        pl.col("_tr").rolling_mean(window).over("asset").alias("atr")
    )
    return frame.select(["timestamp", "asset", "atr"])


def rsi(close: pl.DataFrame, window: int) -> pl.DataFrame:
    """Simple RSI (rolling-average gains/losses)."""
    cols = asset_columns(close)
    out = close
    for col in cols:
        delta = pl.col(col).diff()
        gain = pl.when(delta > 0).then(delta).otherwise(0.0)
        loss = pl.when(delta < 0).then(-delta).otherwise(0.0)
        avg_gain = gain.rolling_mean(window).alias(f"{col}__gain")
        avg_loss = loss.rolling_mean(window).alias(f"{col}__loss")
        out = out.with_columns(avg_gain, avg_loss)
        out = out.with_columns(
            (
                100.0
                - 100.0
                / (1.0 + pl.col(f"{col}__gain") / pl.col(f"{col}__loss").clip(1e-12))
            ).alias(col)
        )
    return out.select(["timestamp", *cols])


def zscore(close: pl.DataFrame, window: int) -> pl.DataFrame:
    cols = asset_columns(close)
    out = close
    for col in cols:
        mean = pl.col(col).rolling_mean(window)
        std = pl.col(col).rolling_std(window)
        out = out.with_columns(((pl.col(col) - mean) / std.clip(1e-12)).alias(col))
    return out.select(["timestamp", *cols])


def rebalance_dates(dates: pl.Series, freq: str = "W") -> list:
    """Last available date per day/week/month."""
    frame = pl.DataFrame({"timestamp": dates}).unique().sort("timestamp")
    if freq == "D":
        return frame["timestamp"].to_list()
    if freq == "W":
        keys = [pl.col("timestamp").dt.year().alias("y"), pl.col("timestamp").dt.week().alias("w")]
    elif freq == "M":
        keys = [pl.col("timestamp").dt.year().alias("y"), pl.col("timestamp").dt.month().alias("m")]
    else:
        raise ValueError(f"unsupported rebalance frequency: {freq}")
    return (
        frame.with_columns(keys)
        .group_by(["y", "w"] if freq == "W" else ["y", "m"])
        .agg(pl.col("timestamp").max())
        .sort("timestamp")["timestamp"]
        .to_list()
    )


def scale_to_target_vol(
    weights: pl.DataFrame,
    returns_wide: pl.DataFrame,
    target_vol: float,
    window: int,
    periods_per_year: int,
    max_scale: float = 2.0,
) -> pl.DataFrame:
    """Scale each rebalance date's weights to an ex-ante portfolio vol target.

    Uses only returns up to and including the decision timestamp.
    """
    if weights.is_empty():
        return weights
    assets = [c for c in asset_columns(returns_wide) if c in weights["asset"].unique().to_list()]
    if not assets:
        return weights

    rows: list[dict[str, object]] = []
    for (ts,), group in weights.group_by(["timestamp"], maintain_order=True):
        w = np.array([float(group.filter(pl.col("asset") == a)["weight"].sum()) for a in assets])
        hist = (
            returns_wide.filter(pl.col("timestamp") <= ts)
            .tail(window)
            .select(assets)
            .to_numpy()
        )
        hist = np.asarray(hist, dtype=float)
        hist = hist[np.isfinite(hist).all(axis=1)]
        scale = 1.0
        if hist.shape[0] >= max(10, len(assets) + 2):
            cov = np.cov(hist, rowvar=False)
            cov = np.atleast_2d(cov)
            port_var = float(w @ cov @ w)
            if np.isfinite(port_var) and port_var > 0:
                vol = math.sqrt(port_var * periods_per_year)
                if vol > 1e-8:
                    scale = min(max_scale, max(0.0, target_vol / vol))
        for row in group.iter_rows(named=True):
            rows.append(
                {
                    "timestamp": ts,
                    "asset": row["asset"],
                    "weight": float(row["weight"]) * scale,
                }
            )
    return pl.DataFrame(rows).sort(["timestamp", "asset"])


def cap_weights(
    weights: pl.DataFrame,
    max_asset_weight: float,
    max_gross: float,
) -> pl.DataFrame:
    """Clip per-asset weights and scale gross exposure."""
    if weights.is_empty():
        return weights
    out = weights.with_columns(
        pl.col("weight").clip(-max_asset_weight, max_asset_weight)
    )
    out = out.with_columns(pl.col("weight").abs().alias("_abs"))
    gross = out.group_by("timestamp").agg(pl.col("_abs").sum().alias("_gross"))
    out = out.join(gross, on="timestamp", how="left").with_columns(
        pl.when(pl.col("_gross") > max_gross)
        .then(pl.col("weight") * max_gross / pl.col("_gross"))
        .otherwise(pl.col("weight"))
        .alias("weight")
    )
    return out.select(["timestamp", "asset", "weight"]).sort(["timestamp", "asset"])
