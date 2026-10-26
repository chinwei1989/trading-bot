"""Read-only reconciliation of the local Deribit testnet order state.

This never places, cancels, or modifies an order. It reads the local SQLite
state and the testnet account, reports open orders and position differences,
and exits nonzero when reconciliation is not clean.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from tradingbot.options.deribit_execution import DeribitExecutionClient
from tradingbot.options.deribit_testnet import TestnetExecutor, TestnetOrderStore

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / "artifacts" / "ai_options_30m" / "testnet_orders.sqlite"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    args = parser.parse_args()

    store = TestnetOrderStore(args.state)
    try:
        with DeribitExecutionClient(environment="testnet") as client:
            report = TestnetExecutor(client, store).reconcile_startup()
    finally:
        store.close()

    print(f"reconciliation_ok={report.ok}")
    print(f"open_orders={len(report.open_orders)}")
    print(f"resolved_orders={len(report.resolved)}")
    print(f"local_positions={report.local_positions}")
    print(f"remote_positions={[(p.instrument, p.size) for p in report.remote_positions]}")
    for issue in report.issues:
        print(f"issue: {issue}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
