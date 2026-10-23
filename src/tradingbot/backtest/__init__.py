"""Backtesting and validation."""

from tradingbot.backtest.engine import BacktestResult, run_backtest
from tradingbot.backtest.metrics import compute_metrics, max_drawdown
from tradingbot.backtest.replay import PaperReplayResult, paper_replay
from tradingbot.backtest.validation import (
    FoldResult,
    WalkForwardResult,
    deflated_sharpe,
    pbo_cscv,
    trend_param_grid,
    walk_forward,
    xsmom_param_grid,
)

__all__ = [
    "BacktestResult",
    "FoldResult",
    "PaperReplayResult",
    "WalkForwardResult",
    "compute_metrics",
    "deflated_sharpe",
    "max_drawdown",
    "paper_replay",
    "pbo_cscv",
    "run_backtest",
    "trend_param_grid",
    "walk_forward",
    "xsmom_param_grid",
]
