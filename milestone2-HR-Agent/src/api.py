from __future__ import annotations

import base64
import binascii
from datetime import date
import json
import os
from pathlib import Path
import re
import time
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings, get_settings
from .contracts import (
    ActionResult,
    AudioTranscribeRequest,
    AudioTranscribeResponse,
    AuthContext,
    ChatRequest,
    ChatResponse,
    ConfirmActionRequest,
    LeaveAttachmentUploadRequest,
    LeaveAttachmentView,
    LeaveBalance,
    LeaveRequestView,
    LoginRequest,
    LoginResponse,
    ManagerReviewRequest,
    ManagerReviewResult,
    ProblemDetail,
    UpdateTicketStatusRequest,
)
from .domain import get_annual_leave_lead_days, get_sick_leave_doc_threshold
from .repository import ConflictError, MemoryRepository, Repository
from .security import redact


def build_runtime(settings: Settings):
    from .agent import AgentService
    from .cache import NullCache, ResilientCache
    from .providers import DeterministicProvider, OpenAIProvider
    from .repository import PostgresRepository
    from .retrieval import RetrievalService
    from .tools import ToolExecutor

    repository: Repository = PostgresRepository(settings.database_url, settings.embedding_dimensions)
    cache = ResilientCache(settings.redis_url) if settings.redis_url else NullCache()
    provider = (
        OpenAIProvider(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.agent_model,
            embedding_model=settings.embedding_model,
            stt_model=settings.stt_model,
            timeout=settings.model_timeout_seconds,
            gemini_api_key=settings.gemini_api_key,
            gemini_stt_model=settings.gemini_stt_model,
        )
        if settings.live_model_ready
        else DeterministicProvider(settings.embedding_dimensions)
    )
    retrieval = RetrievalService(
        repository,
        provider,
        cache,
        settings.retrieval_cache_ttl_seconds,
        settings.policy_index_version,
    )
    tools = ToolExecutor(repository, retrieval, settings)
    return repository, cache, AgentService(repository, provider, tools, settings)


def _validate_attachment_bytes(content_type: str, data: bytes) -> None:
    if len(data) < 4 or len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="Attachment size must be between 4 bytes and 5 MB")
    if content_type == "application/pdf" and not data.startswith(b"%PDF-"):
        raise HTTPException(status_code=422, detail="File payload is not a valid PDF document")
    if content_type == "image/png" and not data.startswith(b"\x89PNG"):
        raise HTTPException(status_code=422, detail="File payload is not a valid PNG image")
    if content_type == "image/jpeg" and not data.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=422, detail="File payload is not a valid JPEG image")


