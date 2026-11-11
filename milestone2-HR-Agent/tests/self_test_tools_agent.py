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
from src.domain import DomainError
from src.providers import DeterministicProvider
from src.repository import MemoryRepository
from src.retrieval import RetrievalService
from src.tools import (
    MANAGER_ANALYTICS_TOOL_SCHEMA,
    TOOL_SCHEMAS,
    ToolExecutor,
    get_tools_for_role,
)


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


# ==============================================================================
# WBS-21: DomainError Handling, Citations Gate, Ticket Deduplication, Telemetry
# ==============================================================================


def test_domain_error_sets_blocked_status_without_polluting_error_rate(repository: MemoryRepository) -> None:
    class PastLeaveProposalProvider:
        def embed(self, texts):
            return [[0.0] * 8 for _ in texts]

        def respond(self, **kwargs):
            return ModelTurn(
                response_id="turn-past-leave",
                tool_calls=[
                    ModelToolCall(
                        call_id="call-past",
                        name="prepare_leave_request",
                        arguments={
                            "start_date": "2025-01-02",
                            "end_date": "2025-01-03",
                            "leave_type": "annual",
                            "reason": "Cuti lampau",
                        },
                    )
                ],
                input_tokens=15,
                output_tokens=10,
            )

    agent = _build_test_service(repository, PastLeaveProposalProvider())
    auth = AuthContext(employee_id="EMP-001", display_name="Alya")

    response = agent.run(ChatRequest(message="Ajukan cuti tahunan 2025-01-02"), auth)

    assert response.outcome == Outcome.abstained
    assert "masa lalu" in response.answer
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].status == "blocked"

    trace = repository.get_trace(response.trace_id)
    assert trace is not None
    assert trace["error"] is None
    assert "masa lalu" in trace["blocked_reason"]
    assert repository.monitoring_summary()["error_count"] == 0


def test_trace_records_retrieved_document_ids_and_citations(repository: MemoryRepository) -> None:
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
    agent = _build_test_service(repository, provider)
    auth = AuthContext(employee_id="EMP-001", display_name="Alya")

    response = agent.run(ChatRequest(message="Berapa jatah cuti tahunan?"), auth)

    assert response.outcome == Outcome.answered
    trace = repository.get_trace(response.trace_id)
    assert trace is not None
    assert trace["retrieved_document_ids"] == ["HR-LEAVE-001"]
    assert trace["citation_ids"] == ["HR-LEAVE-001"]


def test_create_ticket_is_idempotent_for_identical_summary(repository: MemoryRepository) -> None:
    first_id = repository.create_ticket("EMP-001", "privacy", "Pertanyaan sama")
    second_id = repository.create_ticket("EMP-001", "privacy", "Pertanyaan sama")
    assert first_id == second_id

    diff_cat_id = repository.create_ticket("EMP-001", "payroll", "Pertanyaan sama")
    assert diff_cat_id != first_id

    diff_emp_id = repository.create_ticket("EMP-002", "privacy", "Pertanyaan sama")
    assert diff_emp_id != first_id


def test_analytics_tool_is_role_gated_for_manager_and_admin(repository: MemoryRepository) -> None:
    assert len(get_tools_for_role("employee")) == 4
    assert len(get_tools_for_role("manager")) == 5
    assert len(get_tools_for_role("monitoring_admin")) == 5

    assert "low_balance_threshold" in MANAGER_ANALYTICS_TOOL_SCHEMA["parameters"]["properties"]
    prop = MANAGER_ANALYTICS_TOOL_SCHEMA["parameters"]["properties"]["low_balance_threshold"]
    assert prop["type"] == "integer"
    assert prop["minimum"] == 1
    assert prop["maximum"] == 30

    retrieval = RetrievalService(repository, DeterministicProvider(), NullCache(), 0)
    tools = ToolExecutor(repository, retrieval, Settings(model_mode="fake"))

    auth_emp = AuthContext(employee_id="EMP-001", display_name="Alya", role="employee")
    with pytest.raises(DomainError, match="akses analitik hanya diizinkan untuk Manager atau HR Admin"):
        tools.execute("get_team_hr_analytics", {"metric_focus": "overview"}, auth_emp)

    auth_mgr = AuthContext(employee_id="MGR-001", display_name="Raka", role="manager")
    result, proposal = tools.execute("get_team_hr_analytics", {"metric_focus": "overview"}, auth_mgr)
    assert proposal is None
    assert isinstance(result, dict)
    assert result["team_size"] >= 2
    assert "requests_by_status" in result
    assert "low_balance_employees" in result
    low_emp_ids = [e["employee_id"] for e in result["low_balance_employees"]]
    assert "EMP-002" in low_emp_ids
    emp_002_data = next(e for e in result["low_balance_employees"] if e["employee_id"] == "EMP-002")
    assert emp_002_data["annual_remaining"] == 3
    assert result["low_balance_threshold"] == 3

    # Dynamic threshold: threshold 1 should exclude EMP-002 who has 3 remaining days
    result_t1, _ = tools.execute(
        "get_team_hr_analytics",
        {"metric_focus": "overview", "low_balance_threshold": 1},
        auth_mgr,
    )
    assert result_t1["low_balance_threshold"] == 1
    assert "EMP-002" not in [e["employee_id"] for e in result_t1["low_balance_employees"]]


