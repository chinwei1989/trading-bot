"""In-memory paper options broker with cash and premium accounting.

Phase 1 is long-premium only. The premium, cash, and settlement currency are
modelled in quote currency (USD/USDT), not Deribit inverse-option units. A venue
adapter must apply the venue's contract multiplier and settlement rules.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from tradingbot.options.account import (
    OptionAccount,
    OptionCandidate,
    OptionPosition,
    OptionType,
)

Direction = Literal["buy", "sell"]


@dataclass
class OptionHolding:
    instrument: str
    underlying: str
    option_type: OptionType
    strike: float
    expiry: date
    qty: int
    entry_premium: float
    mark_premium: float
    delta: float
    vega: float
    theta: float
    multiplier: float = 1.0
    opened_on: str | None = None

    def as_position(self) -> OptionPosition:
        return OptionPosition(
            instrument=self.instrument,
            underlying=self.underlying,
            option_type=self.option_type,
            strike=self.strike,
            expiry=self.expiry,
            qty=self.qty,
            entry_premium=self.entry_premium,
            mark_premium=self.mark_premium,
            delta=self.delta,
            vega=self.vega,
            theta=self.theta,
            multiplier=self.multiplier,
        )


@dataclass
class OptionFill:
    instrument: str
    side: Direction
    qty: int
    premium: float
    fee: float
    cash_after: float
    status: str = "filled"
    reason: str = ""


@dataclass
class OptionSettlement:
    instrument: str
    qty: int
    intrinsic: float
    proceeds: float
    status: str = "settled"


class PaperOptionsBroker:
    def __init__(
        self,
        cash: float = 10_000.0,
        *,
        fee_bps: float = 3.0,
        state_path: Path | None = None,
    ):
        self.cash = float(cash)
        self.initial_cash = float(cash)
        self.fee_bps = fee_bps
        self.state_path = state_path
        self.holdings: dict[str, OptionHolding] = {}

    def account(self) -> OptionAccount:
        return OptionAccount(
            cash=self.cash,
            positions=tuple(
                holding.as_position() for holding in self.holdings.values()
            ),
        )

    def mark_to_chain(self, chain: list[OptionCandidate]) -> None:
        quotes = {candidate.instrument: candidate for candidate in chain}
        for holding in self.holdings.values():
            quote = quotes.get(holding.instrument)
            if quote is None:
                continue
            holding.mark_premium = quote.bid if quote.bid > 0 else quote.mark
            holding.delta = quote.delta
            holding.vega = quote.vega
            holding.theta = quote.theta

    def _fee(self, premium: float, qty: int) -> float:
        return abs(premium) * abs(qty) * self.fee_bps / 10_000.0

    def buy(
        self,
        candidate: OptionCandidate,
        qty: int,
        *,
        now: datetime | None = None,
    ) -> OptionFill:
        if qty <= 0:
            return OptionFill(
                candidate.instrument,
                "buy",
                qty,
                candidate.ask,
                0.0,
                self.cash,
                status="rejected",
                reason="qty must be positive",
            )
        premium = max(0.0, candidate.ask)
        cost = premium * qty * candidate.multiplier
        fee = self._fee(premium * candidate.multiplier, qty)
        if cost + fee > self.cash + 1e-9:
            return OptionFill(
                candidate.instrument,
                "buy",
                qty,
                premium,
                fee,
                self.cash,
                status="rejected",
                reason="insufficient cash",
            )
        self.cash -= cost + fee
        existing = self.holdings.get(candidate.instrument)
        if existing:
            total_qty = existing.qty + qty
            existing.entry_premium = (
                existing.entry_premium * existing.qty + premium * qty
            ) / total_qty
            existing.qty = total_qty
            existing.mark_premium = premium
            existing.delta = candidate.delta
            existing.vega = candidate.vega
            existing.theta = candidate.theta
        else:
            self.holdings[candidate.instrument] = OptionHolding(
                instrument=candidate.instrument,
                underlying=candidate.underlying,
                option_type=candidate.option_type,
                strike=candidate.strike,
                expiry=candidate.expiry,
                qty=qty,
                entry_premium=premium,
                mark_premium=premium,
                delta=candidate.delta,
                vega=candidate.vega,
                theta=candidate.theta,
                multiplier=candidate.multiplier,
                opened_on=(now or datetime.now()).date().isoformat(),
            )
        return OptionFill(
            candidate.instrument,
            "buy",
            qty,
            premium,
            fee,
            self.cash,
        )

    def sell(
        self,
        candidate: OptionCandidate,
        qty: int,
        *,
        now: datetime | None = None,
    ) -> OptionFill:
        holding = self.holdings.get(candidate.instrument)
        if holding is None or qty <= 0:
            return OptionFill(
                candidate.instrument,
                "sell",
                qty,
                candidate.bid,
                0.0,
                self.cash,
                status="rejected",
                reason="no position",
            )
        qty = min(qty, holding.qty)
        premium = max(0.0, candidate.bid)
        proceeds = premium * qty * holding.multiplier
        fee = self._fee(premium * holding.multiplier, qty)
        self.cash += proceeds - fee
        remaining = holding.qty - qty
        if remaining <= 0:
            self.holdings.pop(candidate.instrument, None)
        else:
            holding.qty = remaining
            holding.mark_premium = premium
        return OptionFill(
            candidate.instrument,
            "sell",
            qty,
            premium,
            fee,
            self.cash,
        )

    def settle_expired(
        self,
        underlying_prices: dict[str, float],
        *,
        today: date | None = None,
    ) -> list[OptionSettlement]:
        today = today or datetime.now().date()
        settlements: list[OptionSettlement] = []
        for instrument, holding in list(self.holdings.items()):
            if holding.expiry > today:
                continue
            price = underlying_prices.get(holding.underlying)
            if price is None or price <= 0:
                settlements.append(
                    OptionSettlement(
                        instrument,
                        holding.qty,
                        0.0,
                        0.0,
                        status="missing_underlying_price",
                    )
                )
                continue
            intrinsic = (
                max(0.0, price - holding.strike)
                if holding.option_type == "call"
                else max(0.0, holding.strike - price)
            )
            proceeds = intrinsic * holding.qty * holding.multiplier
            self.cash += proceeds
            settlements.append(
                OptionSettlement(
                    instrument,
                    holding.qty,
                    intrinsic,
                    proceeds,
                )
            )
            self.holdings.pop(instrument, None)
        return settlements

    def save(self, path: Path | None = None) -> Path:
        out = path or self.state_path
        if out is None:
            raise ValueError("no state path")
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cash": self.cash,
            "initial_cash": self.initial_cash,
            "fee_bps": self.fee_bps,
            "holdings": {
                instrument: {
                    "underlying": holding.underlying,
                    "option_type": holding.option_type,
                    "strike": holding.strike,
                    "expiry": holding.expiry.isoformat(),
                    "qty": holding.qty,
                    "entry_premium": holding.entry_premium,
                    "mark_premium": holding.mark_premium,
                    "delta": holding.delta,
                    "vega": holding.vega,
                    "theta": holding.theta,
                    "multiplier": holding.multiplier,
                    "opened_on": holding.opened_on,
                }
                for instrument, holding in self.holdings.items()
            },
        }
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return out

    def load(self, path: Path | None = None) -> bool:
        source = path or self.state_path
        if source is None or not source.exists():
            return False
        payload = json.loads(source.read_text(encoding="utf-8"))
        self.cash = float(payload["cash"])
        self.initial_cash = float(payload.get("initial_cash", self.cash))
        self.fee_bps = float(payload.get("fee_bps", self.fee_bps))
        self.holdings = {
            instrument: OptionHolding(
                instrument=instrument,
                underlying=str(row["underlying"]),
                option_type=str(row["option_type"]),  # type: ignore[arg-type]
                strike=float(row["strike"]),
                expiry=date.fromisoformat(str(row["expiry"])),
                qty=int(row["qty"]),
                entry_premium=float(row["entry_premium"]),
                mark_premium=float(row["mark_premium"]),
                delta=float(row["delta"]),
                vega=float(row["vega"]),
                theta=float(row["theta"]),
                multiplier=float(row.get("multiplier", 1.0)),
                opened_on=(
                    str(row["opened_on"]) if row.get("opened_on") is not None else None
                ),
            )
            for instrument, row in payload.get("holdings", {}).items()
        }
        return True
