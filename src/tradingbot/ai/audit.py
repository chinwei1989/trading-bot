"""Append-only audit trail for AI decisions.

Only market context, model responses, policy output, and order intent are
recorded. API keys are never written.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _json_default(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def write_audit(
    root: Path,
    *,
    as_of: str,
    provider: str,
    model: str,
    request: dict[str, Any],
    response: dict[str, Any],
    decision: dict[str, Any],
    policy: dict[str, Any],
    orders: list[dict[str, Any]],
    fallback: bool,
) -> Path:
    out_dir = root / "artifacts" / "ai" / "audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = out_dir / f"{stamp}_{provider}.json"
    payload = {
        "as_of": as_of,
        "provider": provider,
        "model": model,
        "fallback": fallback,
        "request": request,
        "response": response,
        "decision": decision,
        "policy": policy,
        "orders": orders,
        "request_hash": hashlib.sha256(
            json.dumps(request, sort_keys=True, default=_json_default).encode()
        ).hexdigest(),
        "created_at": datetime.now(UTC).isoformat(),
    }
    path.write_text(
        json.dumps(payload, indent=2, default=_json_default),
        encoding="utf-8",
    )
    return path


def append_decision(root: Path, payload: dict[str, Any]) -> Path:
    """Append one decision to the AI decision history for evaluation."""
    out = root / "artifacts" / "ai" / "decisions.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    record = {"created_at": datetime.now(UTC).isoformat(), **payload}
    with out.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, default=_json_default) + "\n")
    return out


def write_report(
    root: Path,
    *,
    report: dict[str, Any],
    markdown: str,
) -> tuple[Path, Path]:
    out_dir = root / "artifacts" / "ai" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "latest.json"
    json_path.write_text(
        json.dumps(report, indent=2, default=_json_default),
        encoding="utf-8",
    )
    date = str(report.get("as_of", ""))[:10] or datetime.now(UTC).date().isoformat()
    md_path = out_dir / f"ai_{date}.md"
    md_path.write_text(markdown, encoding="utf-8")
    (out_dir / "latest.md").write_text(markdown, encoding="utf-8")
    return json_path, md_path
