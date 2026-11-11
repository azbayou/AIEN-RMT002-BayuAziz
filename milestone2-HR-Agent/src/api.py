from __future__ import annotations

import base64
import binascii
import json
from pathlib import Path
import re
import time
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
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
    LeaveRequestView,
    LoginRequest,
    LoginResponse,
    ManagerReviewRequest,
    ManagerReviewResult,
    ProblemDetail,
)
from .repository import ConflictError, MemoryRepository, Repository
from .security import redact


def build_runtime(settings: Settings):
    from .agent import AgentService
    from .cache import ResilientCache
    from .providers import DeterministicProvider, OpenAIProvider
    from .repository import PostgresRepository
    from .retrieval import RetrievalService
    from .tools import ToolExecutor

    repository: Repository = PostgresRepository(settings.database_url, settings.embedding_dimensions)
    cache = ResilientCache(settings.redis_url)
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

    @app.post("/api/v1/auth/login", response_model=LoginResponse)
    def login(payload: LoginRequest) -> LoginResponse:
        result = repository.authenticate_password(payload.username, payload.password)
        if result is None:
            raise HTTPException(status_code=401, detail="Invalid username or password")
        return result

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

    @app.get("/api/v1/monitoring/alerts")
    def monitoring_alerts(auth: AuthContext = Depends(admin_auth)) -> list[dict[str, Any]]:
        summary = repository.monitoring_summary()
        rules_path = Path(__file__).resolve().parents[1] / "data" / "monitoring_rules.json"
        if not rules_path.is_file():
            return []
        try:
            rules = json.loads(rules_path.read_text(encoding="utf-8"))
        except Exception:
            return []
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

    return app
