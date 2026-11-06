from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import Settings, get_settings
from .contracts import (
    ActionResult,
    AuthContext,
    ChatRequest,
    ChatResponse,
    ConfirmActionRequest,
    LeaveRequestView,
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
            timeout=settings.model_timeout_seconds,
        )
        if settings.model_mode == "live"
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
            "status": "ok" if ready else "degraded",
            "ready": ready,
            "dependencies": {
                "database": repository_ready,
                "cache": cache_ready,
                "configuration": configuration_ready,
            },
        }

    @app.post("/api/v1/chat", response_model=ChatResponse)
    def chat(payload: ChatRequest, auth: AuthContext = Depends(current_auth)) -> ChatResponse:
        return agent.run(payload, auth)

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
        return []

    return app
