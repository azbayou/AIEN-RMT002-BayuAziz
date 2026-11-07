from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock
import pytest
from pydantic import ValidationError

from src.agent import AgentService
from src.cache import NullCache
from src.config import Settings
from src.contracts import (
    ActionProposal,
    AuthContext,
    ChatRequest,
    ModelToolCall,
    ModelTurn,
    Outcome,
    PolicyChunk,
)
from src.providers import DeterministicProvider
from src.repository import MemoryRepository
from src.retrieval import RetrievalService
from src.tools import TOOL_SCHEMAS, ToolExecutor


# ==============================================================================
# Helper fixtures / builders
# ==============================================================================


def _build_test_service(
    repository: MemoryRepository,
    provider,
    settings: Settings | None = None,
) -> AgentService:
    settings = settings or Settings(model_mode="fake")
    retrieval = RetrievalService(repository, provider, NullCache(), 0)
    tools = ToolExecutor(
        repository,
        retrieval,
        settings,
        today_factory=lambda: date(2026, 9, 23),
    )
    return AgentService(repository, provider, tools, settings)


# ==============================================================================
# WBS-09: Tools Execution & Schemas Verification
# ==============================================================================


def test_tool_schemas_compliance() -> None:
    assert len(TOOL_SCHEMAS) == 4
    schema_map = {s["name"]: s for s in TOOL_SCHEMAS}

    for name in ("search_hr_policy", "get_my_leave_balance", "prepare_leave_request", "create_hr_ticket"):
        assert name in schema_map
        assert schema_map[name]["strict"] is True
        assert schema_map[name]["parameters"]["additionalProperties"] is False


def test_tool_search_hr_policy_bounds(repository: MemoryRepository) -> None:
    retrieval = RetrievalService(repository, DeterministicProvider(), NullCache(), 0)
    tools = ToolExecutor(repository, retrieval, Settings(model_mode="fake"))
    auth = AuthContext(employee_id="EMP-001", display_name="Alya")

    # query too short (< 2)
    with pytest.raises(ValidationError):
        tools.execute("search_hr_policy", {"query": "a", "top_k": 3}, auth)

    # top_k too large (> 5)
    with pytest.raises(ValidationError):
        tools.execute("search_hr_policy", {"query": "cuti", "top_k": 10}, auth)

    # valid query
    results, proposal = tools.execute("search_hr_policy", {"query": "cuti", "top_k": 3}, auth)
    assert isinstance(results, list)
    assert proposal is None


def test_tool_balance_rejects_any_argument(repository: MemoryRepository) -> None:
    retrieval = RetrievalService(repository, DeterministicProvider(), NullCache(), 0)
    tools = ToolExecutor(repository, retrieval, Settings(model_mode="fake"))
    auth = AuthContext(employee_id="EMP-001", display_name="Alya")

    with pytest.raises(ValueError, match="tidak menerima argumen"):
        tools.execute("get_my_leave_balance", {"unexpected": "value"}, auth)

    balances, proposal = tools.execute("get_my_leave_balance", {}, auth)
    assert len(balances) >= 1
    assert proposal is None


def test_tool_create_ticket_execution(repository: MemoryRepository) -> None:
    retrieval = RetrievalService(repository, DeterministicProvider(), NullCache(), 0)
    tools = ToolExecutor(repository, retrieval, Settings(model_mode="fake"))
    auth = AuthContext(employee_id="EMP-001", display_name="Alya")

    ticket_id, proposal = tools.execute(
        "create_hr_ticket",
        {"category": "privacy", "summary": "Pertanyaan mengenai telemetry dan data"},
        auth,
    )
    assert ticket_id.startswith("T-")
    assert proposal is None
    assert repository.tickets[ticket_id]["employee_id"] == "EMP-001"


# ==============================================================================
# WBS-10: Agent Multi-Turn, Outcomes, & Cost Tracking
# ==============================================================================


