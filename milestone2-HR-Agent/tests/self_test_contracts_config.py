from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import pytest
from pydantic import ValidationError

from src.config import Settings
from src.contracts import (
    ActionProposal,
    AnalyticsQueryArgs,
    ChatRequest,
    ChatResponse,
    Citation,
    ConfirmActionRequest,
    LeaveBalance,
    ModelToolCall,
    ModelTurn,
    Outcome,
    PolicyChunk,
    PrepareLeaveArgs,
    ProblemDetail,
    SearchPolicyArgs,
    TicketArgs,
    ToolCallSummary,
    UsageSummary,
)
from src.security import redact, stable_safety_id, token_hash


# ==============================================================================
# WBS-02: Security Helpers Verification
# ==============================================================================


def test_token_hash_is_deterministic_sha256() -> None:
    token = "secret-token-demo-12345"
    digest1 = token_hash(token)
    digest2 = token_hash(token)
    assert digest1 == digest2
    assert len(digest1) == 64
    assert all(c in "0123456789abcdef" for c in digest1)
    assert token not in digest1


def test_stable_safety_id_is_deterministic() -> None:
    emp_id = "EMP-001"
    safety_id = stable_safety_id(emp_id)
    assert safety_id == token_hash(emp_id)
    assert len(safety_id) == 64
    assert emp_id not in safety_id


def test_redact_phone_variants() -> None:
    text = (
        "Hubungi via 081234567890 atau +6281234567890 atau "
        "+62 812-3456-7890 atau 0812-3456-7890 atau 0812.3456.7890."
    )
    result = redact(text)
    assert "081234567890" not in result
    assert "+6281234567890" not in result
    assert "+62 812-3456-7890" not in result
    assert "0812-3456-7890" not in result
    assert "0812.3456.7890" not in result
    assert "[REDACTED_PHONE]" in result


def test_redact_token_patterns() -> None:
    text = (
        "Headers: Bearer token-secret_ABC123, "
        "Key: sk-proj-1234567890abcdef, "
        "Api: api-key-prod_xyz999, "
        "Secret: secret-token-foo_bar."
    )
    result = redact(text)
    assert "token-secret_ABC123" not in result
    assert "sk-proj-1234567890abcdef" not in result
    assert "api-key-prod_xyz999" not in result
    assert "secret-token-foo_bar" not in result
    assert "[REDACTED_TOKEN]" in result


def test_redact_medical_terms_from_data() -> None:
    text = (
        "Diagnosa: pasien mengalami flu dan demam tinggi serta migrain. "
        "Riwayat mencatat asma, hipertensi, stroke, dan alergi makanan."
    )
    result = redact(text)
    for term in ["flu", "demam", "migrain", "asma", "hipertensi", "stroke", "alergi"]:
        assert term not in result
    assert "[REDACTED_MEDICAL]" in result


def test_redact_preserves_cuti_sakit() -> None:
    text = "Karyawan mengajukan permohonan cuti sakit karena sakit kepala."
    result = redact(text)
    assert "cuti sakit" in result
    assert "sakit kepala" not in result
    assert "[REDACTED_MEDICAL]" in result


def test_redact_is_strictly_idempotent() -> None:
    text = (
        "Email: user.name+test@example.co.id\n"
        "Phone: 081987654321\n"
        "Token: bearer token-abc_123\n"
        "Penyakit: diagnosis: diabetes militus dan covid-19."
    )
    first_pass = redact(text)
    second_pass = redact(first_pass)
    third_pass = redact(second_pass)
    assert first_pass == second_pass == third_pass


# ==============================================================================
# WBS-03: Contracts Verification
# ==============================================================================


def test_chat_request_validations() -> None:
    req = ChatRequest(message="  Halo, berapa sisa cuti saya?  ")
    assert req.message == "Halo, berapa sisa cuti saya?"

    with pytest.raises(ValidationError):
        ChatRequest(message="   ")

    with pytest.raises(ValidationError):
        ChatRequest(message="")

    with pytest.raises(ValidationError):
        ChatRequest(message="x" * 4001)


def test_confirm_action_request_validation() -> None:
    req = ConfirmActionRequest(idempotency_key="key-12345678")
    assert req.idempotency_key == "key-12345678"

    with pytest.raises(ValidationError):
        ConfirmActionRequest(idempotency_key="short")


