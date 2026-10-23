"""Persisted high-water mark for drawdown control."""

from __future__ import annotations

import json
from pathlib import Path


def load_peak(path: str | Path) -> float | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
        return float(payload.get("peak_equity"))
    except (OSError, ValueError, TypeError):
        return None


def save_peak(path: str | Path, peak: float) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"peak_equity": float(peak)}, indent=2), encoding="utf-8")
    return out
