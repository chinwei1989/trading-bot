"""Strategy protocol and result container."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import polars as pl


@dataclass
class StrategyResult:
    name: str
    weights: pl.DataFrame  # timestamp, asset, weight (sparse rebalance rows)
    params: dict[str, Any] = field(default_factory=dict)
    notes: str = ""


class Strategy(Protocol):
    name: str

    def generate_weights(self, bars: pl.DataFrame) -> StrategyResult: ...
