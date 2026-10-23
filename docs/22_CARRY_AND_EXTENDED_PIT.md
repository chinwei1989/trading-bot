# 22 — Carry Research Lane and Extended PIT Universe

**Status:** research only. Neither addition is in the paper/live order path.

---

## 1. Carry data

Public Binance data only; no API key.

```powershell
# USD-M perpetual daily bars
uv run python -m tradingbot --config config/futures.yaml download

# 8-hour funding history
uv run python -m tradingbot download-funding `
  --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,LINKUSDT `
  --start 2020-01-01 `
  --output data/normalized/funding.parquet
```

Current downloads:

- Perpetual bars: **19,347 rows**, 8 assets
- Funding events: **58,193 rows**, 8 assets
- Spot bars: existing 8-asset store

## 2. Two-leg carry model

A position is:

```text
long spot + short USD-M perpetual
```

The model includes:

- spot and perp price returns
- 8-hour funding cash flows, summed to the daily level
- fees/slippage on both legs
- weekly rebalance and minimum-funding filter
- a top-N positive-funding selection
- per-asset and gross caps

It does **not** include:

- exchange margin calls or liquidation
- order-book depth
- spot borrow
- live execution
- a full funding/basis term structure

```powershell
uv run python -m tradingbot carry-backtest
uv run python -m tradingbot carry-walkforward
```

Outputs are written under `artifacts/carry/`.

### Results

Full-sample default parameters looked excellent:

| Metric | Value |
|---|---:|
| CAGR | 8.5% |
| Volatility | 1.5% |
| Sharpe | 5.47 |
| Max drawdown | -1.5% |
| Average funding | 12.8%/yr |

But the full-sample result is **not** evidence for live use. The walk-forward
grid produced:

| Metric | OOS |
|---|---:|
| Sharpe | 0.68 |
| Total return | 7.3% over 4 years |
| Max drawdown | -5.7% |
| DSR | 0.00 |
| PBO | 0.57 |

The carry sleeve is therefore **not added to the meta allocator** and does not
change the live gate. It needs a better regime/term-structure model and more
robust execution assumptions before it is a candidate.

---

## 3. Extended delisted-inclusive PIT sample

The original PIT file is listing-aware but only has current survivors. The
extended research universe adds three delisted Binance spot pairs:

- `BUSDUSDT` (last bar 2023-12-15)
- `SRMUSDT` (last bar 2022-11-28)
- `TOMOUSDT` (last bar 2023-11-20)

`COCOSUSDT` was deliberately excluded: its archive has a redenomination-like
price jump that would create a false ~1,000x return without corporate-action
normalization.

Files:

- `config/pit_universe_crypto_extended.csv`
- `data/normalized/bars_pit_extended.parquet`
- `config/pit_extended.yaml`
- `scripts/build_pit_extended.py`

Run:

```powershell
uv run python scripts/build_pit_extended.py
uv run python -m tradingbot --config config/pit_extended.yaml universe-audit
uv run python -m tradingbot --config config/pit_extended.yaml backtest
```

### Extended-universe result

The full-sample meta backtest returned 233% over 9.2 years (Sharpe ~1.0), but
the walk-forward over the extended universe returned:

| Metric | Extended OOS |
|---|---:|
| Sharpe | 1.04 |
| Max drawdown | -22.3% |
| DSR | 0.13 |
| PBO | 0.05 |

This does **not** pass the live gate. It is useful because it shows that the
original current-survivor universe was more flattering than the extended
sample.

### Remaining limitation

This is a **bounded** delisted-inclusive sample, not a complete historical
exchange universe. A true crypto PIT universe needs:

1. all historical exchange listings, including every delisted pair;
2. monthly liquidity/volume-based membership;
3. corporate-action/redenomination normalization;
4. delisting returns and last-trade handling.

The extended sample is a reproducibility bridge, not a claim that survivorship
bias is solved.

---

## 4. Gate impact

No change:

- live gate remains **NO_GO**
- carry is not in meta
- extended PIT is a separate research config
- paper campaigns continue on the original 8-asset config
