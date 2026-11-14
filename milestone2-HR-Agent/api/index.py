from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the root directory of the workspace is in sys.path so that 'src.*' imports succeed on Vercel
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.api import create_app

app = create_app()
