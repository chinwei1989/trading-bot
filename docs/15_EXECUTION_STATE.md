# 15 — Execution State Machine and Reconciliation

**Purpose:** make live/paper order handling restart-safe and prevent duplicate or orphan orders.

---

## 1. Order lifecycle

Every order gets a deterministic `client_order_id` and a persisted intent:

```text
NEW
  → SUBMITTED
  → ACKNOWLEDGED
  → PARTIAL
  → FILLED

Failure branches:
  SUBMITTED → UNKNOWN
  ACKNOWLEDGED → CANCELED
  SUBMITTED → REJECTED
```

The state is stored in SQLite:

```text
artifacts/order_state_{strategy}.sqlite
```

If the process crashes after submission, the next run sees `SUBMITTED`/`UNKNOWN`/`PARTIAL` and **does not blindly resubmit**. It queries the broker by `client_order_id` first.

---

## 2. Idempotency rules

- `client_order_id` is generated from date, asset, side, and quantity.
- Re-running the same plan does not create a second order.
- A `FILLED` intent is a no-op on later runs.
- A `REJECTED`/`CANCELED` intent is terminal; the planner must create a new intent to retry.
- An `UNKNOWN` intent blocks new trading until reconciled.
- A `PARTIAL` intent whose broker order is still open is left alone; it is not resubmitted.
- When a partial is terminal (not open at the broker), the manager submits the remaining quantity as a child intent (`...-r1`, `...-r2`) up to the retry limit. Child orders are persisted and idempotent.

---

## 3. Startup reconciliation

Before planning orders, `OrderManager.assert_reconciled()`:

1. Loads every open intent.
2. Queries the broker by `client_order_id`.
3. Applies the latest known fill/status.
4. Checks broker open orders for untracked orders.
5. Completes terminal partial fills through child intents.
6. Raises `ReconciliationError` if anything is unresolved.

If reconciliation fails, the runner writes an error heartbeat, sends an alert, and stops. It does **not** place new orders.

### Order chunking

`broker.max_child_notional` and `broker.max_children` can split a large order into deterministic child orders (`...-s1`, `...-s2`). This is **order chunking**, not time-based TWAP. It reduces single-order market impact in paper/live adapters; intraday TWAP scheduling is not implemented in the daily runner.

---

## 4. Broker support

| Broker | submit | query by client ID | list open orders |
|---|---|---|---|
| Paper | Yes | In-memory | Always empty |
| Alpaca | Yes | `get_order_by_client_id` | `get_orders(status=OPEN)` |
| ccxt | Yes | tracked ID + `fetch_order` | `fetch_open_orders` |

ccxt client-order-ID support varies by venue. The manager keeps a local mapping; if the venue does not echo the client ID, query by the stored broker order ID through the local mapping.

---

## 5. Inspect state

```powershell
uv run python -c "import sqlite3; c=sqlite3.connect('artifacts/order_state_trend.sqlite'); print(c.execute('select client_order_id,status,filled_qty,broker_order_id from order_intents order by created_at').fetchall())"
```

Or open the SQLite file in any viewer.

---

## 6. What is still manual

- Resolving a genuinely ambiguous `UNKNOWN` order when the broker has no record.
- Flattening a live account after a reconciliation break.
- Deciding whether to keep retrying a partial after the child retry limit.
- Promoting a strategy to live.

These are intentional safety boundaries. TWAP/VWAP scheduling is not implemented.

---

## 7. Tests

The test suite covers:

- state create/update/apply
- full fill + idempotent re-execution
- partial fill while still open → no resubmission
- terminal partial → remainder child completed
- order chunking into deterministic children
- untracked broker open order → reconciliation failure

Run:

```powershell
uv run pytest -q
```

Current suite: **89 tests**.
