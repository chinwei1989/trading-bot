"""Environment smoke test.

Run with:
    uv run python scripts/check_env.py

Checks Python version, core imports, optional imports, and data directories.
Does not require API keys or network access.
"""

from __future__ import annotations

import importlib
import platform
import sys
from pathlib import Path

CORE = [
    "polars",
    "pandas",
    "pyarrow",
    "duckdb",
    "numpy",
    "scipy",
    "statsmodels",
    "sklearn",
    "lightgbm",
    "xgboost",
    "optuna",
    "mlflow",
    "quantstats",
    "pydantic",
    "yaml",
    "httpx",
    "tenacity",
    "structlog",
    "exchange_calendars",
    "pandas_market_calendars",
    "ccxt",
    "alpaca",
]

OPTIONAL = {
    "nautilus_trader": "event-driven engine",
    "transformers": "NLP models",
    "torch": "deep learning",
    "shap": "feature attribution",
    "riskfolio": "portfolio optimization",
    "skfolio": "portfolio optimization",
}


def check_imports(modules: list[str], optional: bool = False) -> list[str]:
    missing: list[str] = []
    for name in modules:
        try:
            mod = importlib.import_module(name)
            version = getattr(mod, "__version__", "")
            print(f"  [ok] {name:<24} {version}")
        except Exception as exc:  # diagnostic output
            label = "optional" if optional else "MISSING"
            print(f"  [{label}] {name:<24} {exc}")
            if not optional:
                missing.append(name)
    return missing


def main() -> int:
    print(f"Python: {sys.version}")
    print(f"Platform: {platform.platform()}")
    print(f"Executable: {sys.executable}")
    print()

    if sys.version_info[:2] != (3, 12):
        print("WARNING: this project targets Python 3.12.x")

    print("Core imports:")
    missing = check_imports(CORE)
    print()

    print("Optional imports:")
    check_imports(list(OPTIONAL), optional=True)
    print()

    root = Path(__file__).resolve().parents[1]
    print("Data directories:")
    for rel in [
        "data/raw",
        "data/normalized",
        "data/features",
        "data/reference",
        "artifacts",
    ]:
        path = root / rel
        status = "exists" if path.exists() else "missing"
        print(f"  [{status}] {path}")
    print()

    if missing:
        print(f"FAIL: missing core modules: {', '.join(missing)}")
        print("Run: uv sync --extra dev")
        return 1

    print("OK: core environment is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