def test_agent_answers_analytics_query_for_manager(repository: MemoryRepository) -> None:
    provider = DeterministicProvider()
    agent = _build_test_service(repository, provider)
    auth_mgr = AuthContext(employee_id="MGR-001", display_name="Raka", role="manager")

    response = agent.run(
        ChatRequest(message="Tampilkan analitik dan statistik cuti tim"),
        auth_mgr,
    )

    assert response.outcome == Outcome.answered
    assert any(tc.name == "get_team_hr_analytics" and tc.status == "ok" for tc in response.tool_calls)
    assert len(response.answer) > 0


def test_api_analytics_overview_endpoint(repository: MemoryRepository) -> None:
    from fastapi.testclient import TestClient
    from src.api import create_app

    settings = Settings(model_mode="fake")
    cache = NullCache()
    provider = DeterministicProvider()
    tools = ToolExecutor(repository, RetrievalService(repository, provider, cache, 0), settings)
    agent = AgentService(repository, provider, tools, settings)
    app = create_app(settings=settings, repository=repository, cache=cache, agent=agent)
    client = TestClient(app)

    assert client.get("/api/v1/analytics/overview").status_code == 401
    assert client.get("/api/v1/analytics/overview", headers={"Authorization": "Bearer token-alya"}).status_code == 403

    res_mgr = client.get("/api/v1/analytics/overview", headers={"Authorization": "Bearer token-manager"})
    assert res_mgr.status_code == 200
    mgr_data = res_mgr.json()
    assert mgr_data["scope"] == "team"
    assert mgr_data["team_size"] >= 2
    assert "low_balance_employees" in mgr_data
    assert mgr_data["low_balance_threshold"] == 3

    # Dynamic low_balance_threshold query parameter
    res_mgr_custom = client.get(
        "/api/v1/analytics/overview?low_balance_threshold=1",
        headers={"Authorization": "Bearer token-manager"},
    )
    assert res_mgr_custom.status_code == 200
    assert res_mgr_custom.json()["low_balance_threshold"] == 1

    # Out of range query parameters -> 422
    assert client.get(
        "/api/v1/analytics/overview?low_balance_threshold=0",
        headers={"Authorization": "Bearer token-manager"},
    ).status_code == 422
    assert client.get(
        "/api/v1/analytics/overview?low_balance_threshold=31",
        headers={"Authorization": "Bearer token-manager"},
    ).status_code == 422

    res_adm = client.get("/api/v1/analytics/overview", headers={"Authorization": "Bearer token-admin"})
    assert res_adm.status_code == 200
    adm_data = res_adm.json()
    assert adm_data["scope"] == "organization"
    assert "ai_operations" in adm_data


def test_dynamic_sick_leave_policy_threshold(repository: MemoryRepository, settings: Settings) -> None:
    from src.domain import get_sick_leave_doc_threshold, validate_leave_request
    from src.contracts import PrepareLeaveArgs, LeaveBalance
    from datetime import date

    # 1. Base threshold from policy file (default 2 days)
    thresh = get_sick_leave_doc_threshold()
    assert thresh == 2

    # 2. Dynamic threshold parsing when policy text changes
    assert get_sick_leave_doc_threshold("Cuti sakit lebih dari tiga hari kerja berturut-turut memerlukan surat dokter") == 3
    assert get_sick_leave_doc_threshold("Cuti sakit lebih dari 1 hari kerja memerlukan surat dokter") == 1
    assert get_sick_leave_doc_threshold("Cuti sakit lebih dari empat hari kerja berturut-turut") == 4

    balances = [LeaveBalance(leave_type="sick", available_days=10, as_of_date=date(2026, 1, 1))]

    # 3. Sick leave <= threshold (e.g. 1 day): attachment is optional
    args_1d = PrepareLeaveArgs(start_date=date(2026, 11, 12), end_date=date(2026, 11, 12), leave_type="sick")
    days_1d, summary_1d = validate_leave_request(args_1d, balances, False, date(2026, 11, 10))
    assert days_1d == 1
    assert any("opsional" in s.lower() for s in summary_1d)

    # 4. Sick leave > threshold (e.g. 3 days: Thu, Fri, Mon): attachment is mandatory
    args_3d = PrepareLeaveArgs(start_date=date(2026, 11, 12), end_date=date(2026, 11, 16), leave_type="sick")
    days_3d, summary_3d = validate_leave_request(args_3d, balances, False, date(2026, 11, 10))
    assert days_3d == 3
    assert any("wajib" in s.lower() for s in summary_3d)

    # 5. Tool prepare_leave_request sets requires_attachment accurately
    auth = AuthContext(employee_id="EMP-001", display_name="Alya Pratama", role="employee")
    retrieval = RetrievalService(repository, DeterministicProvider(), NullCache(), 300)
    tools = ToolExecutor(repository, retrieval, settings, today_factory=lambda: date(2026, 11, 10))

    # Tool execution for 1 day sick leave
    prop_1d, _ = tools.execute("prepare_leave_request", {
        "start_date": "2026-11-12",
        "end_date": "2026-11-12",
        "leave_type": "sick",
        "reason": "Demam ringan",
    }, auth)
    assert prop_1d.requires_attachment is False

    # Tool execution for 3 days sick leave
    prop_3d, _ = tools.execute("prepare_leave_request", {
        "start_date": "2026-11-12",
        "end_date": "2026-11-16",
        "leave_type": "sick",
        "reason": "Istirahat intensif",
    }, auth)
    assert prop_3d.requires_attachment is True

    # 6. RAG Verification: When a new policy chunk is stored in Vector DB / Repository,
    # the threshold dynamically adapts from RAG retrieval!
    custom_chunk = PolicyChunk(
        chunk_id="HR-LEAVE-002-v2",
        document_id="HR-LEAVE-002",
        title="Kebijakan Cuti Sakit Revisi",
        version="2.0",
        effective_date=date(2026, 1, 1),
        section="Pemberitahuan",
        content="Cuti sakit lebih dari empat hari kerja berturut-turut memerlukan dokumen pendukung surat dokter.",
    )
    repository.chunks = [custom_chunk]
    prop_3d_new, _ = tools.execute("prepare_leave_request", {
        "start_date": "2026-11-12",
        "end_date": "2026-11-16",
        "leave_type": "sick",
        "reason": "Istirahat intensif",
    }, auth)
    assert prop_3d_new.requires_attachment is False
    assert any("opsional" in s.lower() for s in prop_3d_new.validation_summary)


