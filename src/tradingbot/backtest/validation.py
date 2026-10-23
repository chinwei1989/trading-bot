"""Walk-forward, Deflated Sharpe Ratio, and Probability of Backtest Overfitting."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from itertools import combinations
from typing import Any

import numpy as np
import polars as pl
from scipy.stats import kurtosis, norm, skew  # type: ignore[import-untyped]

from tradingbot.backtest.engine import run_backtest
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.config import BacktestConfig, StrategyConfig
from tradingbot.data.store import normalize_bars
from tradingbot.strategies import build_strategy


@dataclass
class FoldResult:
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    best_params: dict[str, Any]
    train_sharpe: float
    test_sharpe: float
    test_return: float
    test_max_dd: float


@dataclass
class WalkForwardResult:
    folds: list[FoldResult]
    oos_returns: np.ndarray
    dsr: float
    pbo: float
    trial_sharpes: list[float]
    best_params: list[dict[str, Any]] = field(default_factory=list)
    oos_turnover: np.ndarray = field(default_factory=lambda: np.array([]))
    oos_gross_exposure: np.ndarray = field(default_factory=lambda: np.array([]))
    oos_net_exposure: np.ndarray = field(default_factory=lambda: np.array([]))


def _make_strategy(strategy_config: StrategyConfig, params: dict[str, Any], ppy: int):
    cfg = strategy_config.model_copy(deep=True)
    if cfg.name == "trend":
        cfg.trend = cfg.trend.model_copy(update=params)
    elif cfg.name == "xsmom":
        cfg.xsmom = cfg.xsmom.model_copy(update=params)
    elif cfg.name == "breakout":
        cfg.breakout = cfg.breakout.model_copy(update=params)
    elif cfg.name == "reversal":
        cfg.reversal = cfg.reversal.model_copy(update=params)
    elif cfg.name == "meta":
        cfg.meta = cfg.meta.model_copy(update=params)
    elif cfg.name == "combined":
        cfg.combined = cfg.combined.model_copy(update=params)
    else:
        raise ValueError(f"unknown strategy: {cfg.name}")
    return build_strategy(cfg, ppy)


def _slice_metrics(
    daily: pl.DataFrame, start: datetime, periods_per_year: int = 365
) -> tuple[dict[str, float], pl.DataFrame]:
    sliced = daily.filter(pl.col("timestamp") >= start)
    metrics = compute_metrics(
        sliced["net_return"],
        periods_per_year=periods_per_year,
        turnover=sliced["turnover"],
        gross_exposure=sliced["gross_exposure"],
        net_exposure=sliced["net_exposure"],
    )
    return metrics, sliced


def deflated_sharpe(
    sr: float,
    t: int,
    skewness: float,
    kurt: float,
    n_trials: int,
    sr_variance: float,
) -> float:
    """Bailey & López de Prado (2014) DSR. `sr` is per-period, not annualized."""
    n = max(2, int(n_trials))
    gamma = 0.5772156649015329
    sr0 = math.sqrt(max(sr_variance, 0.0)) * (
        (1.0 - gamma) * norm.ppf(1.0 - 1.0 / n) + gamma * norm.ppf(1.0 - 1.0 / (n * math.e))
    )
    denom = math.sqrt(max(1e-12, 1.0 - skewness * sr + ((kurt - 1.0) / 4.0) * sr**2))
    return float(norm.cdf((sr - sr0) * math.sqrt(max(1, t - 1)) / denom))


def _sharpe_columns(x: np.ndarray) -> np.ndarray:
    mean = x.mean(axis=0)
    std = x.std(axis=0, ddof=1)
    return np.divide(mean, std, out=np.zeros_like(mean), where=std > 1e-12)


def pbo_cscv(returns: np.ndarray, n_blocks: int = 16) -> float:
    """Probability of backtest overfitting via CSCV.

    `returns` shape: (observations, strategies). Higher is better.
    """
    if returns.ndim != 2:
        raise ValueError("returns must be 2D")
    t, n = returns.shape
    if n < 2 or t < 8:
        return 1.0
    s = min(n_blocks, t)
    if s % 2:
        s -= 1
    if s < 4:
        return 1.0
    t_trim = t - (t % s)
    blocks = np.array_split(returns[:t_trim], s)
    half = s // 2
    combos = list(combinations(range(s), half))
    if len(combos) > 5000:
        rng = np.random.default_rng(7)
        idx = rng.choice(len(combos), size=5000, replace=False)
        combos = [combos[i] for i in idx]
    overfit = 0
    for combo in combos:
        is_idx = set(combo)
        oos_idx = [i for i in range(s) if i not in is_idx]
        is_ret = np.concatenate([blocks[i] for i in combo], axis=0)
        oos_ret = np.concatenate([blocks[i] for i in oos_idx], axis=0)
        is_perf = _sharpe_columns(is_ret)
        oos_perf = _sharpe_columns(oos_ret)
        best = int(np.argmax(is_perf))
        rank = (
            np.sum(oos_perf < oos_perf[best]) + 0.5 * np.sum(oos_perf == oos_perf[best])
        ) / n
        if rank <= 0.5:
            overfit += 1
    return float(overfit / len(combos))


def walk_forward(
    bars: pl.DataFrame,
    strategy_config: StrategyConfig,
    backtest_config: BacktestConfig,
    param_grid: list[dict[str, Any]],
    *,
    train_days: int = 900,
    test_days: int = 365,
    step_days: int = 365,
    warmup_days: int = 260,
    periods_per_year: int = 365,
) -> WalkForwardResult:
    bars = normalize_bars(bars)
    dates = bars["timestamp"].unique().sort().to_list()
    min_needed = warmup_days + train_days + test_days
    if len(dates) < min_needed:
        raise ValueError(f"not enough data: {len(dates)} < {min_needed}")

    folds: list[FoldResult] = []
    oos_parts: list[np.ndarray] = []
    oos_turnover_parts: list[np.ndarray] = []
    oos_gross_parts: list[np.ndarray] = []
    oos_net_parts: list[np.ndarray] = []
    trial_sharpes: list[float] = []
    best_params: list[dict[str, Any]] = []
    test_by_param: dict[str, list[np.ndarray]] = {}

    test_start_indices = range(
        warmup_days + train_days, len(dates) - test_days + 1, step_days
    )
    for test_start_idx in test_start_indices:
        train_start_idx = test_start_idx - train_days
        train_end_idx = test_start_idx
        test_end_idx = test_start_idx + test_days
        train_start_date = dates[train_start_idx]
        train_end_date = dates[train_end_idx - 1]
        test_start_date = dates[test_start_idx]
        test_end_date = dates[test_end_idx - 1]
        hist_start = dates[max(0, train_start_idx - warmup_days)]
        train_bars = bars.filter(
            (pl.col("timestamp") >= hist_start) & (pl.col("timestamp") <= train_end_date)
        )
        test_hist_start = dates[max(0, test_start_idx - warmup_days)]
        test_bars = bars.filter(
            (pl.col("timestamp") >= test_hist_start)
            & (pl.col("timestamp") <= test_end_date)
        )

        fold_rows: list[tuple[float, dict[str, Any], float, float, float, pl.DataFrame]] = []
        for params in param_grid:
            key = json.dumps(params, sort_keys=True, default=str)
            strategy = _make_strategy(strategy_config, params, periods_per_year)
            train_weights = strategy.generate_weights(train_bars).weights
            train_result = run_backtest(train_bars, train_weights, backtest_config)
            train_metrics, _ = _slice_metrics(
                train_result.daily, train_start_date, periods_per_year
            )
            test_weights = strategy.generate_weights(test_bars).weights
            test_result = run_backtest(test_bars, test_weights, backtest_config)
            test_metrics, test_slice = _slice_metrics(
                test_result.daily, test_start_date, periods_per_year
            )
            test_returns = test_slice["net_return"].to_numpy()
            test_by_param.setdefault(key, []).append(test_returns)
            trial_sharpes.append(float(train_metrics.get("sharpe", 0.0)))
            fold_rows.append(
                (
                    float(train_metrics.get("sharpe", -1e9)),
                    params,
                    float(test_metrics.get("sharpe", 0.0)),
                    float(test_metrics.get("total_return", 0.0)),
                    float(test_metrics.get("max_dd", 0.0)),
                    test_slice,
                )
            )

        best = max(fold_rows, key=lambda row: row[0])
        _, best_p, test_sharpe, test_return, test_dd, best_slice = best
        folds.append(
            FoldResult(
                train_start=train_start_date,
                train_end=train_end_date,
                test_start=test_start_date,
                test_end=test_end_date,
                best_params=best_p,
                train_sharpe=best[0],
                test_sharpe=test_sharpe,
                test_return=test_return,
                test_max_dd=test_dd,
            )
        )
        oos_parts.append(best_slice["net_return"].to_numpy())
        oos_turnover_parts.append(best_slice["turnover"].to_numpy())
        oos_gross_parts.append(best_slice["gross_exposure"].to_numpy())
        oos_net_parts.append(best_slice["net_exposure"].to_numpy())
        best_params.append(best_p)

    oos = np.concatenate(oos_parts) if oos_parts else np.array([])
    oos_turnover = np.concatenate(oos_turnover_parts) if oos_turnover_parts else np.array([])
    oos_gross = np.concatenate(oos_gross_parts) if oos_gross_parts else np.array([])
    oos_net = np.concatenate(oos_net_parts) if oos_net_parts else np.array([])
    if oos.size > 1 and oos.std(ddof=1) > 0:
        sr_annual = float(oos.mean() / oos.std(ddof=1) * math.sqrt(periods_per_year))
        sr_per = sr_annual / math.sqrt(periods_per_year)
        trials_per = np.nan_to_num(
            np.asarray(trial_sharpes, dtype=float) / math.sqrt(periods_per_year),
            nan=0.0,
            posinf=0.0,
            neginf=0.0,
        )
        sr_var = float(np.var(trials_per, ddof=1)) if trials_per.size > 1 else 0.0
        dsr = deflated_sharpe(
            sr_per,
            len(oos),
            float(skew(oos, bias=False)),
            float(kurtosis(oos, fisher=False, bias=False)),
            n_trials=len(trial_sharpes),
            sr_variance=sr_var,
        )
    else:
        dsr = 0.0

    matrix_parts = []
    if test_by_param:
        min_len = min(sum(len(x) for x in parts) for parts in test_by_param.values())
        for parts in test_by_param.values():
            joined = np.concatenate(parts)
            matrix_parts.append(joined[:min_len])
        matrix = np.nan_to_num(np.column_stack(matrix_parts), nan=0.0, posinf=0.0, neginf=0.0)
        pbo = pbo_cscv(matrix)
    else:
        pbo = 1.0

    return WalkForwardResult(
        folds=folds,
        oos_returns=oos,
        dsr=float(dsr),
        pbo=float(pbo),
        trial_sharpes=trial_sharpes,
        best_params=best_params,
        oos_turnover=oos_turnover,
        oos_gross_exposure=oos_gross,
        oos_net_exposure=oos_net,
    )


def trend_param_grid() -> list[dict[str, Any]]:
    return [
        {
            "lookback": lb,
            "vol_window": vw,
            "target_vol": tv,
            "long_short": ls,
        }
        for lb in (50, 100, 200)
        for vw in (30, 60)
        for tv in (0.10, 0.15)
        for ls in (False, True)
    ]


def xsmom_param_grid() -> list[dict[str, Any]]:
    return [
        {
            "lookback": lb,
            "top_quantile": q,
            "bottom_quantile": q,
            "long_short": ls,
        }
        for lb in (20, 60, 120)
        for q in (0.2, 0.3)
        for ls in (False, True)
    ]


def breakout_param_grid() -> list[dict[str, Any]]:
    return [
        {
            "lookback": lb,
            "exit_lookback": exit_lb,
            "atr_stop": stop,
            "risk_per_trade": risk,
        }
        for lb in (20, 55, 100)
        for exit_lb in (10, 20)
        for stop in (2.0, 3.0)
        for risk in (0.01, 0.02)
    ]


def reversal_param_grid() -> list[dict[str, Any]]:
    return [
        {
            "entry_z": entry,
            "exit_z": exit_z,
            "rsi_entry": rsi_entry,
            "regime_filter": regime,
        }
        for entry in (1.5, 2.0, 2.5)
        for exit_z in (-0.5, 0.0)
        for rsi_entry in (5.0, 10.0)
        for regime in (False, True)
    ]


def meta_param_grid() -> list[dict[str, Any]]:
    return [
        {
            "sleeves": {
                "trend": 0.40,
                "breakout": 0.30,
                "reversal": 0.15,
                "xsmom": 0.15,
            }
        },
        {
            "sleeves": {
                "trend": 0.30,
                "breakout": 0.30,
                "reversal": 0.20,
                "xsmom": 0.20,
            }
        },
        {
            "sleeves": {
                "trend": 0.50,
                "breakout": 0.25,
                "reversal": 0.10,
                "xsmom": 0.15,
            }
        },
    ]