def create_app(*, settings: Settings | None = None, repository=None, cache=None, agent=None) -> FastAPI:
    """Build the documented API without changing endpoint or response contracts."""
    settings = settings or get_settings()
    if repository is None or cache is None or agent is None:
        repository, cache, agent = build_runtime(settings)
    app = FastAPI(title=settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=ProblemDetail(
                title="Invalid request",
                status=422,
                detail="Request validation failed.",
            ).model_dump(),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        titles = {
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not found",
            409: "Conflict",
        }
        return JSONResponse(
            status_code=exc.status_code,
            content=ProblemDetail(
                title=titles.get(exc.status_code, "Request error"),
                status=exc.status_code,
                detail=redact(str(exc.detail)),
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content=ProblemDetail(
                title="Internal server error",
                status=500,
                detail="An unexpected error occurred.",
            ).model_dump(),
        )

    def authenticate(authorization: str | None) -> AuthContext:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
        context = repository.authenticate(authorization[7:])
        if context is None:
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
        return context

    def current_auth(authorization: str | None = Header(default=None)) -> AuthContext:
        return authenticate(authorization)

    def admin_auth(auth: AuthContext = Depends(current_auth)) -> AuthContext:
        if auth.role != "monitoring_admin":
            raise HTTPException(status_code=403, detail="Monitoring admin access required")
        return auth

    def manager_auth(auth: AuthContext = Depends(current_auth)) -> AuthContext:
        if auth.role not in ("manager", "monitoring_admin"):
            raise HTTPException(status_code=403, detail="Manager access required")
        return auth

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, Any]:
        repository_ready = bool(repository.health())
        cache_ready = bool(cache.health())
        configuration_ready = bool(settings.configuration_ready)
        ready = repository_ready and configuration_ready
        return {
            "status": "ready" if ready else "degraded",
            "ready": ready,
            "dependencies": {
                "database": repository_ready,
                "cache": cache_ready,
                "configuration": configuration_ready,
            },
        }

    @app.get("/api/v1/auth/personas")
    def list_personas() -> list[dict[str, Any]]:
        if hasattr(repository, "list_personas"):
            return repository.list_personas()
        return []

    @app.get("/api/v1/policies/rules")
    def policy_rules() -> dict[str, Any]:
        annual_policy_text = None
        sick_policy_text = None

        if hasattr(repository, "pool"):
            try:
                with repository.pool.connection() as connection:
                    rows = connection.execute(
                        "SELECT document_id, content FROM policy_chunks WHERE document_id IN ('HR-LEAVE-001', 'HR-LEAVE-002') ORDER BY chunk_id"
                    ).fetchall()
                    annual_chunks = []
                    sick_chunks = []
                    for r in rows:
                        doc_id = r["document_id"] if isinstance(r, dict) or (hasattr(r, "__getitem__") and "document_id" in r) else r[0]
                        content = r["content"] if isinstance(r, dict) or (hasattr(r, "__getitem__") and "content" in r) else r[1]
                        if doc_id == "HR-LEAVE-001":
                            annual_chunks.append(content)
                        elif doc_id == "HR-LEAVE-002":
                            sick_chunks.append(content)
                    if annual_chunks:
                        annual_policy_text = "\n\n".join(annual_chunks)
                    if sick_chunks:
                        sick_policy_text = "\n\n".join(sick_chunks)
            except Exception:
                pass
        elif hasattr(repository, "chunks"):
            annual_chunks = [c.content for c in repository.chunks if getattr(c, "document_id", None) == "HR-LEAVE-001"]
            sick_chunks = [c.content for c in repository.chunks if getattr(c, "document_id", None) == "HR-LEAVE-002"]
            if annual_chunks:
                annual_policy_text = "\n\n".join(annual_chunks)
            if sick_chunks:
                sick_policy_text = "\n\n".join(sick_chunks)

        lead_days = get_annual_leave_lead_days(annual_policy_text)
        sick_thresh = get_sick_leave_doc_threshold(sick_policy_text)
        return {
            "server_date": date.today().isoformat(),
            "annual_lead_days": lead_days,
            "sick_doc_threshold": sick_thresh,
            "policy_summaries": {
                "annual": {
                    "citation": "[HR-LEAVE-001]",
                    "summary": f"Berdasarkan kebijakan [HR-LEAVE-001], cuti tahunan wajib diajukan paling lambat {lead_days} hari kerja sebelum tanggal mulai cuti dan tidak bertumpang tindih dengan permohonan lain.",
                },
                "sick": {
                    "citation": "[HR-LEAVE-002]",
                    "summary": f"Berdasarkan kebijakan [HR-LEAVE-002], cuti sakit lebih dari {sick_thresh} hari kerja berturut-turut wajib melampirkan surat keterangan dokter.",
                },
                "parental": {
                    "citation": "[HR-LEAVE-003]",
                    "summary": "Berdasarkan kebijakan [HR-LEAVE-003], cuti orang tua mengikuti hak cuti melahirkan / hak ayah sesuai undang-undang dan kebijakan perusahaan.",
                },
            },
        }

    @app.post("/api/v1/auth/login", response_model=LoginResponse)
    def login(payload: LoginRequest) -> LoginResponse:
        result = repository.authenticate_password(payload.username, payload.password)
        if result is None:
            raise HTTPException(status_code=401, detail="Invalid username or password")
        return result

    @app.get("/api/v1/leave-balances/me", response_model=list[LeaveBalance])
    def my_leave_balances(auth: AuthContext = Depends(current_auth)) -> list[LeaveBalance]:
        return repository.get_balances(auth.employee_id)

    @app.post("/api/v1/chat", response_model=ChatResponse)
    def chat(payload: ChatRequest, auth: AuthContext = Depends(current_auth)) -> ChatResponse:
        return agent.run(payload, auth)

    @app.post("/api/v1/audio/transcribe", response_model=AudioTranscribeResponse)
    def transcribe_audio(
        payload: AudioTranscribeRequest,
        auth: AuthContext = Depends(current_auth),
    ) -> AudioTranscribeResponse:
        started = time.monotonic()
        try:
            raw_b64 = payload.audio_base64.split(",")[-1].strip()
            audio_bytes = base64.b64decode(raw_b64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=422, detail="Invalid base64 audio payload")

        if len(audio_bytes) < 4 or len(audio_bytes) > 5 * 1024 * 1024:
            raise HTTPException(status_code=422, detail="Audio size must be between 4 bytes and 5 MB")

        try:
            transcript = agent.provider.transcribe(
                audio_bytes=audio_bytes,
                filename=payload.filename,
                language=payload.language,
            )
        except Exception as err:
            raise HTTPException(status_code=502, detail=f"Speech-to-text transcription unavailable: {err}")

        if not transcript:
            raise HTTPException(status_code=422, detail="No speech detected in audio")

        return AudioTranscribeResponse(
            text=redact(transcript),
            language=payload.language,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        )

    @app.post("/api/v1/action-proposals/{proposal_id}/confirm", response_model=ActionResult)
    def confirm(
        proposal_id: str,
        payload: ConfirmActionRequest,
        auth: AuthContext = Depends(current_auth),
    ) -> ActionResult:
        try:
            return repository.confirm_proposal(auth.employee_id, proposal_id, payload.idempotency_key)
        except KeyError:
            raise HTTPException(status_code=404, detail="Proposal not found")
        except ConflictError as error:
            raise HTTPException(status_code=409, detail=redact(str(error)))

    @app.get("/api/v1/leave-requests/me", response_model=list[LeaveRequestView])
    def my_leave_requests(auth: AuthContext = Depends(current_auth)) -> list[LeaveRequestView]:
        return repository.list_leave_requests(auth.employee_id)

    @app.post("/api/v1/leave-requests/{request_id}/attachment", response_model=LeaveAttachmentView)
    def upload_leave_attachment(
        request_id: str,
        payload: LeaveAttachmentUploadRequest,
        auth: AuthContext = Depends(current_auth),
    ) -> LeaveAttachmentView:
        try:
            raw_b64 = payload.content_base64.split(",")[-1].strip()
            file_bytes = base64.b64decode(raw_b64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=422, detail="Invalid base64 attachment payload")

        _validate_attachment_bytes(payload.content_type, file_bytes)
        safe_filename = re.sub(r"[^A-Za-z0-9._-]", "_", payload.filename.strip()) or "attachment"

        try:
            return repository.save_leave_attachment(
                employee_id=auth.employee_id,
                request_id=request_id,
                filename=safe_filename,
                content_type=payload.content_type,
                file_bytes=file_bytes,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Leave request not found")
        except ConflictError as error:
            raise HTTPException(status_code=409, detail=redact(str(error)))

    @app.get("/api/v1/leave-requests/{request_id}/attachment", response_model=LeaveAttachmentView)
    def get_leave_attachment(
        request_id: str,
        auth: AuthContext = Depends(current_auth),
    ) -> LeaveAttachmentView:
        try:
            return repository.get_leave_attachment(auth, request_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Attachment not found")
        except PermissionError:
            raise HTTPException(status_code=403, detail="Not authorized to view this attachment")

    @app.get("/api/v1/manager/leave-requests", response_model=list[LeaveRequestView])
    def team_leave_requests(auth: AuthContext = Depends(manager_auth)) -> list[LeaveRequestView]:
        return repository.list_team_leave_requests(
            auth.employee_id,
            include_all_departments=(auth.role == "monitoring_admin"),
        )

    @app.post("/api/v1/manager/leave-requests/{request_id}/review", response_model=ManagerReviewResult)
    def review_leave_request(
        request_id: str,
        payload: ManagerReviewRequest,
        auth: AuthContext = Depends(manager_auth),
    ) -> ManagerReviewResult:
        try:
            return repository.review_leave_request(
                reviewer_id=auth.employee_id,
                request_id=request_id,
                decision=payload.decision,
                review_note=payload.review_note,
                is_admin=(auth.role == "monitoring_admin"),
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Leave request not found in your team")
        except ConflictError as error:
            raise HTTPException(status_code=409, detail=redact(str(error)))

    @app.get("/api/v1/analytics/overview")
    def analytics_overview(
        metric_focus: str = "overview",
        low_balance_threshold: int = Query(default=3, ge=1, le=30),
        auth: AuthContext = Depends(manager_auth),
    ) -> dict[str, Any]:
        return repository.get_hr_analytics(
            auth,
            metric_focus=metric_focus,
            low_balance_threshold=low_balance_threshold,
        )

    @app.get("/api/v1/traces/{trace_id}")
    def trace(trace_id: str, auth: AuthContext = Depends(current_auth)) -> dict[str, Any]:
        item = repository.get_trace(trace_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Trace not found")
        if auth.role != "monitoring_admin" and item.get("employee_id") != auth.employee_id:
            raise HTTPException(status_code=403, detail="Trace access denied")
        return item

    @app.get("/api/v1/monitoring/summary")
    def monitoring_summary(auth: AuthContext = Depends(admin_auth)) -> dict[str, Any]:
        return repository.monitoring_summary()

    @app.get("/api/v1/monitoring/rules")
    def monitoring_rules(auth: AuthContext = Depends(admin_auth)) -> list[dict[str, Any]]:
        if hasattr(repository, "list_monitoring_rules"):
            try:
                return repository.list_monitoring_rules()
            except Exception:
                return []
        return []

    @app.get("/api/v1/monitoring/alerts")
    def monitoring_alerts(auth: AuthContext = Depends(admin_auth)) -> list[dict[str, Any]]:
        summary = repository.monitoring_summary()
        if hasattr(repository, "list_monitoring_rules"):
            try:
                rules = repository.list_monitoring_rules()
            except Exception:
                rules = []
        else:
            rules = []
        alerts = []
        samples = summary.get("run_count", summary.get("total_traces", 0))
        for rule in rules:
            if samples < rule.get("minimum_samples", 1):
                continue
            metric_val = summary.get(rule["metric"])
            if metric_val is None:
                continue
            threshold = rule["threshold"]
            op = rule.get("operator", "gt")
            triggered = (metric_val > threshold) if op == "gt" else (metric_val >= threshold)
            if triggered:
                alerts.append({
                    "rule_id": rule["rule_id"],
                    "metric": rule["metric"],
                    "current_value": metric_val,
                    "threshold": threshold,
                    "owner": rule.get("owner", "AI Platform"),
                    "response": rule.get("response", ""),
                })
        return alerts

    @app.get("/api/v1/tickets")
    def list_tickets(auth: AuthContext = Depends(current_auth)) -> list[dict[str, Any]]:
        if hasattr(repository, "list_tickets"):
            emp_id = None if auth.role in ("manager", "monitoring_admin") else auth.employee_id
            return repository.list_tickets(emp_id)
        return []

    @app.patch("/api/v1/tickets/{ticket_id}/status")
    def update_ticket_status(
        ticket_id: str,
        payload: UpdateTicketStatusRequest,
        auth: AuthContext = Depends(manager_auth),
    ) -> dict[str, Any]:
        if not hasattr(repository, "update_ticket_status"):
            raise HTTPException(status_code=501, detail="Update ticket status not supported")
        try:
            return repository.update_ticket_status(ticket_id, payload.status, auth.employee_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/")
    @app.get("/api")
    def root_info() -> dict[str, Any]:
        return {
            "status": "online",
            "service": "PT Nusantara Digital - HR Agent Assistant API",
            "environment": "vercel_serverless" if os.getenv("VERCEL") else "standalone",
            "documentation": "/docs",
            "version": settings.policy_index_version,
            "endpoints": {
                "health": "/healthz",
                "readiness": "/readyz",
                "personas": "/api/v1/auth/personas",
                "chat": "/api/v1/chat",
                "tickets": "/api/v1/tickets",
                "leave_requests": "/api/v1/leaves/requests",
                "monitoring_summary": "/api/v1/monitoring/summary",
                "monitoring_rules": "/api/v1/monitoring/rules",
                "monitoring_alerts": "/api/v1/monitoring/alerts",
            },
        }

    is_vercel = bool(os.getenv("VERCEL"))
    is_backend_only = os.getenv("BACKEND_ONLY", "false").lower() in ("1", "true", "yes")

    from fastapi.staticfiles import StaticFiles

    base_dir = Path(__file__).resolve().parents[1]
    public_dir = base_dir / "ui" / "public" if (base_dir / "ui" / "public").is_dir() else (base_dir / "public")
    web_dir = base_dir / "web"

    if public_dir.is_dir():
        app.mount("/public", StaticFiles(directory=str(public_dir)), name="public")
    if web_dir.is_dir():
        app.mount("/web", StaticFiles(directory=str(web_dir)), name="web_assets")
        if not is_vercel and not is_backend_only:
            app.mount("/portal", StaticFiles(directory=str(web_dir), html=True), name="portal_web")
            # Mount at root only if web index exists and neither vercel nor backend_only is active
            if (web_dir / "index.html").is_file() and not os.getenv("PREFER_ROOT_API"):
                app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="portal")

    return app