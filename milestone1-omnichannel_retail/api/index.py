"""Vercel serverless entrypoint re-exporting the FastAPI application."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.api.main import app  # noqa: E402

__all__ = ["app"]
