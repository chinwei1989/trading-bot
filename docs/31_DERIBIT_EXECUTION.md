# 31 — Deribit Options Execution Adapter

**Status:** testnet execution adapter built and unit-tested. Live order
submission is deliberately disabled. No live credentials are configured.

**Code:** `src/tradingbot/options/deribit_execution.py`  
**Smoke check:** `scripts/deribit_testnet_check.py`  
**Tests:** `tests/test_deribit_execution.py`

This is only the execution primitive. It is not wired into the AI options
strategy or the paper broker.

---

## 1. What is built

- JSON-RPC client for Deribit testnet and live endpoints.
- `public/auth` with API-key client credentials.
- Read-only account summary, option positions, and open orders.
- Buy and reduce-only sell order primitives.
- Order-state lookup and cancellation.
- Contract parsing.
- Inverse intrinsic-value calculation.
- Local-vs-venue position reconciliation.
- Secret-safe errors.

## 2. What is deliberately not built

- automatic live execution
- live order routing from the AI pipeline
- withdrawal or transfer functions
- API-key creation
- persistent order state machine
- live reconciliation worker
- automatic retries around uncertain order states
- venue-specific margin/liquidation handling
- tax or regulatory reporting

The options live gate remains the authority.

## 3. Environment

Use Deribit testnet first:

```text
DERIBIT_CLIENT_ID
DERIBIT_CLIENT_SECRET
```

Do not commit these values. For production, use a secret manager or environment
variables on the host.

The adapter defaults to:

```text
environment = testnet
base URL    = https://test.deribit.com/api/v2
```

Live endpoint:

```text
https://www.deribit.com/api/v2
```

Live construction requires both `allow_live=True` and `LIVE_TRADING=YES`.
Even then, `place_order()` refuses live orders until a separately reviewed live
execution layer is added.

## 4. Testnet smoke check

Set the two environment variables, then:

```powershell
uv run python scripts/deribit_testnet_check.py
```

It calls only:

```text
private/get_account_summary
private/get_positions
private/get_open_orders_by_currency
```

It places no order.

## 5. Safety behavior

- Default environment: **testnet**
- Live orders: **refused**
- Sell orders: require `reduce_only=True`
- Missing credentials: fail closed
- API errors: raised without secrets
- No withdrawal methods exist
- No order is placed by unit tests

## 6. Inverse contract math

Deribit BTC/ETH options are inverse contracts. The intrinsic value of one
contract in coin is:

```text
call: max(0, settlement_price - strike) / settlement_price
put:  max(0, strike - settlement_price) / settlement_price
```

Example:

```text
call strike 100,000, settlement 110,000
intrinsic = 10,000 / 110,000 = 0.0909 BTC per contract
```

The paper options lane still uses a USD approximation. A live adapter must use
coin-denominated premiums and settlement.

## 7. Reconciliation

`reconcile_positions(local, remote)` compares local instrument quantities with
the venue's option positions and returns:

```text
ok
differences
local_instruments
remote_instruments
```

A live cycle must reconcile at startup and after every fill before accepting a
new order.

## 8. Remaining live blockers

- no live credentials
- no persistent live order-state machine
- no live reconciliation worker
- 1/56 paper days
- 0 forward option fills
- options live gate **NO_GO**
- spot live gate **NO_GO**

No live trading is enabled by this adapter or by this document.
