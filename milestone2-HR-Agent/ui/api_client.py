"""HTTP client and background daemon for Miyo HR Assistant."""
from __future__ import annotations

import os
import threading
import time
from typing import Any

import httpx
import streamlit as st

from ui.config import API_URL


def ensure_api_running() -> None:
    """If running in an all-in-one environment without an external API, start FastAPI in background."""
    if "api" in API_URL or "onrender.com" in API_URL:
        return
    if "FASTAPI_DAEMON_STARTED" not in st.session_state:
        st.session_state["FASTAPI_DAEMON_STARTED"] = True
        try:
            httpx.get(f"{API_URL}/healthz", timeout=1.0)
        except Exception:
            try:
                import uvicorn
                from src.api import create_app

                app_instance = create_app()

                def _start_server():
                    uvicorn.run(app_instance, host="127.0.0.1", port=8000, log_level="warning")

                server_thread = threading.Thread(target=_start_server, daemon=True)
                server_thread.start()
                time.sleep(1.5)
            except Exception:
                pass


def api_request(method: str, path: str, token: str, suppress_error: bool = False, **kwargs: Any) -> Any:
    """Execute authenticated API request to backend service."""
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = httpx.request(method, f"{API_URL}{path}", headers=headers, timeout=45, **kwargs)
        if response.is_error:
            if not suppress_error:
                try:
                    detail = response.json().get("detail", response.text)
                except Exception:
                    detail = response.text
                st.error(f"[ERROR {response.status_code}] {detail}")
            return None
        return response.json()
    except httpx.ConnectError:
        if not suppress_error:
            st.error(f"[KONEKSI GAGAL] Gagal terhubung ke API di {API_URL}. Pastikan backend FastAPI sedang berjalan.")
        return None
    except Exception as err:
        if not suppress_error:
            st.error(f"[KESALAHAN SISTEM] {err}")
        return None


def get_health_status() -> dict[str, Any]:
    """Retrieve backend database and service health status."""
    try:
        resp = httpx.get(f"{API_URL}/readyz", timeout=3.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {"status": "offline", "ready": False}
