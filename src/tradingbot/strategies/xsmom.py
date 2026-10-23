"""Cross-sectional momentum strategy for crypto (long/short or long-only)."""

from __future__ import annotations

import math

import polars as pl

from tradingbot.config import XsmomParams
from tradingbot.data.store import asset_columns, wide
from tradingbot.features.indicators import (
    cap_weights,
    momentum,
    rebalance_dates,
    returns,
    scale_to_target_vol,
)
from tradingbot.strategies.base import StrategyResult


class XsmomStrategy:
    name = "xsmom"

    def __init__(self, params: XsmomParams, periods_per_year: int = 365):
        self.params = params
        self.periods_per_year = periods_per_year

    def generate_weights(self, bars: pl.DataFrame) -> StrategyResult:
        p = self.params
        close = wide(bars, "close").sort("timestamp")
        assets = asset_columns(close)
        if not assets:
            return StrategyResult(self.name, pl.DataFrame(), p.model_dump())
        close = close.with_columns([pl.col(a).forward_fill() for a in assets])

        mom = momentum(close, p.lookback, p.skip)
        dates = rebalance_dates(close["timestamp"], p.rebalance)
        rows: list[dict[str, object]] = []

        for ts in dates:
            snap = mom.filter(pl.col("timestamp") == ts)
            if snap.is_empty():
                continue
            values = {}
            for a in assets:
                value = snap[a][0]
                if value is not None and math.isfinite(float(value)):
                    values[a] = float(value)
            weights = {a: 0.0 for a in assets}
            if len(values) >= p.min_assets:
                ranked = sorted(values.items(), key=lambda kv: kv[1])
                n = len(ranked)
                n_top = max(1, round(n * p.top_quantile))
                n_bottom = max(1, round(n * p.bottom_quantile)) if p.long_short else 0
                if n_top + n_bottom > n:
                    n_bottom = max(0, n - n_top)
                longs = [a for a, _ in ranked[-n_top:]]
                shorts = [a for a, _ in ranked[:n_bottom]] if n_bottom else []
                for a in longs:
                    weights[a] = 1.0 / len(longs)
                for a in shorts:
                    weights[a] = -1.0 / len(shorts)
            for a in assets:
                rows.append(
                    {
                        "timestamp": ts,
                        "asset": a,
                        "weight": max(-p.max_weight, min(p.max_weight, weights[a])),
                    }
                )

        if not rows:
            return StrategyResult(self.name, pl.DataFrame(), p.model_dump())
        result = pl.DataFrame(rows).sort(["timestamp", "asset"])
        if p.vol_target:
            result = scale_to_target_vol(
                result,
                returns(close),
                target_vol=p.target_vol,
                window=max(p.vol_window, 20),
                periods_per_year=self.periods_per_year,
            )
        result = cap_weights(result, p.max_weight, p.max_gross)
        return StrategyResult(self.name, result, p.model_dump())
