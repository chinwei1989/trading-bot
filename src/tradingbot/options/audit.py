"""Append-only audit trail for paper option fills and settlements."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tradingbot.options.broker import OptionFill, OptionSettlement


def append_option_events(
    path: str | Path,
    *,
    as_of: str,
    equity: float,
    cash: float,
    fills: list[OptionFill],
    settlements: list[OptionSettlement],
) -> Path:
    """Append normalized fill/settlement events without changing broker state."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    recorded_at = datetime.now(UTC).isoformat()
    with out.open("a", encoding="utf-8") as handle:
        for fill in fills:
            handle.write(
                json.dumps(
                    {
                        "recorded_at": recorded_at,
                        "as_of": as_of,
                        "kind": "fill",
                        "instrument": fill.instrument,
                        "side": fill.side,
                        "qty": fill.qty,
                        "premium": fill.premium,
                        "fee": fill.fee,
                        "cash_after": fill.cash_after,
                        "status": fill.status,
                        "reason": fill.reason,
                        "equity": equity,
                        "cash": cash,
                    }
                )
                + "\n"
            )
        for settlement in settlements:
            handle.write(
                json.dumps(
                    {
                        "recorded_at": recorded_at,
                        "as_of": as_of,
                        "kind": "settlement",
                        "instrument": settlement.instrument,
                        "qty": settlement.qty,
                        "intrinsic": settlement.intrinsic,
                        "proceeds": settlement.proceeds,
                        "status": settlement.status,
                        "equity": equity,
                        "cash": cash,
                    }
                )
                + "\n"
            )
    return out


def load_option_events(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows
