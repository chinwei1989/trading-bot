# 34 · Isolated Options Scope Labs

**Status:** two separate paper-only accounts. Neither is part of the 56-day
options evidence window.

**Code:** `src/tradingbot/options/ai_pipeline.py`  
**Configs:** `config/ai_options_eth_paper.yaml`, `config/ai_options_btc_lab.yaml`  
**Tasks:** `TradingBotAIOptionsEth` every 30 minutes; `TradingBotAIOptionsBtcLab`
daily at 07:45 local

The canonical evidence account remains `config/ai_options_30m.yaml` with its own
state under `artifacts/ai_options_30m/`. The labs exist to answer two separate
questions without touching that account.

---

## 1. Account boundaries

| Lane | Capital | Underlying | Artifacts |
|---|---:|---|---|
| Evidence account | $10,000 | BTC + ETH | `artifacts/ai_options_30m/` |
| ETH-only lab | $10,000 | ETH | `artifacts/ai_options_eth/` |
| BTC contract lab | $100,000 | BTC | `artifacts/ai_options_btc_lab/` |

All three use the paper broker, Deribit public option chains, long premium only,
and the same deterministic contract/account gates. No lab has a live order path.

The $100,000 BTC account is **paper-only test capital**, not real capital and
not a request to raise live risk.

## 2. Underlying selection

The AI options pipeline derives its underlyings from `data.symbols`:

```text
BTCUSDT -> BTC
ETHUSDT -> ETH
```

The bars, option chain, AI context, directions, diagnostics, and report are all
restricted to the configured symbols. Unsupported symbols are rejected. This
means the ETH lab cannot quietly open a BTC position, and the BTC lab cannot
open an ETH position.

## 3. What the labs test

- **ETH-only:** whether ETH contracts fit the current $10k budget and whether
  the AI approves a direction. No forced trades. If the AI is flat or the
  contract gate rejects every ETH contract, the account stays in cash.
- **BTC contract lab:** whether BTC contracts are affordable and executable at
  $100k paper capital under the same premium and contract gates. This is a
  plumbing/affordability check, not evidence of a BTC edge.

## 4. Commands

```powershell
uv run python -m tradingbot --config config/ai_options_eth_paper.yaml ai-options-run
uv run python -m tradingbot --config config/ai_options_btc_lab.yaml ai-options-run

powershell -ExecutionPolicy Bypass -File scripts/run_ai_options_lab.ps1 -Lane eth
powershell -ExecutionPolicy Bypass -File scripts/run_ai_options_lab.ps1 -Lane btc-lab
powershell -ExecutionPolicy Bypass -File scripts/register_ai_options_labs.ps1
```

Reports:

```text
artifacts/ai_options_eth/reports/latest.json
artifacts/ai_options_btc_lab/reports/latest.json
```

The Streamlit **AI options 30m** view shows all three accounts in separate tabs.
The public Vercel snapshot exposes the two labs as read-only lane cards.

## 5. Current readings

At the first run on 27 Oct 2026:

- ETH lab: AI flat; no ETH contract passed the DTE/spread/OI gates.
- BTC lab: AI flat; one BTC long contract passed the contract gate
  (`BTC-6NOV26-81000-C`), proving the $100k budget can fund BTC plumbing, but
  no trade was forced.

Both accounts remain at their starting equity. The labs do not change the
evidence count; live options remain **NO_GO**.
