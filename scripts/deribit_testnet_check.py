"""Read-only Deribit testnet smoke check.

Requires DERIBIT_CLIENT_ID and DERIBIT_CLIENT_SECRET in the environment. It
never places, cancels, or modifies an order. It prints no credentials.
"""

from __future__ import annotations

from tradingbot.options.deribit_execution import DeribitExecutionClient


def main() -> int:
    try:
        with DeribitExecutionClient(environment="testnet") as client:
            summary = client.account_summary("BTC")
            positions = client.positions("BTC")
            orders = client.open_orders("BTC")
    except PermissionError as exc:
        print(f"testnet check blocked: {exc}")
        return 1
    except Exception as exc:
        print(f"testnet check failed: {type(exc).__name__}: {exc}")
        return 1
    print(
        "testnet ok: "
        f"equity={summary.get('equity')} "
        f"positions={len(positions)} "
        f"open_orders={len(orders)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
