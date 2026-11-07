from __future__ import annotations

from datetime import date, datetime, timezone
import pytest
from pydantic import ValidationError

from src.config import Settings
from src.contracts import (
    ActionProposal,
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
