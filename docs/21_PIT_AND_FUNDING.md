# 21 — Campaign Health, PIT Universe, Funding Data

**Status:** infrastructure added. Live trading remains **NO_GO**.

---

## 1. Campaign health (TradingBotHealth)

The three paper campaigns now have a fourth scheduled task:

| Task | Time | Purpose |
|---|---|---|
| `TradingBotPaperCampaign` | 07:00 | trend + XSMOM |
| `TradingBotAIPaper` | 07:15 | Jev / AI paper lane |
| `TradingBotSleeves` | 07:20 | breakout + reversal + meta |
| `TradingBotHealth` | 07:30 | verify fresh rows for all six campaigns |

Run it manually:

```powershell
uv run python -m tradingbot health
```

Outputs:

- `artifacts/CAMPAIGN_HEALTH.json`
- `artifacts/CAMPAIGN_HEALTH.md`
- `logs/health.log`

The check requires a performance row whose **Singapore local date** is today, and
the row must be less than 26 hours old. A heartbeat with `status=error` fails the
campaign even when a performance row exists.

The task was registered and the manual run passed:

```text
Campaign health: OK
  trend, xsmom, breakout, reversal, meta, ai — all fresh
```

This does **not** mean the 56-day gate is complete; it only prevents silently
losing days because a scheduled task failed.

---

## 2. PIT universe / listing-aware spans

File: `config/pit_universe_crypto.csv`

The span file records when each asset was actually available:

```text
asset,start,end
ADAUSDT,2018-04-17,
...
BTCUSDT,2017-08-17,
...
SOLUSDT,2020-08-11,
```

`end` is blank for currently live assets. A closed `end` is supported for
delisted assets when a vendor/historical source provides one.

Commands:

```powershell
uv run python -m tradingbot universe-audit
uv run python -m tradingbot universe-build --output config/pit_universe_crypto.csv
```

All crypto configs now point at the span file through `data.universe_path`.
Backtests, walk-forward runs, paper runs, and the operational runner apply the
span filter before generating signals.

### What this fixes

- SOL/DOGE/LINK cannot be used before their listing dates.
- A future delisted asset can be marked with a closed end date and is dropped
  after that date.
- The audit exposes the true start date of every asset.

### What it does not fix

The public Binance data we have contains **current survivors only**. It does not
include every historical exchange listing that later delisted. Therefore this is
**listing-aware PIT**, not a complete historical constituent universe. A truly
survivorship-free crypto universe needs a vendor or archived exchange listing
snapshot. US equities have the same limitation; the current Alpaca/Yahoo data is
not a delisted-inclusive PIT universe.

The next validation run should use the span file and report this limitation
explicitly.

---

## 3. Funding-rate data

Binance USD-M funding is public and requires no API key.

```powershell
uv run python -m tradingbot download-funding `
  --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,LINKUSDT `
  --start 2020-01-01 `
  --output data/normalized/funding.parquet

uv run python -m tradingbot funding-summary --path data/normalized/funding.parquet
```

The download produced **58,193** funding events across the eight assets through
23 Oct 2026. Mean annualized funding over the sample:

| Asset | Mean annualized funding |
|---|---:|
| BTC | ~11.6% |
| ETH | ~13.7% |
| BNB | ~-0.02% |
| SOL | ~0.2% |
| XRP | ~14.5% |
| ADA | ~13.4% |
| DOGE | ~12.3% |
| LINK | ~13.6% |

Funding is **not yet a strategy**. A proper funding/basis carry sleeve needs:

1. spot long + perpetual short, with margin and liquidation handling;
2. both spot and perp price/funding series;
3. exchange fee and borrow/funding cash-flow accounting;
4. a dedicated backtester or two-leg portfolio model.

Do not treat funding rates or a one-leg spot signal as a delta-neutral strategy.
The data layer is in place; the carry sleeve remains a research task.

---

## 4. Next gate implications

The live gate still requires:

- 56 fresh paper days for deterministic sleeves and the AI lane
- DSR ≥ 0.95
- PBO ≤ 0.20
- TCA within limits
- live keys/configuration only after all of the above

Current status remains **NO_GO**. The new health task makes missed campaign days
visible; it does not improve strategy metrics by itself.
