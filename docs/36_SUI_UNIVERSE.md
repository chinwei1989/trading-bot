# 36 · SUI Added to the Main 9-Asset Universe

**Date:** 28 Oct 2026  
**Status:** paper only. This is an evidence-universe change, not a live promotion.

SUIUSDT (`SUI`) is now part of the main daily crypto campaign and the AI
agent/squad universe. The isolated SUI trend lane in `docs/35_SUI_TREND.md`
remains separate and unchanged.

---

## 1. What changed

Added `SUIUSDT` to:

```text
config/base.yaml             daily trend campaign
config/xsmom.yaml            cross-sectional momentum
config/breakout.yaml         breakout sleeve
config/reversal.yaml         reversal sleeve
config/meta.yaml             meta allocator
config/ai_agent.yaml         single-provider AI
config/ai_squad.yaml         eight-agent AI squad
config/pit_universe_crypto.csv
```

The point-in-time universe starts SUI at its Binance listing date,
**2023-05-03**. The main daily bars now contain:

```text
20,987 rows, 9 assets
SUIUSDT: 1,274 rows, 2023-05-03 through 2026-10-27
```

`config/max_history.yaml` intentionally remains an 8-asset historical test:
SUI did not exist for most of that window. The hourly intraday and futures
configs also remain on their original universes for now.

## 2. Evidence reset and archive

Changing the universe changes the strategy. The prior 8-asset paper results are
therefore **not mixed** with the new 9-asset results.

Archived before reset:

```text
artifacts/archive/pre_sui_9asset_20261028_110444/
```

The archive contains the prior deterministic performance/state/risk files,
reports, AI and AI-squad artifacts, campaign health, readiness, and live-gate
snapshots.

After the archive:

- main trend/XSMOM/breakout/reversal/meta paper books were reset;
- single-provider AI and AI-squad books were reset;
- the new 9-asset forward paper window starts again;
- options evidence and the isolated SUI lane were left untouched.

The main trend book opened SUI on the first 9-asset cycle; XSMOM, breakout, and
meta also picked up SUI exposure. The AI agent kept SUI flat; the AI squad risk
critic vetoed SUI. No trade was forced.

## 3. Validation caveat

The previous spot DSR/PBO and walk-forward figures were computed on the
8-asset universe. They are **stale for the new 9-asset strategy** and must be
rerun before any live-capital decision. This change does not promote the spot
lane.

- Spot live gate: still **NO_GO**
- Options live gate: still **NO_GO**
- Live trading remains disabled

## 4. Running the new universe

```powershell
uv run python -m tradingbot --config config/base.yaml download
powershell -ExecutionPolicy Bypass -File scripts/run_campaign.ps1
powershell -ExecutionPolicy Bypass -File scripts/run_sleeves.ps1
powershell -ExecutionPolicy Bypass -File scripts/run_ai_pipeline.ps1
powershell -ExecutionPolicy Bypass -File scripts/run_ai_squad.ps1
```

The isolated SUI lane still runs its own task:

```text
TradingBotSui, daily 07:10 local
```
