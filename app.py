"""Vercel ASGI entrypoint.

Vercel looks for a top-level ``app`` variable. Streamlit's experimental
Starlette integration exposes the dashboard as an ASGI application, so this is
the actual server entrypoint rather than a plain script wrapper.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from streamlit.starlette import App  # noqa: E402

app = App(str(ROOT / "streamlit_app.py"))
