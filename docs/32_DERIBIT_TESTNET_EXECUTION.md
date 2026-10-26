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

The scheduled canary was also tested end to end:

```text
open-only process      left one order OPEN
new recover process    reconciled and CANCELLED it
final reconciliation   flat, issues 0
scheduled task         TradingBotDeribitCanary, LastResult 0
daily health           canary ok, open orders 0, positions 0
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

## 8. Scheduled canary

The scheduled task is:

```text
TradingBotDeribitCanary
daily at 06:45 local
```

It runs `scripts/run_deribit_testnet_canary.ps1`, which loads the testnet
credentials from the Windows user environment into the child process without
printing them.

The daily cycle:

1. reconciles local state and the testnet account;
2. cancels tracked stale canary orders if necessary;
3. places one far-from-market testnet limit order;
4. verifies it is open;
5. cancels it;
6. reconciles back to flat.

The latest result is written to:

```text
artifacts/ai_options_30m/testnet_canary/latest.json
artifacts/ai_options_30m/testnet_canary/latest.md
```

`scripts/check_testnet_canary.py` validates freshness, status, open orders, and
positions. `scripts/run_health.ps1` now runs that check as part of daily health.

Manual restart test:

```powershell
powershell -File scripts/run_deribit_testnet_canary.ps1 --mode open-only
powershell -File scripts/run_deribit_testnet_canary.ps1 --mode recover-only
```

The first command leaves a testnet order open. The second command runs in a new
process, reconciles it, cancels it, and verifies the account is flat.

## 9. Live status

The options live gate remains **NO_GO**. This module does not enable live
trading and must not be used with live credentials.