def test_tool_argument_contracts_forbid_extra_fields() -> None:
    # PrepareLeaveArgs
    valid_leave = PrepareLeaveArgs(
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 3),
        leave_type="annual",
    )
    assert valid_leave.leave_type == "annual"

    with pytest.raises(ValidationError):
        PrepareLeaveArgs(
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 3),
            leave_type="annual",
            extra_field="malicious_payload",
        )

    # SearchPolicyArgs
    valid_search = SearchPolicyArgs(query="kebijakan cuti", top_k=3)
    assert valid_search.top_k == 3

    with pytest.raises(ValidationError):
        SearchPolicyArgs(query="kebijakan cuti", spoofed_employee_id="EMP-999")

    # TicketArgs
    valid_ticket = TicketArgs(category="privacy", summary="Pertanyaan data pribadi")
    assert valid_ticket.category == "privacy"

    with pytest.raises(ValidationError):
        TicketArgs(category="unknown_category", summary="test")


def test_problem_detail_rfc7807_compliance() -> None:
    problem = ProblemDetail(
        title="Resource Not Found",
        status=404,
        detail="The requested proposal was not found or expired.",
        trace_id="trace-abc-123",
    )
    data = problem.model_dump()
    assert data["type"] == "about:blank"
    assert data["title"] == "Resource Not Found"
    assert data["status"] == 404
    assert data["trace_id"] == "trace-abc-123"


def test_action_proposal_requires_confirmation() -> None:
    proposal = ActionProposal(
        proposal_id="prop-1",
        leave_type="annual",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 3),
        business_days=3,
        validation_summary=["Valid"],
        expires_at=datetime.now(timezone.utc),
    )
    assert proposal.requires_confirmation is True


# ==============================================================================
# WBS-03: Settings & Runtime Configuration Verification
# ==============================================================================


def test_settings_rejects_blank_required_metadata() -> None:
    with pytest.raises(ValidationError):
        Settings(app_name="   ")

    with pytest.raises(ValidationError):
        Settings(environment="")

    with pytest.raises(ValidationError):
        Settings(policy_index_version="   ")


def test_settings_rejects_urls_without_scheme() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="localhost:5432/hr_assistant")

    with pytest.raises(ValidationError):
        Settings(redis_url="redis-host:6379")


def test_settings_normalizes_empty_strings_to_none() -> None:
    settings = Settings(
        openai_api_key="   ",
        openai_base_url="",
        input_cost_per_1m=None,
    )
    assert settings.openai_api_key is None
    assert settings.openai_base_url is None


def test_settings_bounds_and_mode_restrictions() -> None:
    with pytest.raises(ValidationError):
        Settings(model_mode="invalid_mode")

    with pytest.raises(ValidationError):
        Settings(max_agent_turns=0)

    with pytest.raises(ValidationError):
        Settings(max_agent_turns=10)

    with pytest.raises(ValidationError):
        Settings(max_output_tokens=50)


def test_settings_readiness_logic() -> None:
    # Fake mode: only needs database and redis URLs
    fake_settings = Settings(
        model_mode="fake",
        database_url="postgresql://user:pass@localhost:5432/db",
        redis_url="redis://localhost:6379/0",
    )
    assert fake_settings.live_model_ready is False
    assert fake_settings.configuration_ready is True

    # Live mode: requires openai_api_key, agent_model, and embedding_model
    live_incomplete = Settings(
        model_mode="live",
        database_url="postgresql://user:pass@localhost:5432/db",
        redis_url="redis://localhost:6379/0",
        openai_api_key=None,
        agent_model="",
    )
    assert live_incomplete.live_model_ready is False
    assert live_incomplete.configuration_ready is False

    live_complete = Settings(
        model_mode="live",
        database_url="postgresql://user:pass@localhost:5432/db",
        redis_url="redis://localhost:6379/0",
        openai_api_key="sk-fake-test-key",
        agent_model="gpt-4o-mini",
        embedding_model="text-embedding-3-small",
    )
    assert live_complete.live_model_ready is True
    assert live_complete.configuration_ready is True


# ==============================================================================
# WBS-20: Confirmation Safety, Overlap Revalidation, and Balance Reservation
# ==============================================================================


