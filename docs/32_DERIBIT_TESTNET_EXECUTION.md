# 32 — Deribit Testnet Persistent Execution

**Status:** testnet-only execution layer, unit-tested and tested against Deribit
testnet. Live order submission remains disabled.

**Code:** `src/tradingbot/options/deribit_testnet.py`  
**Tests:** `tests/test_options_deribit_testnet.py`

This layer sits on top of the execution primitives in
`src/tradingbot/options/deribit_execution.py`. It is not wired into the AI
options strategy or the live gate.

---

## 1. What this layer adds

- SQLite order state written **before** venue submission
- SQLite aggregate fill records
- deterministic idempotency keys
- duplicate active-order protection
- canary limits for testnet orders
- restart reconciliation by venue order id or label
- local position reconstruction from filled amounts
- remote/local position comparison

## 2. State store

`TestnetOrderStore` persists:

- `testnet_orders`: intent, venue order id, state, filled amount, average price,
  fee, and errors
- `testnet_order_events`: append-only state transitions
- `testnet_fills`: aggregate fill deltas when the venue reports more filled amount

The store is SQLite and can be reopened by a new process. The default test path
should live under `artifacts/` and must not be committed with credentials.

## 3. Idempotency and duplicate protection

Every order gets a deterministic idempotency key:

```text
instrument | side | amount | order_type | price | reduce_only
```

Calling `submit()` twice with the same key returns the existing order rather
than placing another order. A different key for the same instrument while an
order is open is rejected by the canary guard.

This is not a substitute for a venue-side client order id, but the Deribit
`label` is set to the local client order id.

## 4. Canary limits

Defaults:

```text
max contracts       1
max premium         0.01 coin
max open orders     1
max orders/day      10
underlyings         BTC, ETH
minimum DTE         1
maximum DTE         365
```

Buy orders must be limit orders. Sells must be `reduce_only`. A close is
allowed to bypass the premium, open-order, and daily limits so an exit is not
blocked.

The canary guard is intentionally strict. It is a testnet safety layer, not a
live risk policy.

## 5. Restart sequence

On startup:

1. Fetch open orders from the venue.
2. Reconcile local open intents by venue order id.
3. If a local intent has no venue id, adopt a matching open order by label.
4. Refresh every resolved order from `private/get_order_state`.
5. Report untracked venue open orders as issues.
6. Reconstruct local positions from filled amounts.
7. Fetch remote option positions and compare.

If an order was submitted but the process died before the venue id was
persisted, the layer reports it as unresolved rather than blindly resubmitting
it. That is intentional: uncertain state must be investigated.

## 6. Testnet evidence

A real testnet fill/close was completed:

```text
instrument     BTC-6NOV26-70000-P
buy fill       1 @ 0.002 BTC
sell fill      1 @ 0.0019 BTC, reduce_only
final position 0
open orders    0
```

A real testnet restart/open/cancel test also completed:

```text
submit                 OPEN
reopen state           resolved 1, issues 0
idempotent replay      no second order
cancel                 CANCELLED
final reconciliation   flat, issues 0
```

No live order was placed.

## 7. Known limitations

- No individual trade-record ingestion; fills are aggregate deltas.
- The crash window between venue acceptance and local venue-id persistence is
  reported as unresolved, not auto-repaired.
- No automatic cancellation of untracked venue orders.
- No live adapter.
- No automatic canary activation in the AI pipeline yet.
- No live credential storage in this repository.

## 8. Live status

The options live gate remains **NO_GO**. This module does not enable live
trading and must not be used with live credentials.
