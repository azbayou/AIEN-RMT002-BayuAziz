from __future__ import annotations

from datetime import date
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from src.agent import AgentService
from src.api import create_app
from src.cache import NullCache
from src.config import Settings, get_settings
from src.providers import DeterministicProvider
from src.repository import PostgresRepository
from src.retrieval import RetrievalService
from src.tools import ToolExecutor


@pytest.fixture(scope="session")
def pg_pool_repo() -> Iterator[PostgresRepository]:
    env_settings = get_settings()
    repo = PostgresRepository(env_settings.database_url, env_settings.embedding_dimensions)
    yield repo
    repo.pool.close()


@pytest.fixture(scope="session")
def baseline_db_state(pg_pool_repo: PostgresRepository) -> dict[str, list[str]]:
    with pg_pool_repo.pool.connection() as conn:
        proposals = [r["proposal_id"] for r in conn.execute("SELECT proposal_id FROM action_proposals").fetchall()]
        requests = [r["request_id"] for r in conn.execute("SELECT request_id FROM leave_requests").fetchall()]
        tickets = [r["ticket_id"] for r in conn.execute("SELECT ticket_id FROM tickets").fetchall()]
        traces = [r["trace_id"] for r in conn.execute("SELECT trace_id FROM traces").fetchall()]
    return {
        "proposal_ids": proposals,
        "request_ids": requests,
        "ticket_ids": tickets,
        "trace_ids": traces,
    }


@pytest.fixture
def settings() -> Settings:
    base = get_settings()
    return base.model_copy(
        update={
            "model_mode": "fake",
            "proposal_ttl_minutes": 15,
            "max_agent_turns": 4,
            "max_tool_calls": 6,
            "opik_enabled": False,
        }
    )


@pytest.fixture
def repository(
    pg_pool_repo: PostgresRepository,
    baseline_db_state: dict[str, list[str]],
) -> Iterator[PostgresRepository]:
    try:
        yield pg_pool_repo
    finally:
        with pg_pool_repo.pool.connection() as conn:
            conn.execute(
                "DELETE FROM approval_audit_logs WHERE NOT (request_id = ANY(%s::text[]))",
                (baseline_db_state["request_ids"],),
            )
            conn.execute(
                "DELETE FROM leave_attachments WHERE NOT (request_id = ANY(%s::text[]))",
                (baseline_db_state["request_ids"],),
            )
            conn.execute(
                "DELETE FROM leave_requests WHERE NOT (request_id = ANY(%s::text[]))",
                (baseline_db_state["request_ids"],),
            )
            conn.execute(
                "DELETE FROM action_proposals WHERE NOT (proposal_id = ANY(%s::text[]))",
                (baseline_db_state["proposal_ids"],),
            )
            conn.execute(
                "DELETE FROM tickets WHERE NOT (ticket_id = ANY(%s::text[]))",
                (baseline_db_state["ticket_ids"],),
            )
            conn.execute(
                "DELETE FROM traces WHERE NOT (trace_id = ANY(%s::text[]))",
                (baseline_db_state["trace_ids"],),
            )


@pytest.fixture
def client(repository: PostgresRepository, settings: Settings) -> TestClient:
    provider = DeterministicProvider(settings.embedding_dimensions)
    cache = NullCache()
    retrieval = RetrievalService(repository, provider, cache, 0)
    tools = ToolExecutor(repository, retrieval, settings, today_factory=lambda: date(2026, 9, 23))
    agent = AgentService(repository, provider, tools, settings)
    app = create_app(settings=settings, repository=repository, cache=cache, agent=agent)
    return TestClient(app)

