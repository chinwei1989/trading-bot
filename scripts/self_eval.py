"""Run the local code and operational self-evaluation.

This is deliberately read-only with respect to trading. It runs the test suite,
lint, type checks, package build, campaign health, and the live gate, then writes
a compact readiness report. The live gate may remain NO_GO and is reported as a
safety result, not hidden.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts"


def _uv() -> str:
    found = shutil.which("uv")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "uv.exe"
    if local.exists():
        return str(local)
    raise FileNotFoundError("uv is not installed or not on PATH")


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1][:240] if lines else ""


def _run(
    name: str,
    args: list[str],
    *,
    timeout: int = 900,
    allowed_codes: tuple[int, ...] = (0,),
) -> dict[str, Any]:
    started = time.monotonic()
    completed = subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    elapsed = time.monotonic() - started
    output = completed.stdout + "\n" + completed.stderr
    summary = _last_line(output)
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if name == "tests":
        if completed.returncode == 0:
            summary = "pytest passed"
        else:
            summary = next(
                (line for line in reversed(lines) if "failed" in line),
                summary,
            )[:240]
    elif name == "campaign_health":
        summary = next(
            (line for line in lines if line.startswith("Campaign health:")),
            summary,
        )[:240]
    elif name == "live_gate":
        summary = next(
            (line for line in lines if line.startswith("Live gate:")),
            summary,
        )[:240]
    elif name == "build":
        summary = next(
            (line for line in reversed(lines) if line.startswith("Successfully built")),
            summary,
        )[:240]
    return {
        "name": name,
        "command": " ".join(args),
        "returncode": completed.returncode,
        "ok": completed.returncode in allowed_codes,
        "elapsed_seconds": round(elapsed, 1),
        "summary": summary,
    }


def main() -> int:
    uv = _uv()
    checks = [
        _run("tests", [uv, "run", "pytest", "-q", "--disable-warnings"]),
        _run("ruff", [uv, "run", "ruff", "check", "."]),
        _run("mypy", [uv, "run", "mypy", "src"]),
        _run("build", [uv, "build"]),
        _run(
            "campaign_health",
            [uv, "run", "python", "-m", "tradingbot", "health"],
        ),
        _run(
            "live_gate",
            [
                uv,
                "run",
                "python",
                "-m",
                "tradingbot",
                "live-gate",
                "--include-ai",
            ],
            allowed_codes=(0, 1),
        ),
    ]
    required = {"tests", "ruff", "mypy", "build", "campaign_health"}
    code_ok = all(check["ok"] for check in checks if check["name"] in required)
    live_check = next(check for check in checks if check["name"] == "live_gate")
    live_gate = "GO" if live_check["returncode"] == 0 else "NO_GO"
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if code_ok else "FAIL",
        "required_checks_passed": code_ok,
        "live_gate": live_gate,
        "live_note": "NO_GO is expected until the evidence window and all hard checks pass.",
        "checks": checks,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    json_path = OUT / "SELF_EVAL.json"
    md_path = OUT / "SELF_EVAL.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        "# Self-evaluation",
        "",
        f"Generated: `{report['generated_at']}`",
        f"Code checks: **{report['status']}**",
        f"Live gate: **{report['live_gate']}**",
        "",
        "| Check | Result | Seconds | Summary |",
        "|---|---|---:|---|",
    ]
    for check in checks:
        result = "PASS" if check["ok"] else "FAIL"
        lines.append(
            f"| {check['name']} | {result} | {check['elapsed_seconds']} | "
            f"{check['summary'].replace('|', '/')} |"
        )
    lines.extend(
        [
            "",
            "The live gate is reported separately. A NO_GO is the expected safe "
            "result until the paper evidence window and live venue checks pass.",
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"self-eval: {report['status']} live_gate={live_gate}")
    for check in checks:
        print(
            f"  [{'PASS' if check['ok'] else 'FAIL'}] {check['name']}: "
            f"{check['summary']}"
        )
    print(f"saved: {json_path}")
    print(f"saved: {md_path}")
    return 0 if code_ok else 1


if __name__ == "__main__":
    sys.exit(main())
