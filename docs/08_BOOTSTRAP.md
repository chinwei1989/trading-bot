# 08 — Bootstrap: Exact Setup for This PC

**Machine:** Windows 11, Ryzen AI 9 HX 470, 28 GB RAM, 646 GB free, WSL2 Ubuntu installed, Git installed, Python not installed (Store stub only).  
**Goal:** a reproducible Python 3.12 environment, first data download, and a smoke-test backtest.

---

## 1. Install Python 3.12 with uv (Windows)

### Option A — winget (recommended)

Open **PowerShell** (not admin unless needed):

```powershell
winget install --id astral-sh.uv -e
```

Close and reopen PowerShell, then:

```powershell
uv --version
uv python install 3.12
uv python list
```

### Option B — official install script

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then:

```powershell
uv --version
uv python install 3.12
```

### Why uv

- Fast, reproducible, handles Python versions and lockfiles.
- Avoids the Microsoft Store Python alias trap.
- Works well with Nautilus/Freqtrade if you keep their environments separate.

### Verify

```powershell
uv run --python 3.12 python -c "import sys; print(sys.version)"
```

Expected: Python 3.12.x.

---

## 2. Create the project environment

From `C:\projects\tradingbot`:

```powershell
uv venv --python 3.12
.\.venv\Scripts\Activate.ps1
uv pip install --upgrade pip
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then install the core stack:

```powershell
uv add polars pandas pyarrow duckdb numpy scipy statsmodels scikit-learn lightgbm xgboost optuna mlflow quantstats matplotlib plotly pydantic pydantic-settings pyyaml httpx tenacity structlog exchange-calendars pandas-market-calendars ccxt alpaca-py riskfolio-lib skfolio pytest hypothesis ruff mypy
```

Optional (large, install later):

```powershell
uv add "nautilus_trader==1.231.0"
uv add transformers torch shap
```

**Do not** install Freqtrade into the same environment; use its own venv or Docker. Dependency conflicts are likely.

### Verify imports

```powershell
uv run python -c "import polars, duckdb, numpy, pandas, sklearn, lightgbm, ccxt, alpaca; print('ok')"
```

---

## 3. Git and repo hygiene

```powershell
git init
git add .
git commit -m "Initial research and project skeleton"
```

Create `.gitignore` (already included in this repo):

```gitignore
.venv/
__pycache__/
*.pyc
.env
data/raw/
data/normalized/
data/features/
artifacts/
mlruns/
*.parquet
*.duckdb
*.sqlite
.pytest_cache/
.ruff_cache/
.mypy_cache/
```

**Never commit API keys.** Use `.env` locally and `.env.example` in git.

---

## 4. WSL2 Ubuntu (recommended for production)

The machine already has Ubuntu registered.

```powershell
wsl -d Ubuntu
```

Inside Ubuntu:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y build-essential curl git python3.12 python3.12-venv python3-pip
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
uv --version
```

Create the project in the Linux filesystem (faster than `/mnt/c`):

```bash
mkdir -p ~/tradingbot
cd ~/tradingbot
uv venv --python 3.12
source .venv/bin/activate
uv pip install polars pandas pyarrow duckdb numpy scipy statsmodels scikit-learn lightgbm xgboost optuna mlflow quantstats matplotlib plotly pydantic pydantic-settings pyyaml httpx tenacity structlog exchange-calendars pandas-market-calendars ccxt alpaca-py pytest hypothesis ruff mypy
```

**Data location:** keep data in WSL (`~/tradingbot/data`) for performance; back it up to Windows/external drive.

**Access from Windows:** `\\wsl$\Ubuntu\home\<user>\tradingbot`.

**Run at startup:** use systemd services (preferred) or `cron` with `@reboot`.

---

## 5. Accounts and keys (manual)

### Alpaca (US stocks, paper)

1. Sign up at https://alpaca.markets/
2. Open **Paper Trading**.
3. Generate API keys (paper).
4. Store in `.env`:
   ```dotenv
   ALPACA_API_KEY=...
   ALPACA_SECRET_KEY=...
   ALPACA_BASE_URL=https://paper-api.alpaca.markets
   ALPACA_DATA_URL=https://data.alpaca.markets
   ```
5. Verify:
   ```powershell
   uv run python -c "from alpaca.trading.client import TradingClient; import os; c=TradingClient(os.environ['ALPACA_API_KEY'], os.environ['ALPACA_SECRET_KEY'], paper=True); print(c.get_account().status)"
   ```

### FRED (macro)

1. Request a free API key: https://fred.stlouisfed.org/docs/api/api_key.html
2. Add `FRED_API_KEY=...` to `.env`.

### Crypto exchange (paper/testnet)

- **Kraken**: create API key with read + trade (no withdraw), use sandbox where available.
- **Coinbase**: Advanced Trade API keys; start with read-only.
- **Binance**: testnet keys if jurisdiction allows; do not use if US-person restrictions apply.
- Store keys in `.env`; never enable withdrawals.

### X API (optional, later)

1. Sign up at https://console.x.com/
2. Add credits; set a spending limit.
3. Store bearer token in `.env`.
4. Start with 7-day recent search; only buy full-archive if a specific hypothesis requires it.

### Tiingo (optional, $30/mo)

1. https://www.tiingo.com/
2. Get API token; add `TIINGO_API_KEY=...`.

---

## 6. First data download (free)

### 6.1 Binance Vision (crypto)

Use the public ZIPs. Example PowerShell:

