"""Root entrypoint for Streamlit Community Cloud and other app hosts.

Run locally with either:

    streamlit run streamlit_app.py
    uv run streamlit run src/tradingbot/ops/dashboard.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Importing the dashboard executes its top-level Streamlit rendering code.
from tradingbot.ops import dashboard as _dashboard  # noqa: E402,F401
