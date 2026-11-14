from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the root directory of the workspace is in sys.path so that 'src.*' imports succeed on Vercel
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from src.api import create_app

    app = create_app()
except Exception as exc:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    app = FastAPI(title="Miyo HR Backend (Configuration Required)")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    async def missing_env_handler(path: str = ""):
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": "Backend Startup Configuration Required",
                "detail": str(exc),
                "hint": "Pastikan Environment Variables (terutama DATABASE_URL) sudah diset di Vercel Dashboard: Project Settings > Environment Variables.",
                "path": f"/{path}",
            },
        )
