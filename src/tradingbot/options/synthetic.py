"""Synthetic option-chain generation for deterministic replay tests.

This is a pricing and plumbing tool, not evidence of profitability. It uses a
constant Black-Scholes implied volatility, fixed strikes around an initial
reference price, and a synthetic spread. Real option-chain data must replace it
for any credible backtest.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import NormalDist

import polars as pl

from tradingbot.data.store import wide
from tradingbot.options.account import OptionCandidate
from tradingbot.options.backtest import OptionSnapshot
from tradingbot.options.selector import Direction

_NORMAL = NormalDist()
_UNIVERSE = {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}


@dataclass(frozen=True)
class SyntheticChainConfig:
    iv: float = 0.50
    strike_pcts: tuple[float, ...] = (
        -0.30,
        -0.25,
        -0.20,
        -0.15,
        -0.10,
        -0.05,
        0.0,
        0.05,
        0.10,
        0.15,
        0.20,
        0.25,
        0.30,
    )
    expiry_days: tuple[int, ...] = (7, 14, 30)
    spread_pct: float = 0.02
    min_spread: float = 0.01
    open_interest: int = 1_000


def _bs(
    *,
    spot: float,
    strike: float,
    sigma: float,
    dte: int,
    option_type: str,
) -> tuple[float, float, float, float, float]:
    t = max(dte, 1) / 365.0
    vol = max(sigma, 1e-6)
    root_t = math.sqrt(t)
    d1 = (math.log(spot / strike) + 0.5 * vol * vol * t) / (vol * root_t)
    d2 = d1 - vol * root_t
    if option_type == "call":
        price = spot * _NORMAL.cdf(d1) - strike * _NORMAL.cdf(d2)
        delta = _NORMAL.cdf(d1)
    else:
        price = strike * _NORMAL.cdf(-d2) - spot * _NORMAL.cdf(-d1)
        delta = _NORMAL.cdf(d1) - 1.0
    gamma = _NORMAL.pdf(d1) / max(spot * vol * root_t, 1e-12)
    vega = spot * _NORMAL.pdf(d1) * root_t / 100.0
    theta = -spot * _NORMAL.pdf(d1) * vol / (2.0 * root_t) / 365.0
    return max(0.0, price), delta, gamma, max(0.0, vega), min(0.0, theta)


def build_chain(
    underlying: str,
    spot: float,
    *,
    now: datetime,
    reference_price: float,
    expiries: tuple[date, ...],
    config: SyntheticChainConfig | None = None,
) -> list[OptionCandidate]:
    config = config or SyntheticChainConfig()
    chain: list[OptionCandidate] = []
    for expiry in expiries:
        dte = (expiry - now.date()).days
        if dte <= 0:
            continue
        for pct in config.strike_pcts:
            strike = round(reference_price * (1.0 + pct), 2)
            if strike <= 0:
                continue
            for option_type in ("call", "put"):
                mid, delta, gamma, vega, theta = _bs(
                    spot=spot,
                    strike=strike,
                    sigma=config.iv,
                    dte=dte,
                    option_type=option_type,
                )
                if mid <= 0:
                    continue
                half_spread = max(config.min_spread, mid * config.spread_pct) / 2.0
                chain.append(
                    OptionCandidate(
                        instrument=(
                            f"{underlying}-SYN-{expiry.strftime('%d%b%y').upper()}-"
                            f"{strike:.0f}-{'C' if option_type == 'call' else 'P'}"
                        ),
                        underlying=underlying,
                        option_type=option_type,
                        strike=strike,
                        expiry=expiry,
                        bid=max(0.0, mid - half_spread),
                        ask=mid + half_spread,
                        mark=mid,
                        delta=delta,
                        gamma=gamma,
                        vega=vega,
                        theta=theta,
                        open_interest=config.open_interest,
                        volume=config.open_interest,
                        multiplier=1.0,
                    )
                )
    return chain


def build_snapshots(
    bars: pl.DataFrame,
    *,
    config: SyntheticChainConfig | None = None,
) -> list[OptionSnapshot]:
    """Create one chain snapshot per bar for BTCUSDT and ETHUSDT."""
    config = config or SyntheticChainConfig()
    close = wide(bars, "close").sort("timestamp")
    assets = [asset for asset in _UNIVERSE if asset in close.columns]
    if not assets:
        raise ValueError("synthetic snapshots require BTCUSDT and/or ETHUSDT")
    timestamps = close["timestamp"].to_list()
    if not timestamps:
        raise ValueError("no bars")
    start = timestamps[0]
    if not isinstance(start, datetime):
        raise ValueError("bar timestamps must be datetimes")
    start = start.astimezone(UTC) if start.tzinfo else start.replace(tzinfo=UTC)
    expiries = tuple(
        start.date() + timedelta(days=days) for days in config.expiry_days
    )
    reference = {}
    for asset in assets:
        first = close[asset].drop_nulls().head(1)
        if first.is_empty():
            continue
        reference[_UNIVERSE[asset]] = float(first[0])

    snapshots: list[OptionSnapshot] = []
    for row in close.iter_rows(named=True):
        ts = row["timestamp"]
        if not isinstance(ts, datetime):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        ts = ts.astimezone(UTC)
        prices: dict[str, float] = {}
        chain: list[OptionCandidate] = []
        for asset in assets:
            underlying = _UNIVERSE[asset]
            spot = row.get(asset)
            if spot is None or not math.isfinite(float(spot)) or float(spot) <= 0:
                continue
            spot = float(spot)
            reference_price = reference.get(underlying)
            if reference_price is None:
                continue
            prices[underlying] = spot
            chain.extend(
                build_chain(
                    underlying,
                    spot,
                    now=ts,
                    reference_price=reference_price,
                    expiries=expiries,
                    config=config,
                )
            )
        if chain:
            snapshots.append(OptionSnapshot(ts, chain, prices))
    return snapshots


def sma_direction_signal(
    bars: pl.DataFrame,
    *,
    lookback: int = 200,
) -> Callable[[OptionSnapshot], dict[str, Direction]]:
    """A simple causal 30m trend signal for synthetic replay only."""
    close = wide(bars, "close").sort("timestamp")
    assets = [asset for asset in _UNIVERSE if asset in close.columns]
    series: dict[str, list[float | None]] = {}
    for asset in assets:
        values = close[asset].to_list()
        sma: list[float | None] = [None] * len(values)
        running = 0.0
        for i, value in enumerate(values):
            if value is not None:
                running += float(value)
            if i >= lookback:
                old = values[i - lookback]
                if old is not None:
                    running -= float(old)
            if i >= lookback - 1:
                window = values[i - lookback + 1 : i + 1]
                if all(v is not None for v in window):
                    sma[i] = running / lookback
        series[_UNIVERSE[asset]] = sma
    directions_by_ts: dict[datetime, dict[str, Direction]] = {}
    for i, ts in enumerate(close["timestamp"].to_list()):
        if not isinstance(ts, datetime):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        ts = ts.astimezone(UTC)
        directions: dict[str, Direction] = {}
        for asset in assets:
            underlying = _UNIVERSE[asset]
            value = close[asset][i]
            average = series[underlying][i]
            if value is None or average is None:
                directions[underlying] = "flat"
            elif float(value) > float(average):
                directions[underlying] = "long"
            elif float(value) < float(average):
                directions[underlying] = "short"
            else:
                directions[underlying] = "flat"
        directions_by_ts[ts] = directions

    def signal(snapshot: OptionSnapshot) -> dict[str, Direction]:
        return directions_by_ts.get(snapshot.timestamp, {})

    return signal
