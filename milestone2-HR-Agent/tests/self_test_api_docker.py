from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from src.agent import AgentService
from src.api import create_app
from src.cache import NullCache
from src.config import Settings
from src.contracts import ActionProposal, AuthContext
from src.providers import DeterministicProvider
from src.repository import MemoryRepository
from src.retrieval import RetrievalService
from src.tools import ToolExecutor


AUTH_ALYA = {"Authorization": "Bearer token-alya"}
AUTH_BIMA = {"Authorization": "Bearer token-bima"}
AUTH_ADMIN = {"Authorization": "Bearer token-admin"}


@pytest.fixture
def api_client() -> TestClient:
    settings = Settings(model_mode="fake")
    repo = MemoryRepository()
    cache = NullCache()
    retrieval = RetrievalService(repo, DeterministicProvider(), cache, 0)
    tools = ToolExecutor(repo, retrieval, settings, today_factory=lambda: date(2026, 9, 23))
    agent = AgentService(repo, DeterministicProvider(), tools, settings)
    app = create_app(settings=settings, repository=repo, cache=cache, agent=agent)
    client = TestClient(app)
    client._repo = repo  # type: ignore[attr-defined]
    return client


# ==============================================================================
# WBS-11: API Endpoints & Authorization Matrix Verification
# ==============================================================================


def test_api_health_and_readyz(api_client: TestClient) -> None:
    res = api_client.get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

    res_ready = api_client.get("/readyz")
    assert res_ready.status_code == 200
    data = res_ready.json()
    assert "ready" in data
    assert "dependencies" in data
    assert data["dependencies"]["configuration"] is True


def test_api_chat_auth_and_validation(api_client: TestClient) -> None:
    # 401 without auth
    assert api_client.post("/api/v1/chat", json={"message": "halo"}).status_code == 401
    # 401 with invalid token
    assert (
        api_client.post("/api/v1/chat", headers={"Authorization": "Bearer invalid"}, json={"message": "halo"}).status_code
        == 401
    )
    # 422 with blank message (ProblemDetail)
    res_val = api_client.post("/api/v1/chat", headers=AUTH_ALYA, json={"message": "   "})
    assert res_val.status_code == 422
    assert res_val.json()["title"] == "Invalid request"


def test_api_proposal_confirmation_flow_and_owner_isolation(api_client: TestClient) -> None:
    repo: MemoryRepository = api_client._repo  # type: ignore[attr-defined]

    # Seed proposal for Alya
    prop_id = "AP-ALYA-001"
    repo.save_proposal(
        "EMP-001",
        ActionProposal(
            proposal_id=prop_id,
            leave_type="annual",
            start_date=date(2026, 11, 2),
            end_date=date(2026, 11, 3),
            business_days=2,
            validation_summary=["valid"],
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        ),
    )

    # Bima tries to confirm Alya's proposal -> 404 (proposal not found for Bima)
    res_bima = api_client.post(
        f"/api/v1/action-proposals/{prop_id}/confirm",
        headers=AUTH_BIMA,
        json={"idempotency_key": "idem-key-12345"},
    )
    assert res_bima.status_code == 404

    # Alya confirms her proposal -> 200
    res_alya = api_client.post(
        f"/api/v1/action-proposals/{prop_id}/confirm",
        headers=AUTH_ALYA,
        json={"idempotency_key": "idem-key-12345"},
    )
    assert res_alya.status_code == 200
    data = res_alya.json()
    assert data["status"] == "pending_manager_review"
    assert data["idempotent_replay"] is False

    # Alya replays same idempotency key -> 200 with idempotent_replay True
    res_replay = api_client.post(
        f"/api/v1/action-proposals/{prop_id}/confirm",
        headers=AUTH_ALYA,
        json={"idempotency_key": "idem-key-12345"},
    )
    assert res_replay.status_code == 200
    assert res_replay.json()["idempotent_replay"] is True

    # Alya submits different key for same proposal -> 409 Conflict
    res_conflict = api_client.post(
        f"/api/v1/action-proposals/{prop_id}/confirm",
        headers=AUTH_ALYA,
        json={"idempotency_key": "different-key-999"},
    )
    assert res_conflict.status_code == 409


def test_api_traces_owner_isolation_and_admin_access(api_client: TestClient) -> None:
    repo: MemoryRepository = api_client._repo  # type: ignore[attr-defined]

    # Save a trace for Alya
    repo.save_trace(
        {
            "trace_id": "tr-alya-123",
            "employee_id": "EMP-001",
            "outcome": "answered",
        }
    )

    # Alya reads her own trace -> 200
    assert api_client.get("/api/v1/traces/tr-alya-123", headers=AUTH_ALYA).status_code == 200

    # Bima tries to read Alya's trace -> 403
    assert api_client.get("/api/v1/traces/tr-alya-123", headers=AUTH_BIMA).status_code == 403

    # Admin reads Alya's trace -> 200
    assert api_client.get("/api/v1/traces/tr-alya-123", headers=AUTH_ADMIN).status_code == 200

    # Non-existent trace -> 404
    assert api_client.get("/api/v1/traces/tr-unknown", headers=AUTH_ADMIN).status_code == 404


def test_api_monitoring_admin_only_and_alerts_evaluation(api_client: TestClient) -> None:
    repo: MemoryRepository = api_client._repo  # type: ignore[attr-defined]

    # Non-admin access to monitoring -> 403
    assert api_client.get("/api/v1/monitoring/summary", headers=AUTH_ALYA).status_code == 403
    assert api_client.get("/api/v1/monitoring/alerts", headers=AUTH_ALYA).status_code == 403

    # Admin access -> 200
    res_summary = api_client.get("/api/v1/monitoring/summary", headers=AUTH_ADMIN)
    assert res_summary.status_code == 200

    res_alerts = api_client.get("/api/v1/monitoring/alerts", headers=AUTH_ADMIN)
    assert res_alerts.status_code == 200
    assert isinstance(res_alerts.json(), list)


# ==============================================================================
# WBS-12: Dockerfile & Delivery Specifications Verification
# ==============================================================================


def test_dockerfile_and_compose_specs() -> None:
    root = Path(__file__).resolve().parents[1]

    # Dockerfile checks
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    assert "useradd" in dockerfile
    assert "10001" in dockerfile
    assert "USER appuser" in dockerfile
    assert "EXPOSE 8000" in dockerfile
    assert "CMD [" in dockerfile
    assert "--factory" in dockerfile

    # .dockerignore checks
    dockerignore = (root / ".dockerignore").read_text(encoding="utf-8")
    assert ".env" in dockerignore
    assert "__pycache__" in dockerignore

    # docker-compose.yml checks
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    assert "pgvector" in compose
    assert "redis:7-alpine" in compose
    assert "api:" in compose
    assert "streamlit:" in compose
