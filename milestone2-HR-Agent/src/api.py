from __future__ import annotations

import base64
import binascii
from contextlib import asynccontextmanager
from datetime import date
import os
from pathlib import Path
import re
import time
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Settings, get_settings
from .contracts import (
    ActionResult,
    AudioTranscribeRequest,
    AudioTranscribeResponse,
    AuthContext,
    ChatRequest,
    ChatResponse,
    ConfirmActionRequest,
    DemoSessionRequest,
    LeaveAttachmentUploadRequest,
    LeaveAttachmentView,
    LeaveBalance,
    LeaveRequestView,
    LoginRequest,
    LoginResponse,
    ProblemDetail,
    ProposalAttachmentView,
    UpdateTicketStatusRequest,
)
from .domain import (
    compute_earliest_annual_leave_date,
    get_annual_leave_lead_days,
    get_sick_leave_doc_threshold,
)
from .repository import ConflictError, Repository
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


def _sanitize_upload_filename(raw_filename: str) -> str:
    base = Path(raw_filename.strip()).name
    redacted = redact(redact(base).replace("_", " "))
    return re.sub(r"[^A-Za-z0-9._-]", "_", redacted) or "attachment"


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

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            tracker = getattr(agent, "tracker", None)
            if tracker is not None and hasattr(tracker, "flush"):
                try:
                    tracker.flush()
                except Exception:
                    pass
            if hasattr(repository, "close"):
                try:
                    repository.close()
                except Exception:
                    pass

    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.parsed_cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        field_errors = []
        for err in exc.errors()[:5]:
            loc = ".".join(str(part) for part in err.get("loc", []) if part != "body")
            msg = err.get("msg", "invalid value")
            field_errors.append(f"{loc}: {msg}" if loc else msg)
        detail = (
            f"Request validation failed: {'; '.join(field_errors)}"
            if field_errors
            else "Request validation failed."
        )
        return JSONResponse(
            status_code=422,
            content=ProblemDetail(
                title="Invalid request",
                status=422,
                detail=redact(detail),
            ).model_dump(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        titles = {
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not found",
            405: "Method not allowed",
            409: "Conflict",
        }
        headers = dict(getattr(exc, "headers", None) or {})
        if exc.status_code == 401 and "WWW-Authenticate" not in headers:
            headers["WWW-Authenticate"] = "Bearer"
        return JSONResponse(
            status_code=exc.status_code,
            headers=headers or None,
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
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        context = repository.authenticate(authorization[7:])
        if context is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return context

    def current_auth(authorization: str | None = Header(default=None)) -> AuthContext:
        return authenticate(authorization)

    def admin_auth(auth: AuthContext = Depends(current_auth)) -> AuthContext:
        if auth.role != "monitoring_admin":
            raise HTTPException(status_code=403, detail="Monitoring admin access required")
        return auth

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        repository_ready = bool(repository.health())
        cache_ready = bool(cache.health())
        configuration_ready = bool(settings.configuration_ready)
        ready = repository_ready and configuration_ready
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "status": "ready" if ready else "degraded",
                "ready": ready,
                "dependencies": {
                    "database": repository_ready,
                    "cache": cache_ready,
                    "configuration": configuration_ready,
                },
            },
        )

    @app.get("/auth/personas")
    def list_personas() -> list[dict[str, Any]]:
        if hasattr(repository, "list_personas"):
            allow_demo = (
                settings.allow_demo_session
                and settings.environment.strip().casefold() != "production"
            )
            try:
                return repository.list_personas(allow_demo_session=allow_demo)
            except TypeError:
                return repository.list_personas()
        return []

    @app.post("/auth/demo-session", response_model=LoginResponse)
    def create_demo_session(payload: DemoSessionRequest) -> LoginResponse:
        if (
            not settings.allow_demo_session
            or settings.environment.strip().casefold() == "production"
        ):
            raise HTTPException(
                status_code=403,
                detail="Demo session login is disabled; use /auth/login",
            )
        try:
            return repository.create_demo_session(payload.employee_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Persona not found")
        except PermissionError:
            raise HTTPException(status_code=403, detail="Demo session is only available for employee accounts")

    @app.post("/auth/login", response_model=LoginResponse)
    def login(payload: LoginRequest) -> LoginResponse:
        result = repository.authenticate_password(payload.username, payload.password)
        if result is None:
            raise HTTPException(status_code=401, detail="Invalid username or password")
        return result

    @app.get("/api/v1/policies/rules")
    def policy_rules(auth: AuthContext = Depends(current_auth)) -> dict[str, Any]:
        today = settings.reference_date or date.today()
        doc_map = {
            "HR-LEAVE-001": "annual",
            "HR-LEAVE-002": "sick",
            "HR-LEAVE-003": "parental",
        }
        texts_by_doc: dict[str, str | None] = {}
        for doc_id in doc_map:
            if hasattr(repository, "get_policy_document_text"):
                texts_by_doc[doc_id] = repository.get_policy_document_text(doc_id, as_of=today)
            else:
                texts_by_doc[doc_id] = None

        annual_policy_text = texts_by_doc["HR-LEAVE-001"]
        sick_policy_text = texts_by_doc["HR-LEAVE-002"]
        lead_days = get_annual_leave_lead_days(annual_policy_text)
        earliest_annual = compute_earliest_annual_leave_date(today, lead_days)
        sick_thresh = get_sick_leave_doc_threshold(sick_policy_text)
        policy_summaries = {
            leave_key: {
                "citation": f"[{doc_id}]",
                "summary": (
                    f"[{doc_id}] {' '.join(texts_by_doc[doc_id].split())}"
                    if texts_by_doc[doc_id]
                    else f"[{doc_id}]"
                ),
            }
            for doc_id, leave_key in doc_map.items()
        }
        return {
            "server_date": today.isoformat(),
            "annual_lead_days": lead_days,
            "earliest_annual_start_date": earliest_annual.isoformat(),
            "sick_doc_threshold": sick_thresh,
            "policy_summaries": policy_summaries,
        }

    @app.get("/api/v1/evaluation/cases")
    def evaluation_cases(auth: AuthContext = Depends(current_auth)) -> list[dict[str, Any]]:
        if hasattr(repository, "list_evaluation_cases"):
            return repository.list_evaluation_cases()
        return []

    @app.get("/api/v1/leave-balances/me", response_model=list[LeaveBalance])
    def my_leave_balances(auth: AuthContext = Depends(current_auth)) -> list[LeaveBalance]:
        today = settings.reference_date or date.today()
        try:
            return repository.get_balances(auth.employee_id, as_of=today)
        except TypeError:
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
        except Exception:
            raise HTTPException(status_code=502, detail="Speech-to-text transcription unavailable")

        if not transcript:
            raise HTTPException(status_code=422, detail="No speech detected in audio")

        return AudioTranscribeResponse(
            text=redact(transcript),
            language=payload.language,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        )

    @app.post("/api/v1/action-proposals/{proposal_id}/attachment", response_model=ProposalAttachmentView)
    def upload_proposal_attachment(
        proposal_id: str,
        payload: LeaveAttachmentUploadRequest,
        auth: AuthContext = Depends(current_auth),
    ) -> ProposalAttachmentView:
        try:
            raw_b64 = payload.content_base64.split(",")[-1].strip()
            file_bytes = base64.b64decode(raw_b64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=422, detail="Invalid base64 attachment payload")

        _validate_attachment_bytes(payload.content_type, file_bytes)
        safe_filename = _sanitize_upload_filename(payload.filename)

        try:
            return repository.save_proposal_attachment(
                employee_id=auth.employee_id,
                proposal_id=proposal_id,
                filename=safe_filename,
                content_type=payload.content_type,
                file_bytes=file_bytes,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Proposal not found")
        except ConflictError as error:
            raise HTTPException(status_code=409, detail=redact(str(error)))

    @app.post("/api/v1/action-proposals/{proposal_id}/confirm", response_model=ActionResult)
    def confirm(
        proposal_id: str,
        payload: ConfirmActionRequest,
        auth: AuthContext = Depends(current_auth),
        x_enforce_sick_attachment: str | None = Header(default=None),
    ) -> ActionResult:
        today = settings.reference_date or date.today()
        enforce_attachment = (x_enforce_sick_attachment or "").strip().lower() in {"1", "true", "yes"}
        try:
            try:
                return repository.confirm_proposal(
                    auth.employee_id,
                    proposal_id,
                    payload.idempotency_key,
                    today=today,
                    enforce_attachment=enforce_attachment,
                )
            except TypeError:
                return repository.confirm_proposal(
                    auth.employee_id,
                    proposal_id,
                    payload.idempotency_key,
                    today=today,
                )
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
        safe_filename = _sanitize_upload_filename(payload.filename)

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

    @app.get("/api/v1/analytics/overview")
    def analytics_overview(
        metric_focus: str = "overview",
        low_balance_threshold: int = Query(default=3, ge=1, le=30),
        auth: AuthContext = Depends(admin_auth),
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
                raise HTTPException(status_code=503, detail="Monitoring rules unavailable")
        return []

    @app.get("/api/v1/monitoring/alerts")
    def monitoring_alerts(auth: AuthContext = Depends(admin_auth)) -> list[dict[str, Any]]:
        try:
            summary = repository.monitoring_summary()
            rules = (
                repository.list_monitoring_rules()
                if hasattr(repository, "list_monitoring_rules")
                else []
            )
        except Exception:
            raise HTTPException(status_code=503, detail="Monitoring alerts unavailable")

        ops = {
            "gt": lambda v, t: v > t,
            "gte": lambda v, t: v >= t,
            "lt": lambda v, t: v < t,
            "lte": lambda v, t: v <= t,
            "eq": lambda v, t: v == t,
        }
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
            cmp_fn = ops.get(op, ops["gt"])
            if cmp_fn(metric_val, threshold):
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
            if auth.role == "monitoring_admin":
                return repository.list_tickets()
            return repository.list_tickets(employee_id=auth.employee_id)
        return []

    @app.patch("/api/v1/tickets/{ticket_id}/status")
    def update_ticket_status(
        ticket_id: str,
        payload: UpdateTicketStatusRequest,
        auth: AuthContext = Depends(admin_auth),
    ) -> dict[str, Any]:
        if not hasattr(repository, "update_ticket_status"):
            raise HTTPException(status_code=501, detail="Update ticket status not supported")
        try:
            return repository.update_ticket_status(
                ticket_id,
                payload.status,
                auth.employee_id,
                allowed_manager_id=None,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Ticket not found")
        except PermissionError:
            raise HTTPException(status_code=403, detail="Not authorized to update this ticket")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=redact(str(exc)))

    is_vercel = bool(os.getenv("VERCEL"))
    is_backend_only = os.getenv("BACKEND_ONLY", "false").lower() in ("1", "true", "yes")

    from fastapi.staticfiles import StaticFiles

    base_dir = Path(__file__).resolve().parents[1]
    public_dir = base_dir / "ui" / "public" if (base_dir / "ui" / "public").is_dir() else (base_dir / "web" / "asset")
    web_dir = base_dir / "web"

    @app.get("/api")
    def root_info() -> dict[str, Any]:
        return {
            "status": "online",
            "service": "PT Nusantara Digital - HR Agent Assistant API",
            "environment": "vercel_serverless" if is_vercel else "standalone",
            "documentation": "/docs",
            "version": settings.policy_index_version,
            "endpoints": {
                "health": "/healthz",
                "readiness": "/readyz",
                "personas": "/auth/personas",
                "demo_session": "/auth/demo-session",
                "login": "/auth/login",
                "policy_rules": "/api/v1/policies/rules",
                "evaluation_cases": "/api/v1/evaluation/cases",
                "chat": "/api/v1/chat",
                "tickets": "/api/v1/tickets",
                "leave_requests": "/api/v1/leave-requests/me",
                "monitoring_summary": "/api/v1/monitoring/summary",
                "monitoring_rules": "/api/v1/monitoring/rules",
                "monitoring_alerts": "/api/v1/monitoring/alerts",
            },
        }

    if is_vercel or is_backend_only or os.getenv("PREFER_ROOT_API") or not (web_dir / "index.html").is_file():
        app.add_api_route("/", root_info, methods=["GET"])
    else:
        @app.get("/", include_in_schema=False)
        def serve_spa_index() -> FileResponse:
            return FileResponse(web_dir / "index.html")

        if (web_dir / "app.js").is_file():
            @app.get("/app.js", include_in_schema=False)
            def serve_spa_script() -> FileResponse:
                return FileResponse(web_dir / "app.js", media_type="application/javascript")

        if (web_dir / "asset").is_dir():
            app.mount("/asset", StaticFiles(directory=str(web_dir / "asset")), name="web_assets")

    if public_dir.is_dir():
        app.mount("/public", StaticFiles(directory=str(public_dir)), name="public")

    return app