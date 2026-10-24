"""Vercel entry point: serves the FastAPI app as a Python function (all /api/* routes rewrite here)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from inquira.main import app  # noqa: E402,F401
