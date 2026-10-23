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

## Vercel

Vercel expects a top-level ASGI/WSGI variable in `app.py`. The repository now
exports:

```python
from streamlit.starlette import App

app = App("streamlit_app.py")
```

`vercel.json` sets a minimal build command, and `.vercelignore` excludes the
large `pyproject.toml`/`uv.lock` dependency graph so Vercel installs the
dashboard-only `requirements.txt` instead. `requirements.txt` includes
`streamlit[starlette]` and `uvicorn[standard]`.

Use **`app.py`** as the Vercel entrypoint. The local ASGI check works with:

```powershell
uv run uvicorn app:app --host 127.0.0.1 --port 8504
```

Caveat: Vercel Functions are serverless and the `maxDuration` in `vercel.json`
is 60 seconds. The ASGI app was verified locally with uvicorn; it is not a
replacement for a persistent Streamlit host. Streamlit keeps a long-lived session/WebSocket open, so Vercel
may disconnect during normal use. For a stable always-on dashboard, use
Streamlit Community Cloud, Render, or a container host rather than Vercel.

Vercel also does not persist local `data/` or `artifacts/`; the hosted dashboard
will be empty unless those are mounted from external storage.

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

The trading campaigns still run on their Windows scheduled tasks at 07:00,
07:15, and 07:20, with health at 07:30.

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
