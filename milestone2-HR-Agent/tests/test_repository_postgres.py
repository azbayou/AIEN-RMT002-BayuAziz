from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.config import Settings
from src.contracts import ActionProposal
from src.repository import PostgresRepository


pytestmark = pytest.mark.postgres


@pytest.fixture
def postgres_repository() -> PostgresRepository:
    if not os.getenv("RUN_POSTGRES_TESTS"):
        pytest.skip("Set RUN_POSTGRES_TESTS=1 for PostgreSQL integration tests.")
    settings = Settings()
    repository = PostgresRepository(settings.database_url, settings.embedding_dimensions)
    if not repository.health():
        repository.pool.close()
        pytest.skip("PostgreSQL is not available.")
    try:
        yield repository
    finally:
        repository.pool.close()


def test_postgres_repository_supports_owner_bound_actions(postgres_repository: PostgresRepository) -> None:
    proposal_id = f"AP-TEST-{uuid4().hex[:12]}"
    proposal = ActionProposal(
        proposal_id=proposal_id,
        leave_type="annual",
        start_date=date(2026, 12, 14),
        end_date=date(2026, 12, 15),
        business_days=2,
        validation_summary=["integration"],
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    postgres_repository.save_proposal("EMP-001", proposal)
    try:
        assert postgres_repository.get_proposal(proposal_id)[0] == "EMP-001"
        with pytest.raises(KeyError):
            postgres_repository.confirm_proposal("EMP-002", proposal_id, "wrong-owner-key")
        first = postgres_repository.confirm_proposal("EMP-001", proposal_id, "integration-key")
        replay = postgres_repository.confirm_proposal("EMP-001", proposal_id, "integration-key")
        assert first.request_id == replay.request_id
        assert replay.idempotent_replay is True
        assert all(
            item.status == "pending_manager_review"
            for item in postgres_repository.list_leave_requests("EMP-001")
            if item.request_id == proposal_id
        )
    finally:
        with postgres_repository.pool.connection() as connection:
            connection.execute(
                "DELETE FROM leave_requests WHERE request_id = %s",
                (proposal_id,),
            )
            connection.execute(
                "DELETE FROM action_proposals WHERE proposal_id = %s",
                (proposal_id,),
            )


def test_postgres_repository_redacts_trace_and_supports_search(
    postgres_repository: PostgresRepository,
) -> None:
    trace_id = f"trace-test-{uuid4().hex[:12]}"
    postgres_repository.save_trace(
        {
            "trace_id": trace_id,
            "employee_id": "EMP-001",
            "message": "user@example.com",
        }
    )
    try:
        trace = postgres_repository.get_trace(trace_id)
        assert trace is not None
        assert "user@example.com" not in trace["message"]
        assert postgres_repository.lexical_search("cuti tahunan", 3)
    finally:
        with postgres_repository.pool.connection() as connection:
            connection.execute("DELETE FROM traces WHERE trace_id = %s", (trace_id,))