```powershell
$base = "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1d"
$file = "BTCUSDT-1d-2026-09.zip"
Invoke-WebRequest "$base/$file" -OutFile "data/raw/binance/$file"
Expand-Archive "data/raw/binance/$file" -DestinationPath "data/raw/binance/"
```

Better: write a Python downloader that:
- iterates months,
- checks HTTP 404 (no data),
- verifies checksums if available,
- writes a manifest.

**Note:** spot timestamps are microseconds from 1 Jan 2025; normalize to UTC.

### 6.2 Alpaca (stocks)

```python
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
import os, datetime as dt

client = StockHistoricalDataClient(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"])
req = StockBarsRequest(
    symbol_or_symbols=["SPY", "QQQ"],
    timeframe=TimeFrame.Day,
    start=dt.datetime(2010, 1, 1),
    end=dt.datetime(2026, 10, 1),
    adjustment="all",
)
bars = client.get_stock_bars(req)
df = bars.df.reset_index()
print(df.head(), len(df))
```

### 6.3 FRED (macro)

```python
import os, httpx, polars as pl

key = os.environ["FRED_API_KEY"]
series = ["DFF", "DGS2", "DGS10", "VIXCLS", "BAMLH0A0HYM2", "DTWEXBGS", "CPIAUCSL", "UNRATE", "PAYEMS", "WALCL"]
rows = []
for s in series:
    r = httpx.get("https://api.stlouisfed.org/fred/series/observations", params={
        "series_id": s, "api_key": key, "file_type": "json",
        "observation_start": "2000-01-01",
    }, timeout=30)
    r.raise_for_status()
    for o in r.json()["observations"]:
        rows.append({"series": s, "date": o["date"], "value": o["value"]})
df = pl.DataFrame(rows)
print(df.head(), df.shape)
```

For backtests, use **ALFRED vintages** (`realtime_start`/`realtime_end`) for revised series.

---

## 7. Smoke-test backtest (no framework)

```python
import polars as pl

# prices: columns [date, asset, close]
prices = pl.read_parquet("data/normalized/bars/frequency=1d/**/*.parquet")

# 12-month trend signal, long/flat, vol-targeted
df = (
    prices.sort(["asset", "date"])
    .with_columns(
        ret=pl.col("close").pct_change().over("asset"),
        mom12=pl.col("close").pct_change(252).over("asset"),
        vol20=pl.col("ret").rolling_std(20).over("asset") * (252 ** 0.5),
    )
    .with_columns(
        signal=(pl.col("mom12") > 0).cast(pl.Float64),
        weight=(pl.col("signal") * 0.10 / pl.col("vol20").clip(0.05, 1.0)),
    )
)

# shift signal by 1 day: trade next bar
df = df.with_columns(weight=pl.col("weight").shift(1).over("asset").fill_null(0))

# daily portfolio return (simplified, equal-weight across active assets)
port = (
    df.group_by("date")
    .agg((pl.col("weight") * pl.col("ret")).sum() / pl.col("weight").abs().sum().clip(1e-9))
    .sort("date")
)
equity = (1 + port["ret"].fill_null(0)).cum_prod()
print(equity.tail())
```

This is a **toy**. It ignores costs, rebalancing, and proper vol targeting. The real backtester must handle those.

---

## 8. First-week checklist

- [ ] `uv --version` works.
- [ ] Python 3.12 installed.
- [ ] Repo initialized; `.venv` created.
- [ ] Core imports pass.
- [ ] Alpaca paper account + keys.
- [ ] FRED key.
- [ ] BTC/ETH daily + hourly downloaded.
- [ ] SPY/QQQ daily downloaded.
- [ ] 10 FRED series downloaded.
- [ ] Data audit notebook: row counts, missing dates, duplicates, outliers.
- [ ] One chart: BTC vs SPY vs 10y yield.
- [ ] One toy trend backtest with next-bar fills.
- [ ] Commit the code, not the data.

---

## 9. Common Windows issues

| Problem | Fix |
|---|---|
| `python` opens Microsoft Store | Install via `uv`; use `uv run python` |
| PowerShell blocks activation | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| TA-Lib build fails | Use Polars/NumPy indicators or Nautilus indicators; avoid TA-Lib initially |
| SSL certificate errors | Update Windows; use `certifi`; check proxy/VPN |
| Long path errors | Enable long paths in Windows; keep repo path short |
| WSL `/mnt/c` slow | Store data in WSL filesystem |
| Sleep interrupts bot | Power settings: never sleep; use UPS |
| Windows Update reboots | Schedule active hours; use a dedicated machine/VM |
| Clock drift | Enable Windows time sync; use UTC everywhere |

---

## 10. Security checklist

- [ ] API keys are trade-only, **withdrawals disabled**.
- [ ] IP allowlist enabled where supported.
- [ ] 2FA on broker/exchange accounts.
- [ ] Separate account/sub-account for the bot.
- [ ] Keys in `.env`/Credential Manager, never in git.
- [ ] Backups encrypted; restore tested.
- [ ] Dedicated Windows user for trading.
- [ ] No remote desktop exposed to the internet.
- [ ] Alerting on failed logins/API errors.

---

## 11. Next step

Once the checklist passes, open `docs/04_IMPLEMENTATION_PLAN.md` and start **Phase 1**: build the normalized Parquet store, the cost model, and the backtester. Don't skip to strategy optimization.

**First real milestone:** reproduce buy-and-hold SPY and a 12-month trend strategy on BTC/SPY with next-bar fills and realistic costs. If those don't reconcile, fix the plumbing before adding complexity.
