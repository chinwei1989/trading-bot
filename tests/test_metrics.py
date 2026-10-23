from __future__ import annotations

import numpy as np
import pytest

from tradingbot.backtest.metrics import compute_metrics, max_drawdown


def test_max_drawdown() -> None:
    assert max_drawdown(np.array([1.0, 1.2, 0.9, 1.0])) == pytest.approx(-0.25)


def test_metrics_on_known_returns() -> None:
    r = np.array([0.01, -0.005, 0.02, 0.0])
    metrics = compute_metrics(r, periods_per_year=252)
    assert metrics["total_return"] == pytest.approx(np.prod(1 + r) - 1)
    assert metrics["n_days"] == 4
    assert metrics["max_dd"] < 0
    assert metrics["hit_rate"] == pytest.approx(0.5)


def test_metrics_short_series() -> None:
    metrics = compute_metrics([0.01], periods_per_year=365)
    assert metrics["total_return"] == 0.0
    assert metrics["n_days"] == 1
