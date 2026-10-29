"""Bounded, read-only operations log view for the dashboard.

Logs can contain API keys, bot tokens, or account identifiers.  The dashboard
must never serve raw log files, so this module only reads an allowlisted set of
operational logs, keeps a bounded tail, and applies conservative redaction
before the data reaches the frontend.  It never writes to the log directory.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_LOG_LINES = 200
MAX_BYTES = 2_000_000

LOG_FILES: tuple[tuple[str, str], ...] = (
    ("campaign.log", "Campaign"),
    ("health.log", "Health"),
    ("sleeves.log", "Sleeves"),
    ("ai_pipeline.log", "AI pipeline"),
    ("ai_squad.log", "AI squad"),
    ("intraday.log", "Intraday"),
    ("sui.log", "SUI lab"),
    ("options_swing.log", "Swing options"),
    ("ai_options_30m.log", "AI options 30m"),
    ("ai_options_eth.log", "ETH options lab"),
    ("ai_options_btc_lab.log", "BTC options lab"),
    ("testnet_canary.log", "Testnet canary"),
)

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # key=value / key: value in plain text or JSON
    (
        re.compile(
            r"""(?i)((?:api[_-]?key|secret|token|password|passwd|authorization|"""
            r"""bearer|private[_-]?key|client[_-]?secret|access[_-]?key)"""
            r"""\s*[:=]\s*)(["']?)([^\s"',;}]+)"""
        ),
        r"\1\2[REDACTED]",
    ),
    # Telegram bot tokens embedded in URLs
    (
        re.compile(r"(?i)(https://api\.telegram\.org/bot)[^/\s]+"),
        r"\1[REDACTED]",
    ),
    # Common provider token prefixes
    (
        re.compile(r"\b(?:sk|pk|ghp|gho|ghs|xox[baprs])[-_][A-Za-z0-9_-]{8,}\b"),
        "[REDACTED]",
    ),
    # Quoted JSON values for secret-looking keys
    (
        re.compile(
            r"""(?i)("(?:api[_-]?key|secret|token|password|passwd|"""
            r"""private[_-]?key|client[_-]?secret)"\s*:\s*")[^"]+"""
        ),
        r"\1[REDACTED]",
    ),
)


def _redact(line: str) -> str:
    for pattern, replacement in _REDACTIONS:
        line = pattern.sub(replacement, line)
    return line


def _tail(path: Path) -> tuple[list[str], bool, int]:
    size = path.stat().st_size
    start = max(0, size - MAX_BYTES)
    with path.open("rb") as handle:
        handle.seek(start)
        raw = handle.read()
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    truncated = start > 0 or len(lines) > MAX_LOG_LINES
    if len(lines) > MAX_LOG_LINES:
        lines = lines[-MAX_LOG_LINES:]
    return [_redact(line) for line in lines], truncated, size


def build_logs_payload(root: Path) -> dict[str, Any]:
    """Return recent, redacted lines from the allowlisted log files."""
    log_dir = root / "logs"
    root_text = str(root)
    home_text = str(Path.home())
    files: list[dict[str, Any]] = []
    for name, label in LOG_FILES:
        path = log_dir / name
        if not path.exists() or not path.is_file():
            continue
        try:
            lines, truncated, size = _tail(path)
            updated = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
        except OSError:
            continue
        lines = [
            line.replace(root_text, "<repo>").replace(home_text, "~")
            for line in lines
        ]
        files.append(
            {
                "name": name,
                "label": label,
                "updated_at": updated,
                "size_bytes": size,
                "truncated": truncated,
                "lines": lines,
            }
        )
    files.sort(key=lambda item: str(item["updated_at"]), reverse=True)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "max_lines": MAX_LOG_LINES,
        "redacted": True,
        "files": files,
    }
