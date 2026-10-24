# 26 — Deterministic Intraday Paper Lane

**Status:** built, paper-only, running at :01 every hour on completed 1h bars.  
**Account:** separate $10,000 paper account under `artifacts/intraday/`.  
**Scope:** crypto only. US-equity market hours are not handled by this lane.  
**Verified:** one preview cycle and one real paper cycle completed; `TradingBotIntraday` task test returned exit code 0; initial account entered one BNB long.  
**Relationship to the daily campaign:** separate data, account, journal, risk state, heartbeat, and performance. It does **not** replace or alter the validated daily campaign or its 56-day evidence window.

---

## 1. Why this lane exists

The original system makes one decision per day. A daily signal cannot react to an
intraday move, so this lane provides a controlled interval alternative:

- refresh recent Binance bars every hour;
- use only the latest **completed** hourly bar;
- recompute trend, breakout, reversal, XSMOM, and the meta allocator on the
  hourly grid;
- execute through the existing deterministic risk, order manager, and paper
  broker;
- write a separate hourly performance and heartbeat record.

It is **not** a 24/7 market-monitoring daemon. A Windows scheduled task runs one
cycle every hour. Each cycle exits when it is done.

---

## 2. Architecture

```mermaid
flowchart LR
    TASK[TradingBotIntraday<br/>every hour] --> RUN[run --once]
    RUN --> REFRESH[refresh recent Binance bars]
    REFRESH --> STORE[(bars_1h.parquet)]
    STORE --> COMPLETE[drop still-forming bar]
    COMPLETE --> STRAT[trend + breakout + reversal + XSMOM]
    STRAT --> META[meta allocator<br/>hourly grid]
    META --> RISK[deterministic risk<br/>caps + kill switch]
    RISK --> PLAN[plan orders]
    PLAN --> PAPER[PaperBroker<br/>separate account]
    PAPER --> ART[performance + heartbeat + journal]
    ART --> DASH[read-only Intraday dashboard view]
```

The daily campaign is unchanged and runs on its own schedule:

```text
daily bars → daily sleeves → daily meta → daily paper account
```

---

## 3. Interval behavior

| Item | Value |
|---|---|
| Bar interval | `1h` |
| Cycle interval | once per hour |
| Data source | Binance public klines |
| Universe | 8 crypto assets |
| Signal rebalance | every completed bar (`H`) |
| Annualization | 8760 periods/year |
| Execution | paper only |
| Maximum 1h history initially fetched | 1000 bars per symbol |

“Continuous with interval” here means **one decision at each hourly bar close**,
not tick-by-tick and not an always-running order loop.

The task starts at **:01 past the next hour**, then repeats hourly. It uses
`MultipleInstances: IgnoreNew`, so a slow cycle cannot overlap the next one.

---

## 4. Data handling

`src/tradingbot/data/intraday.py`:

1. loads the existing 1h parquet store;
2. fetches recent klines for each symbol;
3. merges on `(timestamp, asset)`, keeping the latest row;
4. drops the still-forming bar using the interval duration;
5. saves the completed-only store.

At 10:15 UTC with `1h` bars, the 10:00 bar is dropped and the 09:00 bar is the
newest usable bar. The strategy never sees the current incomplete bar.

`run_forever` automatically refreshes intraday data before each cycle when
`data.interval != "1d"`.

---

## 5. Strategies

All sleeve lookbacks are expressed in **hourly bars**, not days:

| Sleeve | Hourly lookback | Meaning |
|---|---:|---|
| Trend | 200 | ~8 days of hourly closes |
| Breakout | 55 | ~2.3 days |
| Reversal | 20 | ~20 hours |
| XSMOM | 60 | ~2.5 days |
| Meta | 90 | ~3.75 days |

This is an **intraday variant**. It is not the validated daily strategy with the
same economic horizon. The daily campaign remains the evidence baseline.

The meta allocator uses a `no_trade_band` of 2% to reduce churn. That is a
cost-control measure, not a profitability claim.

---

## 6. Risk and execution

The lane uses the same deterministic machinery:

- per-asset cap: 20%;
- gross cap: 80%;
- minimum cash: 20%;
- maximum drawdown: 25%;
- kill switch: `artifacts/intraday/KILL`;
- 10 bps commission and 5 bps slippage in the paper model;
- order state machine and startup reconciliation;
- separate journal and paper state.

There is no live broker in this lane. The global live gate remains `NO_GO`.

---

## 7. Schedule

| Local time | Task | Mode |
|---|---|---|
| 07:00 | `TradingBotPaperCampaign` | daily deterministic |
| 07:15 | `TradingBotAIPaper` | daily single-Jev AI |
| 07:20 | `TradingBotSleeves` | daily sleeves |
| 07:25 | `TradingBotAISquad` | daily AI squad |
| every hour | `TradingBotIntraday` | hourly intraday paper |
| 07:30 | `TradingBotHealth` | health check |

The intraday task is independent of the daily tasks. It writes to
`artifacts/intraday/`, not to the daily campaign accounts.

---

## 8. Commands

```powershell
# One-time initial fetch / manual refresh
uv run python -m tradingbot --config config/intraday_meta.yaml refresh-bars

# Decision preview; no orders
powershell -ExecutionPolicy Bypass -File scripts/run_intraday_cycle.ps1 -DryRun

# One real paper cycle
uv run python -m tradingbot --config config/intraday_meta.yaml `
  run --mode paper --once --no-evaluate

# Optional foreground loop (not used by the scheduled task)
uv run python -m tradingbot --config config/intraday_meta.yaml `
  run --mode paper --interval 3600 --no-evaluate

# Register the hourly task
powershell -ExecutionPolicy Bypass -File scripts/register_intraday_campaign.ps1

# Check task state
Get-ScheduledTask -TaskName "TradingBotIntraday"
Get-ScheduledTaskInfo -TaskName "TradingBotIntraday"

# Health includes intraday_meta
uv run python -m tradingbot health
```

---

## 9. Dashboard

The Streamlit dashboard has an **Intraday** view showing:

- intraday equity and cash;
- gross exposure and positions;
- latest cycle timestamp;
- orders/fills;
- heartbeat.

The view is read-only. It does not start the task or place orders.

---

## 10. Known limitations

1. **No intraday backtest evidence yet.** The hourly strategy is running forward
   on paper only. Do not describe it as validated.
2. **Hourly horizons are different.** A 200-bar trend on 1h data is not the same
   as a 200-day trend.
3. **Overtrading risk.** Hourly rebalances can lose to fees and slippage. The
   no-trade band only partially mitigates this.
4. **Crypto only.** Binance spot is 24/7. US equities require market-hours and
   corporate-action handling that this lane does not implement.
5. **No tick data or order-book depth.** Execution is simulated at the last
   completed bar close plus configured slippage.
6. **No live path.** The existing live gate still blocks live capital.
7. **Scheduled task, not a daemon.** If the machine is asleep or task scheduler
   is disabled, cycles are skipped; `StartWhenAvailable` helps but is not a
   guarantee of perfect hourly coverage.

---

## 11. How to change the interval

For a different interval, change all of the following together:

1. `data.interval` in `config/intraday_meta.yaml`;
2. `backtest.periods_per_year` (for example 15m → 35040);
3. the task repetition interval;
4. the strategy lookbacks and `no_trade_band`;
5. the initial data limit and data quality checks.

Do not change the interval without rerunning cost, turnover, and drawdown
analysis. The current default is 1h for a reason: 15m is noisier and more
expensive; 4h reacts more slowly.