def test_confirm_proposal_revalidates_overlap_and_reserves_balance() -> None:
    from src.repository import ConflictError, MemoryRepository

    repo = MemoryRepository()
    # EMP-001 initial annual balance is 8
    balances_initial = {b.leave_type: b.available_days for b in repo.get_balances("EMP-001")}
    assert balances_initial["annual"] == 8

    prop1 = ActionProposal(
        proposal_id="AP-1",
        leave_type="annual",
        start_date=date(2026, 11, 23),
        end_date=date(2026, 11, 24),
        business_days=2,
        validation_summary=["valid"],
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    prop2 = ActionProposal(
        proposal_id="AP-2",
        leave_type="annual",
        start_date=date(2026, 11, 23),
        end_date=date(2026, 11, 24),
        business_days=2,
        validation_summary=["valid"],
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    repo.save_proposal("EMP-001", prop1)
    repo.save_proposal("EMP-001", prop2)

    # Konfirmasi AP-1 -> berhasil
    res1 = repo.confirm_proposal("EMP-001", "AP-1", "key-ap1-12345")
    assert res1.status == "pending_manager_review"
    assert res1.idempotent_replay is False

    # Verifikasi saldo berkurang sebesar business_days dari AP-1 (8 - 2 = 6)
    balances_after = {b.leave_type: b.available_days for b in repo.get_balances("EMP-001")}
    assert balances_after["annual"] == 6

    # Konfirmasi AP-2 -> wajib melempar ConflictError dengan pesan mengandung "overlap"
    with pytest.raises(ConflictError, match="overlap"):
        repo.confirm_proposal("EMP-001", "AP-2", "key-ap2-12345")


def test_idempotent_replay_succeeds_even_after_proposal_expires() -> None:
    from src.repository import MemoryRepository

    repo = MemoryRepository()
    prop_exp = ActionProposal(
        proposal_id="AP-EXP",
        leave_type="annual",
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 2),
        business_days=2,
        validation_summary=["valid"],
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    repo.save_proposal("EMP-001", prop_exp)
    first_res = repo.confirm_proposal("EMP-001", "AP-EXP", "key-replay-01")
    assert first_res.idempotent_replay is False

    # Ubah expires_at menjadi masa lalu (now - 5 menit)
    owner, prop_item = repo.proposals["AP-EXP"]
    expired_item = prop_item.model_copy(
        update={"expires_at": datetime.now(timezone.utc) - timedelta(minutes=5)}
    )
    repo.proposals["AP-EXP"] = (owner, expired_item)

    # Replay dengan key yang sama -> tetap berhasil dan idempotent_replay is True
    replay_res = repo.confirm_proposal("EMP-001", "AP-EXP", "key-replay-01")
    assert replay_res.request_id == "AP-EXP"
    assert replay_res.idempotent_replay is True


def test_reusing_idempotency_key_across_different_proposals_raises_conflict() -> None:
    from src.repository import ConflictError, MemoryRepository

    repo = MemoryRepository()
    prop_a = ActionProposal(
        proposal_id="AP-A",
        leave_type="annual",
        start_date=date(2026, 12, 10),
        end_date=date(2026, 12, 11),
        business_days=2,
        validation_summary=["valid"],
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    prop_b = ActionProposal(
        proposal_id="AP-B",
        leave_type="annual",
        start_date=date(2026, 12, 15),
        end_date=date(2026, 12, 16),
        business_days=2,
        validation_summary=["valid"],
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    repo.save_proposal("EMP-001", prop_a)
    repo.save_proposal("EMP-001", prop_b)

    # Konfirmasi AP-A dengan "same-key-123"
    res_a = repo.confirm_proposal("EMP-001", "AP-A", "same-key-123")
    assert res_a.idempotent_replay is False

    # Konfirmasi AP-B dengan "same-key-123" -> wajib melempar ConflictError
    with pytest.raises(ConflictError, match="idempotency key"):
        repo.confirm_proposal("EMP-001", "AP-B", "same-key-123")


# ==============================================================================
# WBS-24: Password Hashing & Login Authentication Verification
# ==============================================================================


def test_password_hashing_and_login_authentication() -> None:
    from src.contracts import AuthContext, LoginRequest, LoginResponse
    from src.repository import MemoryRepository
    from src.security import hash_password, verify_password

    # 1. Test hash_password and verify_password
    pwd = "Secret#Password123"
    hashed = hash_password(pwd)
    assert hashed.startswith("pbkdf2_sha256$")
    assert verify_password(pwd, hashed) is True
    assert verify_password("Wrong#Password", hashed) is False
    assert verify_password("", hashed) is False
    assert verify_password(pwd, "invalid_format") is False
    assert verify_password(pwd, "") is False

    # 2. Test AuthContext contract supports manager role and organization fields
    auth_emp = AuthContext(employee_id="EMP-001", display_name="Alya")
    assert auth_emp.role == "employee"
    assert auth_emp.department is None
    assert auth_emp.manager_id is None

    auth_mgr = AuthContext(
        employee_id="MGR-001",
        display_name="Raka",
        role="manager",
        department="Engineering",
    )
    assert auth_mgr.role == "manager"
    assert auth_mgr.department == "Engineering"

    # 3. Test LoginRequest and LoginResponse contracts
    req = LoginRequest(username="alya", password="Password#123")
    assert req.username == "alya"
    resp = LoginResponse(access_token="token-test", profile=auth_emp)
    assert resp.access_token == "token-test"
    assert resp.token_type == "bearer"
    assert resp.profile.employee_id == "EMP-001"

    # 4. Test MemoryRepository.authenticate_password
    repo = MemoryRepository()

    # Valid employee login
    res_alya = repo.authenticate_password("alya", "Password#123")
    assert isinstance(res_alya, LoginResponse)
    assert res_alya.profile.employee_id == "EMP-001"
    assert res_alya.access_token == "token-alya"
    assert res_alya.profile.role == "employee"
    assert res_alya.profile.department == "Engineering"

    # Test login by employee_id as identifier
    res_alya_id = repo.authenticate_password("EMP-001", "Password#123")
    assert isinstance(res_alya_id, LoginResponse)
    assert res_alya_id.profile.employee_id == "EMP-001"

    # Manager login
    res_raka = repo.authenticate_password("raka", "Password#123")
    assert isinstance(res_raka, LoginResponse)
    assert res_raka.profile.employee_id == "MGR-001"
    assert res_raka.profile.role == "manager"
    assert res_raka.access_token == "token-manager"

    # Monitoring admin login
    res_admin = repo.authenticate_password("admin", "Password#123")
    assert isinstance(res_admin, LoginResponse)
    assert res_admin.profile.employee_id == "ADM-001"
    assert res_admin.profile.role == "monitoring_admin"

    # Invalid password -> returns None
    assert repo.authenticate_password("alya", "WrongPassword") is None
    assert repo.authenticate_password("raka", "WrongPassword") is None
    assert repo.authenticate_password("admin", "WrongPassword") is None

    # Unknown username -> returns None
    assert repo.authenticate_password("nonexistent_user", "Password#123") is None


def test_api_login_endpoint() -> None:
    from fastapi.testclient import TestClient
    from src.agent import AgentService
    from src.api import create_app
    from src.cache import NullCache
    from src.config import Settings
    from src.providers import DeterministicProvider
    from src.repository import MemoryRepository
    from src.retrieval import RetrievalService
    from src.tools import ToolExecutor

    settings = Settings(model_mode="fake")
    repo = MemoryRepository()
    cache = NullCache()
    provider = DeterministicProvider()
    retrieval = RetrievalService(repo, provider, cache, 0)
    tools = ToolExecutor(repo, retrieval, settings)
    agent = AgentService(repo, provider, tools, settings)
    app = create_app(settings=settings, repository=repo, cache=cache, agent=agent)
    client = TestClient(app)

    # Valid login
    res = client.post("/api/v1/auth/login", json={"username": "alya", "password": "Password#123"})
    assert res.status_code == 200
    data = res.json()
    assert data["access_token"] == "token-alya"
    assert data["token_type"] == "bearer"
    assert data["profile"]["employee_id"] == "EMP-001"
    assert data["profile"]["role"] == "employee"

    # Manager login
    res_mgr = client.post("/api/v1/auth/login", json={"username": "raka", "password": "Password#123"})
    assert res_mgr.status_code == 200
    assert res_mgr.json()["profile"]["role"] == "manager"

    # Invalid password -> 401 ProblemDetail
    res_err = client.post("/api/v1/auth/login", json={"username": "alya", "password": "wrong"})
    assert res_err.status_code == 401
    err_data = res_err.json()
    assert err_data["title"] == "Unauthorized"
    assert err_data["status"] == 401
    assert "Invalid username or password" in err_data["detail"]

    # Invalid request body -> 422
    assert client.post("/api/v1/auth/login", json={"username": ""}).status_code == 422


def test_analytics_query_args_validation() -> None:
    # default threshold is 3
    args_default = AnalyticsQueryArgs()
    assert args_default.low_balance_threshold == 3
    assert args_default.metric_focus == "overview"

    # custom valid threshold
    args_custom = AnalyticsQueryArgs(metric_focus="balance_risks", low_balance_threshold=7)
    assert args_custom.low_balance_threshold == 7
    assert args_custom.metric_focus == "balance_risks"

    # boundaries: ge=1, le=30
    assert AnalyticsQueryArgs(low_balance_threshold=1).low_balance_threshold == 1
    assert AnalyticsQueryArgs(low_balance_threshold=30).low_balance_threshold == 30

    with pytest.raises(ValidationError):
        AnalyticsQueryArgs(low_balance_threshold=0)

    with pytest.raises(ValidationError):
        AnalyticsQueryArgs(low_balance_threshold=31)




