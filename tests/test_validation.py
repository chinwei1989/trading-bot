from __future__ import annotations

import numpy as np
import pytest

from tradingbot.backtest.validation import (
    deflated_sharpe,
    pbo_cscv,
    trend_param_grid,
    xsmom_param_grid,
)


def test_deflated_sharpe_strong_vs_zero() -> None:
    strong = deflated_sharpe(0.10, 1000, 0.0, 3.0, 1, 0.0)
    zero = deflated_sharpe(0.0, 1000, 0.0, 3.0, 1, 0.0)
    assert strong > 0.99
    assert 0.4 < zero < 0.6


def test_pbo_random_is_near_half() -> None:
    values = []
    for seed in range(8):
        rng = np.random.default_rng(seed)
        returns = rng.normal(0.0, 1.0, size=(1200, 10))
        values.append(pbo_cscv(returns, n_blocks=12))
    assert 0.35 < float(np.mean(values)) < 0.65


def test_pbo_strong_signal_is_low() -> None:
    rng = np.random.default_rng(7)
    returns = rng.normal(0.0, 1.0, size=(800, 4))
    returns[:, 0] += 0.5
    pbo = pbo_cscv(returns, n_blocks=8)
    assert pbo < 0.2


def test_param_grid_sizes() -> None:
    assert len(trend_param_grid()) == 24
    assert len(xsmom_param_grid()) == 12


def test_pbo_requires_multiple_strategies() -> None:
    assert pbo_cscv(np.zeros((100, 1))) == 1.0
    with pytest.raises(ValueError):
        pbo_cscv(np.zeros(100))
