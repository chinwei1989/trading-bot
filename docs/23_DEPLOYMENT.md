# 23 — Dashboard Deployment

## The entrypoint error

The project is a Python package under `src/`, so deployment hosts cannot infer a
root Streamlit file. The root entrypoints now exist:

- `streamlit_app.py` — preferred Streamlit Cloud / Render / Docker entrypoint
- `app.py` — compatibility alias for hosts that default to `app.py`

Both add `src/` to `sys.path` and load the read-only dashboard.

If a host asks for a **main file path**, use:

```text
streamlit_app.py
```

Do not point it at `src/tradingbot/ops/dashboard.py`; that bypasses the path
bootstrap.

## Vercel: lite status app

Vercel's Python function bundle limit is 500 MB. Streamlit plus pandas, pyarrow,
polars, plotly, and their dependencies exceeded that limit at 696 MB. The Vercel
entrypoint is therefore a **lite FastAPI status page**, not the full Streamlit
dashboard.

`app.py` exports a real top-level ASGI app:

```python
from fastapi import FastAPI

app = FastAPI()
```

It reads `deploy/status.json` and shows:

- live-capital gate status
- campaign health
- paper equity and unique days for all six deterministic/single-AI campaigns
- a separate seven-agent AI squad paper account
- a 60-second browser refresh

It has no Streamlit, pandas, polars, pyarrow, or plotly dependency, so the Vercel
bundle stays well below 500 MB.

Regenerate the snapshot before redeploying:

```powershell
uv run python scripts/export_deploy_status.py
```

`vercel.json` installs `requirements-vercel.txt`; `.vercelignore` excludes
`requirements.txt`, `pyproject.toml`, and `uv.lock`.

For the **full Streamlit dashboard**, use Streamlit Community Cloud, Render, or
Docker with the repository on a persistent host. Vercel does not persist local
`data/` or `artifacts/`.

Optional Vercel access gate:

```text
DASHBOARD_PASSWORD=use-a-long-random-password
```

The lite app then uses HTTP Basic Auth. It remains read-only.

If the production URL redirects to `vercel.com/sso-api`, the project has
**Vercel Deployment Protection / Vercel Authentication** enabled. That is a
platform-level login, separate from `DASHBOARD_PASSWORD`. To expose the app with
only the app password, disable Vercel Authentication in the project's
Deployment Protection settings; keep `DASHBOARD_PASSWORD` set.

## Streamlit Community Cloud

1. Push the repository.
2. Set the app main file to `streamlit_app.py`.
3. Select **Python 3.12** in Advanced settings.
4. Add `DASHBOARD_PASSWORD` in the app Secrets section if the app is public.
5. Do not add `.env`, broker keys, `data/`, or `artifacts/`.

`requirements.txt` installs only the dashboard dependencies. The dashboard is
read-only and has no order controls.

## Render / Railway / Heroku-style hosts

- `render.yaml` is included for Render.
- `Procfile` is included for Procfile-based hosts.
- Start command:

```text
streamlit run streamlit_app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true
```

## Docker

`Dockerfile` and `.dockerignore` are included:

```powershell
docker build -t tradingbot-dashboard .
docker run --rm -p 8501:8501 tradingbot-dashboard
```

Docker was not installed on the build machine, so the image itself was not built
locally. The Python package build (`uv build`) passed.

The Docker image contains the dashboard code, `config/`, and `web/vendor/`.
It does **not** contain `.env`, secrets, `data/`, or `artifacts/`. Mount those
only if you intentionally want the hosted dashboard to show local evidence.

## Authentication / access gate

Set a host secret:

```text
DASHBOARD_PASSWORD=use-a-long-random-password
```

When present, the dashboard shows a password screen before rendering any data.
When absent, local use is unchanged.

For a public deployment, add at least one more layer:

- reverse proxy with TLS and basic auth or SSO
- firewall / IP allowlist
- SSH tunnel or Tailscale instead of a public port
- no direct exposure of the Streamlit port

Do not expose the dashboard with no authentication. The dashboard is read-only,
but it contains account/equity/strategy data.

## Live refresh

The sidebar has **Auto-refresh**: Off / 30 seconds / 60 seconds / 5 minutes.
It refreshes read data only. It never runs a campaign and never places an order.

All trading jobs are **one-shot daily** Windows scheduled tasks. There is no
24/7 daemon and no intraday order loop:

| Local time | Task |
|---|---|
| 07:00 | deterministic trend/XSMOM campaign |
| 07:15 | single-Jev AI paper lane |
| 07:20 | breakout/reversal/meta sleeves |
| 07:25 | seven-agent AI squad |
| 07:30 | campaign health check |

The dashboard auto-refresh only reads files; it never triggers a cycle or sends
an order.

The full Streamlit dashboard has "Both", "Deterministic", "AI agent", "AI
squad", and "3D Office" views. The AI squad view reads the separate
`artifacts/ai_squad/` account and its latest blackboard.

## Live-trading gate is separate

Dashboard access is not the live-trading gate. Live capital still requires:

- `LIVE_TRADING=YES`
- live broker configuration and keys
- 56 unique paper days
- DSR ≥ 0.95
- PBO ≤ 0.20
- TCA within limits
- no kill switch

The current gate remains **NO_GO**.