class MultiTurnSuccessProvider:
    """Simulates turn 1 (tool call to policy search) then turn 2 (final answer with valid citation)."""

    def __init__(self, sample_chunk: PolicyChunk) -> None:
        self.turn = 0
        self.chunk = sample_chunk

    def embed(self, texts):
        return [[0.0] * 8 for _ in texts]

    def respond(self, **kwargs):
        self.turn += 1
        if self.turn == 1:
            return ModelTurn(
                response_id="turn-1",
                tool_calls=[
                    ModelToolCall(
                        call_id="call-search",
                        name="search_hr_policy",
                        arguments={"query": "cuti tahunan", "top_k": 1},
                    )
                ],
                input_tokens=10,
                output_tokens=5,
            )
        return ModelTurn(
            response_id="turn-2",
            text=f"Berdasarkan [{self.chunk.document_id}], jatah cuti tahunan adalah 12 hari kerja.",
            input_tokens=20,
            output_tokens=15,
        )


def test_agent_multi_turn_with_valid_citation(repository: MemoryRepository) -> None:
    sample = PolicyChunk(
        chunk_id="HR-LEAVE-001:c1",
        document_id="HR-LEAVE-001",
        title="Kebijakan Cuti",
        section="Ketentuan",
        version="1.0",
        effective_date="2026-01-01",
        content="Jatah cuti tahunan adalah 12 hari kerja.",
    )
    repository.chunks = [sample]

    provider = MultiTurnSuccessProvider(sample)
    settings = Settings(
        model_mode="fake",
        input_cost_per_1m=1.50,
        output_cost_per_1m=2.00,
    )
    agent = _build_test_service(repository, provider, settings)
    auth = AuthContext(employee_id="EMP-001", display_name="Alya")

    response = agent.run(ChatRequest(message="Berapa jatah cuti tahunan?"), auth)

    assert response.outcome == Outcome.answered
    assert len(response.citations) == 1
    assert response.citations[0].document_id == "HR-LEAVE-001"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "search_hr_policy"

    # Verify usage & cost
    assert response.usage.input_tokens > 0
    assert response.usage.output_tokens > 0
    assert response.usage.estimated_cost is not None
    assert response.usage.estimated_cost > 0


class LeaveProposalProvider:
    """Simulates preparing a leave request."""

    def __init__(self) -> None:
        self.turn = 0

    def embed(self, texts):
        return [[0.0] * 8 for _ in texts]

    def respond(self, **kwargs):
        self.turn += 1
        if self.turn == 1:
            return ModelTurn(
                response_id="turn-prep",
                tool_calls=[
                    ModelToolCall(
                        call_id="call-prep",
                        name="prepare_leave_request",
                        arguments={
                            "start_date": "2026-10-01",
                            "end_date": "2026-10-02",
                            "leave_type": "sick",
                            "reason": "Sakit flu",
                        },
                    )
                ],
                input_tokens=15,
                output_tokens=10,
            )
        return ModelTurn(
            response_id="turn-ans",
            text="Proposal cuti Anda sudah disiapkan dan menunggu konfirmasi.",
            input_tokens=25,
            output_tokens=12,
        )


def test_agent_proposal_outcome(repository: MemoryRepository) -> None:
    provider = LeaveProposalProvider()
    agent = _build_test_service(repository, provider)
    auth = AuthContext(employee_id="EMP-001", display_name="Alya")

    response = agent.run(ChatRequest(message="Saya mau ajukan cuti"), auth)

    assert response.outcome == Outcome.action_proposed
    assert response.action_proposal is not None
    assert response.action_proposal.leave_type == "sick"
    assert response.action_proposal.business_days == 2
    assert response.action_proposal.requires_confirmation is True


def test_agent_tool_call_budget_enforcement(repository: MemoryRepository) -> None:
    class ExcessiveToolProvider:
        def embed(self, texts):
            return [[0.0] * 8 for _ in texts]

        def respond(self, **kwargs):
            return ModelTurn(
                response_id="turn-excessive",
                tool_calls=[
                    ModelToolCall(call_id=f"c-{i}", name="get_my_leave_balance", arguments={})
                    for i in range(10)
                ],
            )

    settings = Settings(model_mode="fake", max_tool_calls=4)
    agent = _build_test_service(repository, ExcessiveToolProvider(), settings)
    auth = AuthContext(employee_id="EMP-001", display_name="Alya")

    response = agent.run(ChatRequest(message="Cek saldo"), auth)
    assert response.outcome == Outcome.abstained
    trace = repository.get_trace(response.trace_id)
    assert "budget exceeded" in trace["error"]
