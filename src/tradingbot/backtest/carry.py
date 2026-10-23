"""Two-leg funding/basis carry research lane.

A carry position is long spot + short USD-M perpetual. The pair is
delta-neutral at entry and earns the funding rate when funding is positive. It
carries basis risk while open.

This model is deliberately research-only:
  - one pair-level capital model, not exchange margin/liquidation;
  - no order-book model;
  - no live execution path.

The daily P&L is:

    spot return - perp return + daily funding - both-leg fees

where weights are pair notional as a fraction of equity.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from tradingbot.backtest.metrics import compute_metrics
from tradingbot.data.funding import load_funding
from tradingbot.data.store import normalize_bars


@dataclass(frozen=True)
class CarryParams:
    lookback_days: int = 14
    rebalance_days: int = 7
    min_funding_apr: float = 0.05
    top_n: int = 5
    max_weight: float = 0.20
    max_gross: float = 0.80
    spot_cost_bps: float = 10.0
    perp_cost_bps: float = 10.0
    perp_margin: float = 0.20


@dataclass
class CarryResult:
    daily: pl.DataFrame
    weights: pl.DataFrame
    metrics: dict[str, float]
    params: CarryParams


def _close_frame(bars: pl.DataFrame, name: str) -> pl.DataFrame:
    bars = normalize_bars(bars).select(["timestamp", "asset", "close"])
    return bars.rename({"close": name})


def _prepare(
    spot_bars: pl.DataFrame,
    perp_bars: pl.DataFrame,
    funding: pl.DataFrame,
    lookback: int,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame, list[str]]:
    spot = _close_frame(spot_bars, "spot")
    perp = _close_frame(perp_bars, "perp")
    prices = spot.join(perp, on=["timestamp", "asset"], how="inner").sort(
        ["timestamp", "asset"]
    )
    if prices.is_empty():
        raise ValueError("no overlapping spot/perp bars")

    funding = funding.select(["timestamp", "asset", "funding_rate"]).with_columns(
        pl.col("timestamp").dt.date().alias("date")
    )
    daily_fund = (
        funding.group_by(["date", "asset"])
        .agg(pl.col("funding_rate").sum().alias("funding_daily"))
        .sort(["date", "asset"])
    )
    prices = (
        prices.with_columns(pl.col("timestamp").dt.date().alias("date"))
        .join(daily_fund, on=["date", "asset"], how="left")
        .with_columns(pl.col("funding_daily").fill_null(0.0))
        .drop("date")
    )

    assets = sorted(prices["asset"].unique().to_list())
    if not assets:
        raise ValueError("no common assets")

    spot_w = prices.pivot(index="timestamp", on="asset", values="spot").sort("timestamp")
    perp_w = prices.pivot(index="timestamp", on="asset", values="perp").sort("timestamp")
    funding_w = prices.pivot(
        index="timestamp", on="asset", values="funding_daily"
    ).sort("timestamp")
    mean_w = (
        prices.sort(["asset", "timestamp"])
        .with_columns(
            pl.col("funding_daily")
            .rolling_mean(window_size=lookback, min_samples=lookback)
            .over("asset")
            .alias("mean_funding")
        )
        .pivot(index="timestamp", on="asset", values="mean_funding")
        .sort("timestamp")
    )

    for frame in (spot_w, perp_w, funding_w, mean_w):
        for asset in assets:
            if asset not in frame.columns:
                frame = frame.with_columns(pl.lit(None).alias(asset))
    spot_w = spot_w.select(["timestamp", *assets]).with_columns(
        [pl.col(a).forward_fill().fill_null(0.0) for a in assets]
    )
    perp_w = perp_w.select(["timestamp", *assets]).with_columns(
        [pl.col(a).forward_fill().fill_null(0.0) for a in assets]
    )
    funding_w = funding_w.select(["timestamp", *assets]).with_columns(
        [pl.col(a).fill_null(0.0) for a in assets]
    )
    mean_w = mean_w.select(["timestamp", *assets])
    return spot_w, perp_w, funding_w, mean_w, assets


def run_carry(
    spot_bars: pl.DataFrame,
    perp_bars: pl.DataFrame,
    funding: pl.DataFrame,
    params: CarryParams | None = None,
    *,
    initial_capital: float = 10_000.0,
) -> CarryResult:
    """Run a daily two-leg carry backtest."""
    p = params or CarryParams()
    if not 1 <= p.top_n <= 50:
        raise ValueError("top_n must be between 1 and 50")
    if p.lookback_days < 2:
        raise ValueError("lookback_days must be >= 2")
    if p.rebalance_days < 1:
        raise ValueError("rebalance_days must be >= 1")
    if p.max_gross <= 0 or p.max_weight <= 0:
        raise ValueError("max_gross and max_weight must be positive")

    spot_w, perp_w, funding_w, mean_w, assets = _prepare(
        spot_bars, perp_bars, funding, p.lookback_days
    )
    dates = spot_w["timestamp"].to_list()
    n_days, n_assets = spot_w.height, len(assets)
    spot = spot_w.select(assets).to_numpy().astype(float)
    perp = perp_w.select(assets).to_numpy().astype(float)
    fund = funding_w.select(assets).to_numpy().astype(float)
    mean = mean_w.select(assets).to_numpy().astype(float)

    with np.errstate(divide="ignore", invalid="ignore"):
        spot_ret = np.vstack([np.zeros((1, n_assets)), spot[1:] / spot[:-1] - 1.0])
        perp_ret = np.vstack([np.zeros((1, n_assets)), perp[1:] / perp[:-1] - 1.0])
    spot_ret = np.nan_to_num(spot_ret, nan=0.0, posinf=0.0, neginf=0.0)
    perp_ret = np.nan_to_num(perp_ret, nan=0.0, posinf=0.0, neginf=0.0)

    target = np.zeros((n_days, n_assets))
    current = np.zeros(n_assets)
    threshold = p.min_funding_apr / 365.0
    for i in range(n_days):
        if i >= p.lookback_days and (i - p.lookback_days) % p.rebalance_days == 0:
            scores = mean[i]
            eligible = np.where(np.isfinite(scores) & (scores > threshold))[0]
            if eligible.size:
                order = eligible[np.argsort(scores[eligible])[::-1][: p.top_n]]
                weight = min(p.max_weight, p.max_gross / len(order))
                current = np.zeros(n_assets)
                current[order] = weight
            else:
                current = np.zeros(n_assets)
        target[i] = current

    effective = np.vstack([np.zeros((1, n_assets)), target[:-1]])
    previous = np.vstack([np.zeros((1, n_assets)), effective[:-1]])
    delta = np.abs(effective - previous)
    turnover = 2.0 * delta.sum(axis=1)
    cost = delta.sum(axis=1) * (p.spot_cost_bps + p.perp_cost_bps) / 10_000.0
    funding_return = (effective * fund).sum(axis=1)
    basis_return = (effective * (spot_ret - perp_ret)).sum(axis=1)
    gross_return = funding_return + basis_return
    net_return = gross_return - cost
    equity = initial_capital * np.cumprod(1.0 + net_return)

    daily = pl.DataFrame(
        {
            "timestamp": dates,
            "funding_return": funding_return,
            "basis_return": basis_return,
            "gross_return": gross_return,
            "cost": cost,
            "net_return": net_return,
            "equity": equity,
            "turnover": turnover,
            "gross_exposure": np.abs(effective).sum(axis=1),
            "net_exposure": np.zeros(n_days),
        }
    )
    metrics = compute_metrics(
        daily["net_return"],
        periods_per_year=365,
        turnover=daily["turnover"],
        gross_exposure=daily["gross_exposure"],
        net_exposure=daily["net_exposure"],
    )
    metrics["final_equity"] = float(equity[-1]) if equity.size else initial_capital
    active = np.abs(effective).sum(axis=1) > 0
    metrics["avg_funding_annualized"] = (
        float(np.mean(funding_return[active]) * 365) if active.any() else 0.0
    )
    metrics["avg_basis_annualized"] = (
        float(np.mean(basis_return[active]) * 365) if active.any() else 0.0
    )
    metrics["margin_fraction"] = p.perp_margin

    weights = (
        pl.DataFrame(effective, schema=assets)
        .with_columns(pl.Series("timestamp", dates))
        .unpivot(index="timestamp", variable_name="asset", value_name="weight")
        .filter(pl.col("weight").abs() > 1e-12)
        .sort(["timestamp", "asset"])
    )
    return CarryResult(daily=daily, weights=weights, metrics=metrics, params=p)


@dataclass
class CarryWalkForwardResult:
    folds: list[dict[str, object]]
    oos_returns: np.ndarray
    oos_metrics: dict[str, float]
    dsr: float
    pbo: float
    trial_sharpes: list[float]


def _slice_bars(bars: pl.DataFrame, start: Any, end: Any) -> pl.DataFrame:
    return bars.filter((pl.col("timestamp") >= start) & (pl.col("timestamp") <= end))


def walk_forward_carry(
    spot_bars: pl.DataFrame,
    perp_bars: pl.DataFrame,
    funding: pl.DataFrame,
    param_grid: list[dict[str, object]],
    *,
    train_days: int = 730,
    test_days: int = 365,
    step_days: int = 365,
    warmup_days: int = 60,
) -> CarryWalkForwardResult:
    """Simple anchored grid walk-forward for the carry lane."""
    from tradingbot.backtest.validation import deflated_sharpe, pbo_cscv

    if not param_grid:
        raise ValueError("param_grid must not be empty")
    spot = normalize_bars(spot_bars)
    dates = spot["timestamp"].unique().sort().to_list()
    min_needed = warmup_days + train_days + test_days
    if len(dates) < min_needed:
        raise ValueError(f"not enough data: {len(dates)} < {min_needed}")

    oos_parts: list[np.ndarray] = []
    oos_turnover_parts: list[np.ndarray] = []
    oos_gross_parts: list[np.ndarray] = []
    oos_net_parts: list[np.ndarray] = []
    test_by_param: dict[str, list[np.ndarray]] = {}
    trial_sharpes: list[float] = []
    folds: list[dict[str, object]] = []
    for test_start_idx in range(
        warmup_days + train_days, len(dates) - test_days + 1, step_days
    ):
        train_start = dates[test_start_idx - train_days]
        train_end = dates[test_start_idx - 1]
        test_start = dates[test_start_idx]
        test_end = dates[test_start_idx + test_days - 1]
        history_start = dates[max(0, test_start_idx - train_days - warmup_days)]

        train_spot = _slice_bars(spot_bars, history_start, train_end)
        train_perp = _slice_bars(perp_bars, history_start, train_end)
        train_fund = _slice_bars(funding, history_start, train_end)
        test_spot = _slice_bars(spot_bars, history_start, test_end)
        test_perp = _slice_bars(perp_bars, history_start, test_end)
        test_fund = _slice_bars(funding, history_start, test_end)

        scored: list[tuple[float, dict[str, object], pl.DataFrame, np.ndarray]] = []
        for raw in param_grid:
            params = CarryParams(**raw)  # type: ignore[arg-type]
            train_result = run_carry(train_spot, train_perp, train_fund, params)
            test_result = run_carry(test_spot, test_perp, test_fund, params)
            train_slice = train_result.daily.filter(pl.col("timestamp") >= train_start)
            test_slice = test_result.daily.filter(pl.col("timestamp") >= test_start)
            train_metrics = compute_metrics(
                train_slice["net_return"], periods_per_year=365
            )
            test_returns = test_slice["net_return"].to_numpy()
            key = json.dumps(raw, sort_keys=True, default=str)
            test_by_param.setdefault(key, []).append(test_returns)
            trial_sharpes.append(float(train_metrics.get("sharpe", 0.0)))
            scored.append(
                (
                    float(train_metrics.get("sharpe", -1e9)),
                    raw,
                    test_slice,
                    test_returns,
                )
            )
        _, best_params, best_slice, best_returns = max(scored, key=lambda row: row[0])
        oos_parts.append(best_returns)
        oos_turnover_parts.append(best_slice["turnover"].to_numpy())
        oos_gross_parts.append(best_slice["gross_exposure"].to_numpy())
        oos_net_parts.append(best_slice["net_exposure"].to_numpy())
        folds.append(
            {
                "train_start": str(train_start),
                "train_end": str(train_end),
                "test_start": str(test_start),
                "test_end": str(test_end),
                "best_params": best_params,
                "test_metrics": compute_metrics(
                    best_slice["net_return"], periods_per_year=365
                ),
            }
        )

    oos = np.concatenate(oos_parts) if oos_parts else np.array([])
    oos_turnover = (
        np.concatenate(oos_turnover_parts) if oos_turnover_parts else np.array([])
    )
    oos_gross = np.concatenate(oos_gross_parts) if oos_gross_parts else np.array([])
    oos_net = np.concatenate(oos_net_parts) if oos_net_parts else np.array([])
    oos_metrics = compute_metrics(
        oos,
        periods_per_year=365,
        turnover=oos_turnover,
        gross_exposure=oos_gross,
        net_exposure=oos_net,
    )
    dsr = 0.0
    if oos.size > 1 and oos.std(ddof=1) > 0:
        from scipy.stats import kurtosis, skew  # type: ignore[import-untyped]

        annual_sr = float(oos.mean() / oos.std(ddof=1) * np.sqrt(365))
        per_sr = annual_sr / np.sqrt(365)
        trial_per = np.asarray(trial_sharpes, dtype=float) / np.sqrt(365)
        variance = float(np.var(trial_per, ddof=1)) if trial_per.size > 1 else 0.0
        dsr = deflated_sharpe(
            per_sr,
            len(oos),
            float(skew(oos, bias=False)),
            float(kurtosis(oos, bias=False)),
            len(trial_sharpes),
            variance,
        )

    matrices = [np.concatenate(parts) for parts in test_by_param.values()]
    if matrices and len({len(x) for x in matrices}) == 1:
        pbo = pbo_cscv(np.column_stack(matrices))
    else:
        pbo = 1.0
    return CarryWalkForwardResult(
        folds=folds,
        oos_returns=oos,
        oos_metrics=oos_metrics,
        dsr=float(dsr),
        pbo=float(pbo),
        trial_sharpes=trial_sharpes,
    )


def carry_param_grid() -> list[dict[str, object]]:
    """Small, deliberately un-tuned grid for the carry walk-forward."""
    grid: list[dict[str, object]] = []
    for lookback in (7, 14, 30):
        for rebalance in (7, 14):
            for min_apr in (0.03, 0.05, 0.10):
                grid.append(
                    {
                        "lookback_days": lookback,
                        "rebalance_days": rebalance,
                        "min_funding_apr": min_apr,
                        "top_n": 5,
                        "max_weight": 0.20,
                        "max_gross": 0.60,
                        "spot_cost_bps": 10.0,
                        "perp_cost_bps": 10.0,
                    }
                )
    return grid


def save_carry(result: CarryResult, out_dir: str | Path) -> tuple[Path, Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    daily = out / "carry_daily.csv"
    weights = out / "carry_weights.parquet"
    metrics = out / "carry_metrics.json"
    result.daily.write_csv(daily)
    result.weights.write_parquet(weights)
    metrics.write_text(json.dumps(result.metrics, indent=2, default=str), encoding="utf-8")
    return daily, weights, metrics


def load_carry_inputs(
    spot_config: str | Path,
    perp_config: str | Path,
    funding_path: str | Path,
    *,
    root: Path | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    from tradingbot.config import load_config
    from tradingbot.data.store import load_bars

    root = root or Path.cwd()
    spot_path = Path(spot_config)
    perp_path = Path(perp_config)
    spot_path = spot_path if spot_path.is_absolute() else root / spot_path
    perp_path = perp_path if perp_path.is_absolute() else root / perp_path
    spot_cfg = load_config(spot_path)
    perp_cfg = load_config(perp_path)
    funding_path = Path(funding_path)
    funding_path = funding_path if funding_path.is_absolute() else root / funding_path
    spot_bars_path = root / spot_cfg.data.bars_path
    perp_bars_path = root / perp_cfg.data.bars_path
    return load_bars(spot_bars_path), load_bars(perp_bars_path), load_funding(funding_path)
