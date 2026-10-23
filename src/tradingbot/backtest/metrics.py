"""Performance and risk metrics."""

from __future__ import annotations

import math

import numpy as np
import polars as pl


def _clean(values) -> np.ndarray:
    arr = np.asarray(values, dtype=float).reshape(-1)
    return arr[np.isfinite(arr)]


def max_drawdown(equity: np.ndarray) -> float:
    if equity.size == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    return float((equity / peak - 1.0).min())


def compute_metrics(
    returns: pl.Series | np.ndarray | list[float],
    periods_per_year: int = 365,
    turnover: pl.Series | np.ndarray | list[float] | None = None,
    gross_exposure: pl.Series | np.ndarray | list[float] | None = None,
    net_exposure: pl.Series | np.ndarray | list[float] | None = None,
) -> dict[str, float]:
    r = _clean(returns)
    if r.size < 2:
        return {
            "total_return": 0.0,
            "cagr": 0.0,
            "vol": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "max_dd": 0.0,
            "calmar": 0.0,
            "hit_rate": 0.0,
            "profit_factor": 0.0,
            "var_95": 0.0,
            "cvar_95": 0.0,
            "n_days": float(r.size),
            "turnover_annual": 0.0,
            "gross_exposure_avg": 0.0,
            "net_exposure_avg": 0.0,
        }

    equity = np.cumprod(1.0 + r)
    years = max(r.size / periods_per_year, 1e-9)
    total_return = float(equity[-1] - 1.0)
    cagr = float(equity[-1] ** (1.0 / years) - 1.0) if equity[-1] > 0 else -1.0
    std = float(r.std(ddof=1))
    vol = std * math.sqrt(periods_per_year)
    sharpe = float(r.mean() / std * math.sqrt(periods_per_year)) if std > 1e-12 else 0.0
    downside = r[r < 0]
    down_std = float(downside.std(ddof=1)) if downside.size > 1 else 0.0
    sortino = (
        float(r.mean() / down_std * math.sqrt(periods_per_year)) if down_std > 1e-12 else 0.0
    )
    dd = max_drawdown(equity)
    calmar = float(cagr / abs(dd)) if dd < -1e-12 else 0.0
    gains = r[r > 0].sum()
    losses = -r[r < 0].sum()
    profit_factor = float(gains / losses) if losses > 1e-12 else 0.0
    var_95 = float(np.quantile(r, 0.05))
    tail = r[r <= var_95]
    cvar_95 = float(tail.mean()) if tail.size else var_95

    def _mean(series) -> float:
        if series is None:
            return 0.0
        arr = _clean(series)
        return float(arr.mean()) if arr.size else 0.0

    turnover_annual = float(_clean(turnover).sum() / years) if turnover is not None else 0.0

    return {
        "total_return": total_return,
        "cagr": cagr,
        "vol": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_dd": dd,
        "calmar": calmar,
        "hit_rate": float((r > 0).mean()),
        "profit_factor": profit_factor,
        "var_95": var_95,
        "cvar_95": cvar_95,
        "n_days": float(r.size),
        "turnover_annual": turnover_annual,
        "gross_exposure_avg": _mean(gross_exposure),
        "net_exposure_avg": _mean(net_exposure),
    }
