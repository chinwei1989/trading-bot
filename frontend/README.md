# NOVA Next.js dashboard

Read-only Next.js frontend for the Python trading bot.

## Local live dashboard

Terminal 1 — Python JSON API:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_next_api.ps1
```

Terminal 2 — Next.js UI:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_next_dashboard.ps1
```

Open <http://127.0.0.1:3000>.

The frontend uses `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000` in local mode.
The API is read-only except for `POST /api/ai-gist/regenerate`, which asks Jev
for a new paper gist and writes the existing `artifacts/ai_summary/latest.json`.
It has no broker or order access.

## Static Vercel snapshot

Generate the snapshot:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\export_frontend_snapshot.ps1
```

The snapshot is written to:

```text
frontend/public/dashboard.json
deploy/dashboard.json
```

Deploy this `frontend` directory as a Next.js Vercel project **without**
`NEXT_PUBLIC_API_URL`. The public page reads `dashboard.json` and the AI gist
regenerate button is disabled because there is no live API.

The Vercel project **Root Directory must be `frontend`**. If the project is
still rooted at the repository root, Vercel runs the root `vercel.json` and
tries `pip install -r requirements-vercel.txt`, which can fail with
`externally-managed-environment`. This `frontend/vercel.json` explicitly tells
Vercel to use Next.js, but it only applies when the project root is `frontend`.

Set `DASHBOARD_PASSWORD` in the Vercel project before publishing. The
`middleware.ts` gate redirects unauthenticated requests to `/login`; the
snapshot JSON is protected by the same gate. Vercel Deployment Protection is
still recommended as a second layer.

## Routes

- `/` — landing, AI gist, portfolio, lanes, 7D performance, readiness
- `/holdings` — exposure, P&L, SUI, positions, option holdings
- `/performance` — Today / 7D / 30D / 3M / 1Y / All
- `/readiness` — paper health and live gates
- `/options` — options lanes, evidence, and gate failures
