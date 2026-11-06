from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from src.cache import NullCache
from src.config import Settings
from src.contracts import AuthContext
from src.providers import DeterministicProvider
from src.repository import MemoryRepository
from src.retrieval import RetrievalService
from src.tools import TOOL_SCHEMAS, ToolExecutor


def executor(repository: MemoryRepository) -> ToolExecutor:
    retrieval = RetrievalService(repository, DeterministicProvider(), NullCache(), 0)
    return ToolExecutor(
        repository,
        retrieval,
        Settings(model_mode="fake"),
        today_factory=lambda: date(2026, 9, 23),
    )


def test_tool_schemas_are_strict_and_have_complete_required_properties() -> None:
    assert {schema["name"] for schema in TOOL_SCHEMAS} == {
        "search_hr_policy",
        "get_my_leave_balance",
        "prepare_leave_request",
        "create_hr_ticket",
    }
    for schema in TOOL_SCHEMAS:
        parameters = schema["parameters"]
        assert schema["strict"] is True
        assert parameters["additionalProperties"] is False
        assert set(parameters["required"]) == set(parameters["properties"])


def test_malformed_and_unknown_tool_calls_are_rejected(repository: MemoryRepository) -> None:
    tools = executor(repository)
    auth = AuthContext(employee_id="EMP-001", display_name="Alya")
    with pytest.raises(ValidationError):
        tools.execute("search_hr_policy", {"query": ""}, auth)
    with pytest.raises(ValueError, match="tidak menerima argumen"):
        tools.execute("get_my_leave_balance", {"employee_id": "EMP-002"}, auth)
    with pytest.raises(ValueError, match="unknown tool"):
        tools.execute("approve_leave", {}, auth)


def test_prepare_leave_is_identity_bound_and_does_not_create_request(
    repository: MemoryRepository,
) -> None:
    tools = executor(repository)
    proposal, _ = tools.execute(
        "prepare_leave_request",
        {
            "start_date": "2026-10-01",
            "end_date": "2026-10-02",
            "leave_type": "sick",
            "reason": "Pemulihan",
        },
        AuthContext(employee_id="EMP-001", display_name="Alya"),
    )
    assert proposal.requires_confirmation is True
    assert proposal.expires_at is not None
    assert repository.list_leave_requests("EMP-001") == []
    assert repository.get_proposal(proposal.proposal_id)[0] == "EMP-001"


def test_prepare_leave_rejects_employee_id_spoofing(repository: MemoryRepository) -> None:
    tools = executor(repository)
    with pytest.raises(ValidationError):
        tools.execute(
            "prepare_leave_request",
            {
                "start_date": "2026-10-01",
                "end_date": "2026-10-02",
                "leave_type": "sick",
                "reason": "Pemulihan",
                "employee_id": "EMP-002",
            },
            AuthContext(employee_id="EMP-001", display_name="Alya"),
        )