def test_dynamic_annual_leave_policy_lead_days(repository: MemoryRepository, settings: Settings) -> None:
    from src.domain import get_annual_leave_lead_days
    from src.contracts import PolicyChunk

    # 1. Base lead days from policy file (default 3 days)
    assert get_annual_leave_lead_days() == 3

    # 2. Dynamic parsing
    assert get_annual_leave_lead_days("Pengajuan dilakukan paling lambat dua hari kerja sebelum tanggal mulai") == 2
    assert get_annual_leave_lead_days("Pengajuan minimal satu hari kerja sebelumnya") == 1
    assert get_annual_leave_lead_days("Pengajuan cuti tahunan paling lambat 5 hari kerja") == 5

    # 3. Tool execution with RAG retrieval
    auth = AuthContext(employee_id="EMP-001", display_name="Alya Pratama", role="employee")
    retrieval = RetrievalService(repository, DeterministicProvider(), NullCache(), 300)
    tools = ToolExecutor(repository, retrieval, settings, today_factory=lambda: date(2026, 9, 23))

    # By default, start_date=2026-09-28 has only 2 business days lead time (Thu 24, Fri 25), so fails with 3 days rule
    with pytest.raises(Exception, match="tiga hari kerja"):
        tools.execute("prepare_leave_request", {
            "start_date": "2026-09-28",
            "end_date": "2026-09-28",
            "leave_type": "annual",
            "reason": "Liburan",
        }, auth)

    # 4. RAG Verification: When a new policy chunk is stored in Vector DB / Repository,
    # the threshold dynamically adapts from RAG retrieval!
    custom_chunk = PolicyChunk(
        chunk_id="HR-LEAVE-001-v3",
        document_id="HR-LEAVE-001",
        title="Kebijakan Cuti Tahunan Revisi",
        version="3.0",
        effective_date=date(2026, 1, 1),
        section="Pengajuan",
        content="Pengajuan cuti tahunan dilakukan paling lambat dua hari kerja sebelum tanggal mulai.",
    )
    repository.chunks = [custom_chunk]

    # Now Sep 28 has 2 business days lead time, which satisfies the 2-day requirement retrieved via RAG!
    prop, _ = tools.execute("prepare_leave_request", {
        "start_date": "2026-09-28",
        "end_date": "2026-09-28",
        "leave_type": "annual",
        "reason": "Liburan",
    }, auth)
    assert prop.business_days == 1


def test_requires_evidence_policy_scope() -> None:
    from src.agent import AgentService

    keywords = ["carryover", "sisa", "bawa", "dibawa", "parental", "eskalasi", "pengecualian", "izin"]
    for kw in keywords:
        msg = f"Bagaimana aturan terkait {kw} cuti kantor?"
        assert AgentService._requires_evidence(msg) is True, f"Failed for keyword: {kw}"

    assert AgentService._requires_evidence("Halo selamat pagi Miyo") is False


def test_system_instructions_carryover_and_exception() -> None:
    from src.agent import SYSTEM_INSTRUCTIONS

    assert "[HR-LEAVE-001]" in SYSTEM_INSTRUCTIONS
    assert "carryover" in SYSTEM_INSTRUCTIONS
    assert "5 hari kerja" in SYSTEM_INSTRUCTIONS
    assert "31 Maret" in SYSTEM_INSTRUCTIONS
    assert "create_hr_ticket(category=\"leave_exception\")" in SYSTEM_INSTRUCTIONS



