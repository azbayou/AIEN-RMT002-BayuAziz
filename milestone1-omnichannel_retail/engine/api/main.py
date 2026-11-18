"""FastAPI boundary for the prebuilt analytics engine."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from engine.api.control_plane import router as control_plane_router
from engine.api.models import AnalysisRequest, AnalysisResponse
from engine.core.legacy_service import configured_max_rows, run_query
from engine.core.orchestrator import analyze
from engine.llm.catalog import TABLES
from engine.llm.providers import build_provider
from engine.sql.safety import UnsafeQueryError

WEB_UI_DIR = Path(__file__).resolve().parents[2] / "ui" / "web"

app = FastAPI(title="Omnichannel Retail Analytics Engine", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(control_plane_router)
app.mount("/assets", StaticFiles(directory=str(WEB_UI_DIR), check_dir=False), name="assets")

provider = build_provider()
logger = logging.getLogger(__name__)


@app.get("/", include_in_schema=False)
def root() -> Response:
    """Serve the Modern Enterprise Medallion Control Plane UI."""

    index_path = WEB_UI_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path, media_type="text/html")
    return HTMLResponse("<h1>Medallion UI Loading...</h1>")


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2_000)
    max_rows: int | None = Field(default=None, ge=1, le=1_000)


class QueryResponse(BaseModel):
    question: str
    sql: str
    columns: list[str]
    rows: list[dict[str, object]]
    explanation: str
    tables_used: list[str]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "provider": provider.__class__.__name__}


@app.get("/schema")
def schema() -> dict[str, object]:
    return {"tables": TABLES}


@app.post("/v1/analyze", response_model=AnalysisResponse)
def analyze_question(request: AnalysisRequest) -> AnalysisResponse:
    try:
        return analyze(request, provider)
    except (UnsafeQueryError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # Keep provider/database details out of the HTTP response.
        logger.exception("Analytics analysis failed")
        raise HTTPException(status_code=503, detail="Analysis failed") from exc


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    """Backward-compatible endpoint for the original capstone foundation."""

    try:
        result = run_query(request.question, request.max_rows or configured_max_rows(), provider)
    except (UnsafeQueryError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # API boundary converts operational failures to a stable response.
        logger.exception("Legacy analytics query failed")
        raise HTTPException(status_code=503, detail="Query execution failed") from exc
    return QueryResponse(**result.__dict__)
