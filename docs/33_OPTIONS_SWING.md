# 33 — BTC/ETH Swing Options Paper Lane

**Status:** deterministic paper-only swing lane. No live order path.

**Code:** `src/tradingbot/options/swing.py`  
**Config:** `config/options_swing.yaml`  
**Tests:** `tests/test_options_swing.py`  
**Task:** `TradingBotOptionsSwing`, daily at 07:40 local

The lane is separate from the 30-minute AI options lane and from every spot
account. It uses `artifacts/options_swing/` for state and reports.

---

## 1. Signal

Daily BTCUSDT/ETHUSDT bars only; the still-forming daily bar is excluded.

```text
long:  close > SMA50 > SMA200 and 20-day momentum > 0
short: close < SMA50 < SMA200 and 20-day momentum < 0
flat:  otherwise
```

A long signal buys a call. A short signal buys a put. There are no naked
short options.

## 2. Contract gate

```text
DTE                  21–45 days
delta                0.40–0.60
max spread           5%
minimum open interest 100
underlyings          BTC, ETH
```

Only long premium is permitted.

## 3. Position sizing

```text
max open legs               2
max legs per underlying     1
max premium per trade       2% of equity
max total premium           5% of equity
minimum cash                20% of equity
max contracts per trade     1
```

## 4. Exits

Every daily cycle marks the chain and exits when any condition is true:

- profit target: mark ≥ entry premium × 1.50
- stop loss: mark ≤ entry premium × 0.50
- DTE ≤ 7
- trend reversal or flat signal
- holding period ≥ 20 calendar days

Exits use the current bid. If there is no bid, the position is retained and an
alert is written.

## 5. State and reports

```text
artifacts/options_swing/paper_state.json
artifacts/options_swing/performance.jsonl
artifacts/options_swing/heartbeat.json
artifacts/options_swing/fills.jsonl
artifacts/options_swing/reports/latest.json
artifacts/options_swing/reports/latest.md
```

## 6. Running

```powershell
uv run python -m tradingbot --config config/options_swing.yaml options-swing-run
```

The scheduled task runs the same command daily at 07:40 local through
`scripts/run_options_swing.ps1`.

## 7. Current result

The initial real-chain paper cycle was flat:

```text
BTC: flat, 20d momentum -6.52%
ETH: flat, 20d momentum -13.50%
fills: 0
positions: 0
equity: $10,000.00
```

That is the strategy refusing to trade without trend/momentum alignment. It is
not evidence of profitability.

## 8. Limitations

- Long premium only; theta and spreads are material costs.
- No continuous historical options chain; only current public chain plus one
  free Tardis day.
- No claim of profitability.
- No live adapter, live credentials, or live order path.
- This lane does not count as the 30-minute AI options evidence.
