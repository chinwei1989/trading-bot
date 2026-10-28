"""Local read-only JSON API for the Next.js dashboard."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from tradingbot.ops.ai_summary import build_ai_state_summary
from tradingbot.ops.frontend_data import build_dashboard_payload

ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title="NOVA Dashboard API", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "paper_only": True, "order_access": False}


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    return build_dashboard_payload(ROOT)


@app.post("/api/ai-gist/regenerate")
def regenerate_gist() -> dict[str, Any]:
    try:
        result = build_ai_state_summary(ROOT)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc
    return {"status": "ok", "ai_gist": result}
