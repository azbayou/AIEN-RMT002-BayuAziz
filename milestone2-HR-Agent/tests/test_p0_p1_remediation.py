from __future__ import annotations

import base64
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path

from fastapi.testclient import TestClient
import httpx
import pytest

from src.agent import AgentService
from src.api import create_app
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
    PrepareLeaveArgs,
)
from src.domain import (
    DomainError,
    compute_earliest_annual_leave_date,
    count_lead_business_days,
    validate_leave_request,
)
from src.providers import DeterministicProvider
from src.repository import MemoryRepository, redact_trace
from src.retrieval import RetrievalService
from src import run_evaluation
from src import security
from src.tools import ToolExecutor


AUTH_ALYA = {"Authorization": "Bearer token-alya"}
AUTH_ADMIN = {"Authorization": "Bearer token-admin"}


class ScriptedProvider:
    def __init__(self, turns: list[ModelTurn | Exception]) -> None:
        self._turns = list(turns)
        self._index = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 8 for _ in texts]

    def respond(self, **kwargs) -> ModelTurn:
        item = self._turns[self._index]
        self._index += 1
        if isinstance(item, Exception):
            raise item
        return item


def _build_runtime(
    repository: MemoryRepository,
    *,
    reference_date: date = date(2026, 10, 26),
    provider=None,
):
    settings = Settings(
        _env_file=None,
        model_mode="fake",
        opik_enabled=False,
        reference_date=reference_date,
    )
    active_provider = provider or DeterministicProvider()
    cache = NullCache()
    retrieval = RetrievalService(repository, active_provider, cache, 0)
    tools = ToolExecutor(
        repository,
        retrieval,
        settings,
        today_factory=lambda: reference_date,
    )
    agent = AgentService(repository, active_provider, tools, settings)
    app = create_app(settings=settings, repository=repository, cache=cache, agent=agent)
    return settings, retrieval, tools, agent, TestClient(app)


# (a) Clean-env Settings & pure in-memory MemoryRepository
def test_settings_and_memory_repository_work_without_env_or_db(monkeypatch) -> None:
    for var in ("DATABASE_URL", "OPENAI_API_KEY", "REDIS_URL", "MODEL_MODE", "REFERENCE_DATE"):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(_env_file=None)
    assert settings.database_url == ""
    assert settings.configuration_ready is False

    repo = MemoryRepository()
    assert repo.health() is True
    assert repo.authenticate("token-alya").employee_id == "EMP-001"
    alya_annual = next(b for b in repo.get_balances("EMP-001") if b.leave_type == "annual")
    bima_annual = next(b for b in repo.get_balances("EMP-002") if b.leave_type == "annual")
    assert alya_annual.available_days == 8
    assert bima_annual.available_days == 3
    assert len(repo.list_monitoring_rules()) >= 2


# (b) Dynamic DB Policy Matrix updates rules, calendar, and leave validation live
def test_dynamic_db_policy_matrix_updates_rules_calendar_and_tools() -> None:
    repo = MemoryRepository()
    repo.chunks = [
        PolicyChunk(
            chunk_id="leave-001-pengajuan",
            document_id="HR-LEAVE-001",
            title="Kebijakan Cuti Tahunan",
            section="Pengajuan",
            version="2.1",
            effective_date=date(2026, 1, 1),
            content="Pengajuan dilakukan paling lambat tiga hari kerja sebelum tanggal mulai.",
        ),
        PolicyChunk(
            chunk_id="leave-002-sakit",
            document_id="HR-LEAVE-002",
            title="Kebijakan Cuti Sakit",
            section="Pemberitahuan",
            version="1.4",
            effective_date=date(2026, 1, 1),
            content="Cuti sakit lebih dari dua hari kerja berturut-turut memerlukan dokumen pendukung.",
        ),
    ]
    _, retrieval, tools, _, client = _build_runtime(repo, reference_date=date(2026, 10, 26))
    auth = AuthContext(employee_id="EMP-001", display_name="Alya Pratama", role="employee")

    initial_rules = client.get("/api/v1/policies/rules", headers=AUTH_ALYA).json()
    assert initial_rules["annual_lead_days"] == 3
    assert initial_rules["earliest_annual_start_date"] == "2026-10-29"
    assert initial_rules["sick_doc_threshold"] == 2
    initial_fp = repo.policy_fingerprint(as_of=date(2026, 10, 26))

    # Update DB chunks dynamically to H-1 annual lead time and >1 day sick attachment threshold
    repo.chunks = [
        PolicyChunk(
            chunk_id="leave-001-pengajuan-v2",
            document_id="HR-LEAVE-001",
            title="Kebijakan Cuti Tahunan",
            section="Pengajuan",
            version="2.2",
            effective_date=date(2026, 1, 1),
            content="Pengajuan dilakukan minimal H-1 (satu hari kerja) sebelum tanggal mulai.",
        ),
        PolicyChunk(
            chunk_id="leave-002-sakit-v2",
            document_id="HR-LEAVE-002",
            title="Kebijakan Cuti Sakit",
            section="Pemberitahuan",
            version="1.5",
            effective_date=date(2026, 1, 1),
            content="Cuti sakit lebih dari satu hari kerja berturut-turut memerlukan dokumen pendukung.",
        ),
    ]
    assert repo.policy_fingerprint(as_of=date(2026, 10, 26)) != initial_fp
    assert "H-1" in retrieval.search("pengajuan cuti tahunan", top_k=1)[0].content

    updated_rules = client.get("/api/v1/policies/rules", headers=AUTH_ALYA).json()
    assert updated_rules["annual_lead_days"] == 1
    assert updated_rules["earliest_annual_start_date"] == "2026-10-27"
    assert updated_rules["sick_doc_threshold"] == 1

    cal, _ = tools.execute("get_calendar", {"days": 5}, auth)
    assert cal["annual_lead_days"] == 1
    assert cal["earliest_annual_leave_date"] == "2026-10-27"
    assert cal["sick_doc_threshold"] == 1
    tue_entry = next(d for d in cal["calendar"] if d["date"] == "2026-10-27")
    assert tue_entry["can_book_annual_leave"] is True

    _, annual_proposal = tools.execute(
        "prepare_leave_request",
        {
            "start_date": "2026-10-27",
            "end_date": "2026-10-27",
            "leave_type": "annual",
            "reason": "Keperluan keluarga",
        },
        auth,
    )
    assert annual_proposal is not None
    assert annual_proposal.business_days == 1

    _, sick_proposal = tools.execute(
        "prepare_leave_request",
        {
            "start_date": "2026-10-27",
            "end_date": "2026-10-28",
            "leave_type": "sick",
            "reason": "Istirahat",
        },
        auth,
    )
    assert sick_proposal is not None
    assert sick_proposal.business_days == 2
    assert sick_proposal.requires_attachment is True


# (c) Standard H-3 lead-time calculation (Mon 2026-10-26 -> Thu 2026-10-29 allowed, Wed 2026-10-28 blocked)
def test_standard_h3_lead_time_rule() -> None:
    monday = date(2026, 10, 26)
    wednesday = date(2026, 10, 28)
    thursday = date(2026, 10, 29)
    assert count_lead_business_days(monday, wednesday) == 2
    assert count_lead_business_days(monday, thursday) == 3
    assert compute_earliest_annual_leave_date(monday, 3) == thursday

    balances = repo_balances = MemoryRepository().get_balances("EMP-001")
    assert repo_balances
    with pytest.raises(DomainError, match="minimal tiga hari kerja"):
        validate_leave_request(
            PrepareLeaveArgs(start_date=wednesday, end_date=wednesday, leave_type="annual", reason=None),
            balances,
            False,
            monday,
            policy_text="Pengajuan dilakukan paling lambat tiga hari kerja sebelum tanggal mulai.",
        )

    days, _ = validate_leave_request(
        PrepareLeaveArgs(start_date=thursday, end_date=thursday, leave_type="annual", reason=None),
        balances,
        False,
        monday,
        policy_text="Pengajuan dilakukan paling lambat tiga hari kerja sebelum tanggal mulai.",
    )
    assert days == 1


# (d) Prose brackets do not false-abstain; fake citations do abstain; action_proposed preserves citations
def test_citation_brackets_and_action_proposed_citations(repository: MemoryRepository) -> None:
    auth = AuthContext(employee_id="EMP-001", display_name="Alya Pratama", role="employee")

    prose_provider = ScriptedProvider([
        ModelTurn(
            response_id="t1",
            tool_calls=[
                ModelToolCall(
                    call_id="c1",
                    name="search_hr_policy",
                    arguments={"query": "cuti tahunan", "top_k": 3},
                )
            ],
        ),
        ModelTurn(
            response_id="t2",
            text="[Penting] Pegawai memperoleh 12 hari cuti tahunan [HR-LEAVE-001]. [Catatan] Simpan bukti.",
        ),
    ])
    _, _, _, prose_agent, _ = _build_runtime(repository, provider=prose_provider)
    prose_resp = prose_agent.run(ChatRequest(message="Berapa jatah cuti tahunan?"), auth)
    assert prose_resp.outcome == Outcome.answered
    assert [c.document_id for c in prose_resp.citations] == ["HR-LEAVE-001"]

    fake_provider = ScriptedProvider([
        ModelTurn(
            response_id="t1",
            tool_calls=[
                ModelToolCall(
                    call_id="c1",
                    name="search_hr_policy",
                    arguments={"query": "cuti tahunan", "top_k": 3},
                )
            ],
        ),
        ModelTurn(
            response_id="t2",
            text="Aturan palsu [HR-FAKE-999].",
        ),
    ])
    _, _, _, fake_agent, _ = _build_runtime(repository, provider=fake_provider)
    fake_resp = fake_agent.run(ChatRequest(message="Berapa jatah cuti tahunan?"), auth)
    assert fake_resp.outcome == Outcome.abstained
    assert fake_resp.citations == []

    action_provider = ScriptedProvider([
        ModelTurn(
            response_id="t1",
            tool_calls=[
                ModelToolCall(
                    call_id="c1",
                    name="search_hr_policy",
                    arguments={"query": "cuti tahunan", "top_k": 3},
                ),
                ModelToolCall(
                    call_id="c2",
                    name="prepare_leave_request",
                    arguments={
                        "start_date": "2026-10-29",
                        "end_date": "2026-10-30",
                        "leave_type": "annual",
                        "reason": "Acara keluarga",
                    },
                ),
            ],
        ),
        ModelTurn(
            response_id="t2",
            text="Proposal cuti disiapkan sesuai [HR-LEAVE-001]. Silakan konfirmasi.",
        ),
    ])
    _, _, _, action_agent, _ = _build_runtime(
        repository, reference_date=date(2026, 10, 26), provider=action_provider
    )
    action_resp = action_agent.run(
        ChatRequest(message="Siapkan cuti tahunan 2026-10-29 sampai 2026-10-30"), auth
    )
    assert action_resp.outcome == Outcome.action_proposed
    assert action_resp.action_proposal is not None
    assert [c.document_id for c in action_resp.citations] == ["HR-LEAVE-001"]


# (e) Sick leave attachment enforcement before /confirm & privacy isolation from monitoring_admin
def test_sick_leave_attachment_required_before_confirm_and_admin_blocked() -> None:
    repo = MemoryRepository()
    _, _, tools, _, client = _build_runtime(repo, reference_date=date(2026, 10, 26))
    auth = AuthContext(employee_id="EMP-001", display_name="Alya Pratama", role="employee")

    _, proposal = tools.execute(
        "prepare_leave_request",
        {
            "start_date": "2026-10-27",
            "end_date": "2026-10-29",
            "leave_type": "sick",
            "reason": "Pemulihan",
        },
        auth,
    )
    assert proposal is not None
    assert proposal.requires_attachment is True

    confirm_before = client.post(
        f"/api/v1/action-proposals/{proposal.proposal_id}/confirm",
        headers=AUTH_ALYA,
        json={"idempotency_key": "sick-confirm-001"},
    )
    assert confirm_before.status_code == 409

    pdf_bytes = b"%PDF-1.4\n%surat dokter test\n"
    upload_resp = client.post(
        f"/api/v1/action-proposals/{proposal.proposal_id}/attachment",
        headers=AUTH_ALYA,
        json={
            "filename": "surat-dokter.pdf",
            "content_type": "application/pdf",
            "content_base64": base64.b64encode(pdf_bytes).decode("ascii"),
        },
    )
    assert upload_resp.status_code == 200
    assert upload_resp.json()["proposal_id"] == proposal.proposal_id

    confirm_after = client.post(
        f"/api/v1/action-proposals/{proposal.proposal_id}/confirm",
        headers=AUTH_ALYA,
        json={"idempotency_key": "sick-confirm-001"},
    )
    assert confirm_after.status_code == 200
    confirm_data = confirm_after.json()
    assert confirm_data["status"] == "pending_manager_review"

    admin_att = client.get(
        f"/api/v1/leave-requests/{confirm_data['request_id']}/attachment",
        headers=AUTH_ADMIN,
    )
    assert admin_att.status_code == 403

    owner_att = client.get(
        f"/api/v1/leave-requests/{confirm_data['request_id']}/attachment",
        headers=AUTH_ALYA,
    )
    assert owner_att.status_code == 200
    assert base64.b64decode(owner_att.json()["content_base64"]) == pdf_bytes


# (f) Auth boundaries & pending-only hard gate
def test_auth_boundaries_and_pending_only_review_lock() -> None:
    repo = MemoryRepository()
    _, _, _, _, client = _build_runtime(repo, reference_date=date(2026, 10, 26))

    assert client.get("/api/v1/policies/rules").status_code == 401
    assert client.get("/api/v1/evaluation/cases").status_code == 401

    personas_resp = client.get("/auth/personas")
    assert personas_resp.status_code == 200
    personas = personas_resp.json()
    assert len(personas) == 3
    for p in personas:
        assert "balances" not in p
        assert "demo_token" not in p

    demo_emp = client.post("/auth/demo-session", json={"employee_id": "EMP-001"})
    assert demo_emp.status_code == 200
    session_token = demo_emp.json()["access_token"]
    assert session_token.startswith("sess_")
    assert (
        client.get(
            "/api/v1/leave-balances/me",
            headers={"Authorization": f"Bearer {session_token}"},
        ).status_code
        == 200
    )

    demo_admin = client.post("/auth/demo-session", json={"employee_id": "ADM-001"})
    assert demo_admin.status_code == 403

    # Pending-only hard gate: /review cannot approve any leave request
    prop = ActionProposal(
        proposal_id="AP-GATE-1",
        leave_type="annual",
        start_date=date(2026, 10, 29),
        end_date=date(2026, 10, 30),
        business_days=2,
        validation_summary=["valid"],
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    repo.save_proposal("EMP-001", prop)
    confirmed = repo.confirm_proposal("EMP-001", "AP-GATE-1", "gate-key-0001", today=date(2026, 10, 26))

    admin_review = client.post(
        f"/api/v1/manager/leave-requests/{confirmed.request_id}/review",
        headers=AUTH_ADMIN,
        json={"decision": "approved", "review_note": "Attempt auto-approve"},
    )
    assert admin_review.status_code in (403, 404)
    emp_review = client.post(
        f"/api/v1/manager/leave-requests/{confirmed.request_id}/review",
        headers=AUTH_ALYA,
        json={"decision": "approved", "review_note": "Self-approve"},
    )
    assert emp_review.status_code in (403, 404)

    # Even a manager account cannot approve leave via the API (pending-only hard gate)
    mgr_repo = MemoryRepository(employees=[
        {
            "employee_id": "MGR-001",
            "username": "manager",
            "display_name": "Manager",
            "role": "manager",
            "department": "Engineering",
            "token": "token-mgr",
            "balances": {},
        }
    ])
    _, _, _, _, mgr_client = _build_runtime(mgr_repo, reference_date=date(2026, 10, 26))
    mgr_review = mgr_client.post(
        f"/api/v1/manager/leave-requests/{confirmed.request_id}/review",
        headers={"Authorization": "Bearer token-mgr"},
        json={"decision": "approved", "review_note": "Manager approve"},
    )
    assert mgr_review.status_code in (403, 404)
    assert repo.list_leave_requests("EMP-001")[0].status == "pending_manager_review"


# (g) Recursive redact_trace & offline baseline medical redaction
def test_recursive_redact_trace_and_offline_medical_redaction(monkeypatch) -> None:
    monkeypatch.setattr(security, "_CACHED_TERMS", None)
    monkeypatch.setattr(security, "_LAST_DB_ATTEMPT", time_block := 9999999999.0)
    assert time_block > 0

    offline_redacted = security.redact("Saya sakit diabetes dan darah tinggi")
    assert "diabetes" not in offline_redacted.casefold()
    assert "darah tinggi" not in offline_redacted.casefold()
    assert "[REDACTED_MEDICAL]" in offline_redacted

    legal_phrase = security.redact("Saya ingin mengajukan cuti sakit selama 2 hari")
    assert "cuti sakit" in legal_phrase.casefold()

    secret_samples = (
        "key=AIzaSyDummyGoogleKey1234567890 "
        "gh=ghp_DummyGitHubToken123456789012 "
        "jwt=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJFTVAtMDAxIn0.signatureToken123 "
        "dsn=postgresql://hr_app:secretpass@postgres:5432/hr_assistant"
    )
    redacted_secrets = security.redact(secret_samples)
    for leaked in ("AIzaSyDummy", "ghp_Dummy", "eyJhbGci", "secretpass"):
        assert leaked not in redacted_secrets

    proposal = ActionProposal(
        proposal_id="AP-REDACT-1",
        leave_type="sick",
        start_date=date(2026, 10, 27),
        end_date=date(2026, 10, 28),
        business_days=2,
        reason="Sakit diabetes dan darah tinggi, hubungi alya@example.com / 081234567890, secret-token_XYZ987",
        validation_summary=["valid"],
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    redacted_payload = redact_trace({"proposal": proposal, "items": [proposal]})
    dumped = json.dumps(redacted_payload)
    for sensitive in ("diabetes", "darah tinggi", "alya@example.com", "081234567890", "XYZ987"):
        assert sensitive not in dumped


# (h) Deferred create_hr_ticket: Outcome.escalated on clean turn, zero tickets on failed/abstained turn
def test_create_hr_ticket_escalated_and_zero_side_effects_on_abstain(repository: MemoryRepository) -> None:
    auth = AuthContext(employee_id="EMP-001", display_name="Alya Pratama", role="employee")

    clean_provider = ScriptedProvider([
        ModelTurn(
            response_id="t1",
            tool_calls=[
                ModelToolCall(
                    call_id="tc1",
                    name="create_hr_ticket",
                    arguments={
                        "category": "leave_exception",
                        "summary": "Mohon pengecualian carryover cuti tahunan",
                    },
                )
            ],
        ),
        ModelTurn(response_id="t2", text="Tiket eskalasi HR telah dibuat."),
    ])
    _, _, _, clean_agent, _ = _build_runtime(repository, provider=clean_provider)
    clean_resp = clean_agent.run(ChatRequest(message="Buat tiket pengecualian cuti"), auth)
    assert clean_resp.outcome == Outcome.escalated
    assert len(repository.list_tickets("EMP-001")) == 1

    # On a fresh repository, a ticket call followed by a bad citation or provider failure creates ZERO tickets
    fresh_repo = MemoryRepository()
    failing_provider = ScriptedProvider([
        ModelTurn(
            response_id="t1",
            tool_calls=[
                ModelToolCall(
                    call_id="tc1",
                    name="create_hr_ticket",
                    arguments={
                        "category": "policy_question",
                        "summary": "Pertanyaan eskalasi yang gagal di turn kedua",
                    },
                )
            ],
        ),
        TimeoutError("upstream timeout"),
    ])
    _, _, _, failing_agent, _ = _build_runtime(fresh_repo, provider=failing_provider)
    fail_resp = failing_agent.run(ChatRequest(message="Eskalasi pertanyaan"), auth)
    assert fail_resp.outcome == Outcome.abstained
    assert fresh_repo.list_tickets("EMP-001") == []


# Evaluator checks: API cases fetch, trace retrieval_recall@3, citation_validity, forbidden trace check, p95 & evaluated_at
def test_run_evaluation_uses_api_cases_and_trace_metrics(tmp_path: Path, monkeypatch) -> None:
    repo = MemoryRepository()
    repo.chunks = [
        PolicyChunk(
            chunk_id="chunk-annual",
            document_id="HR-LEAVE-001",
            title="Kebijakan Cuti Tahunan",
            section="Hak dan saldo",
            version="2.1",
            effective_date=date(2026, 1, 1),
            content="Pegawai tetap memperoleh 12 hari kerja cuti tahunan per tahun kalender.",
        )
    ]
    repo.evaluation_cases = [
        {
            "case_id": "policy-annual-001",
            "category": "policy",
            "input": "Berapa jatah cuti tahunan?",
            "expected_documents": ["HR-LEAVE-001"],
            "expected_tools": ["search_hr_policy"],
            "hard_gate": False,
        },
        {
            "case_id": "leave-valid-008",
            "category": "action",
            "input": "Siapkan cuti tahunan 2026-10-29 sampai 2026-10-30",
            "expected_documents": [],
            "expected_tools": ["prepare_leave_request"],
            "hard_gate": True,
        },
    ]

    provider = ScriptedProvider([
        # Case 1 turns
        ModelTurn(
            response_id="c1t1",
            tool_calls=[
                ModelToolCall(
                    call_id="c1-call",
                    name="search_hr_policy",
                    arguments={"query": "cuti tahunan", "top_k": 3},
                )
            ],
        ),
        ModelTurn(response_id="c1t2", text="Jatah cuti tahunan adalah 12 hari kerja [HR-LEAVE-001]."),
        # Case 2 turns
        ModelTurn(
            response_id="c2t1",
            tool_calls=[
                ModelToolCall(
                    call_id="c2-call",
                    name="prepare_leave_request",
                    arguments={
                        "start_date": "2026-10-29",
                        "end_date": "2026-10-30",
                        "leave_type": "annual",
                        "reason": "Liburan",
                    },
                )
            ],
        ),
        ModelTurn(response_id="c2t2", text="Proposal cuti telah disiapkan untuk konfirmasi."),
    ])
    _, _, _, _, test_client = _build_runtime(
        repo, reference_date=date(2026, 10, 26), provider=provider
    )

    class _TestClientWrapper:
        def __init__(self, *args, **kwargs):
            self._headers = kwargs.get("headers") or {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url: str):
            return test_client.get(url, headers=self._headers)

        def post(self, url: str, json=None):
            return test_client.post(url, headers=self._headers, json=json)

    monkeypatch.setattr(httpx, "Client", _TestClientWrapper)
    out_file = tmp_path / "eval_report.json"
    report = run_evaluation.run("http://testserver", "token-alya", cases_path=None, output_path=out_file)

    assert report["evaluated_at"]
    assert report["case_count"] == 2
    assert report["passed_count"] == 2
    assert report["hard_gates_passed"] is True
    assert report["retrieval_recall_at_3"] == 1.0
    assert report["citation_validity"] == 1.0
    assert report["release_decision"] == "release"
    assert report["results"][0]["retrieved_document_ids"] == ["HR-LEAVE-001"]
    assert report["latency_ms"]["p95"] == max(r["latency_ms"] for r in report["results"])

    # Verify forbidden fact caught in trace and empty cited_cases on policy cases yields citation_validity=0.0
    ok, failures = run_evaluation._case_passed(
        {
            "case_id": "medical-pii-012",
            "category": "privacy",
            "forbidden_facts": ["diabetes"],
            "hard_gate": True,
        },
        {"answer": "Aman.", "outcome": "answered", "citations": [], "tool_calls": []},
        trace_data={"error": "leaked diabetes", "retrieved_document_ids": []},
    )
    assert not ok
    assert any("trace" in f for f in failures)

    # Empty citations on a policy suite should produce citation_validity == 0.0 and block release
    repo_nocite = MemoryRepository()
    repo_nocite.evaluation_cases = [
        {
            "case_id": "policy-annual-001",
            "category": "policy",
            "input": "Berapa jatah cuti tahunan?",
            "expected_documents": ["HR-LEAVE-001"],
            "expected_tools": ["search_hr_policy"],
            "hard_gate": False,
        }
    ]
    provider_nocite = ScriptedProvider([
        ModelTurn(response_id="n1", text="Saya tidak punya sitasi."),
    ])
    _, _, _, _, nocite_client = _build_runtime(
        repo_nocite, reference_date=date(2026, 10, 26), provider=provider_nocite
    )

    class _NoCiteWrapper:
        def __init__(self, *args, **kwargs):
            self._headers = kwargs.get("headers") or {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url: str):
            return nocite_client.get(url, headers=self._headers)

        def post(self, url: str, json=None):
            return nocite_client.post(url, headers=self._headers, json=json)

    monkeypatch.setattr(httpx, "Client", _NoCiteWrapper)
    nocite_report = run_evaluation.run(
        "http://testserver", "token-alya", cases_path=None, output_path=tmp_path / "nocite.json"
    )
    assert nocite_report["citation_validity"] == 0.0
    assert nocite_report["retrieval_recall_at_3"] == 0.0
    assert nocite_report["release_decision"] == "block"


# Opik telemetry integrity, redaction, LLM turn preview, and FastAPI lifespan flush
def test_opik_trace_preserves_metadata_redacts_input_and_flushes_on_lifespan(
    repository: MemoryRepository,
    monkeypatch,
) -> None:
    import opik
    from src.opik_tracker import OpikTracker
    from src.security import stable_safety_id

    monkeypatch.setattr(security, "_CACHED_TERMS", None)
    monkeypatch.setattr(security, "_LAST_DB_ATTEMPT", 9999999999.0)
    monkeypatch.setenv("OPIK_API_KEY", "test-opik-key")
    monkeypatch.setenv("OPIK_WORKSPACE", "test-workspace")
    monkeypatch.setenv("OPIK_PROJECT_NAME", "test-project")

    class FakeOpikSpan:
        def __init__(self, **kwargs) -> None:
            self.init_kwargs = kwargs
            self.end_kwargs: dict | None = None

        def end(self, **kwargs) -> None:
            self.end_kwargs = kwargs

    class FakeOpikTrace:
        def __init__(self, **kwargs) -> None:
            self.init_kwargs = kwargs
            self.spans: list[FakeOpikSpan] = []
            self.end_kwargs: dict | None = None

        def span(self, **kwargs) -> FakeOpikSpan:
            span = FakeOpikSpan(**kwargs)
            self.spans.append(span)
            return span

        def end(self, **kwargs) -> None:
            self.end_kwargs = kwargs

    class FakeOpikClient:
        def __init__(self) -> None:
            self.traces: list[FakeOpikTrace] = []
            self.flush_calls = 0

        def trace(self, **kwargs) -> FakeOpikTrace:
            trace = FakeOpikTrace(**kwargs)
            self.traces.append(trace)
            return trace

        def flush(self) -> bool:
            self.flush_calls += 1
            return True

    fake_client = FakeOpikClient()
    flush_tracker_calls = 0

    def fake_flush_tracker() -> None:
        nonlocal flush_tracker_calls
        flush_tracker_calls += 1

    monkeypatch.setattr(opik, "Opik", lambda **kwargs: fake_client)
    monkeypatch.setattr(opik, "flush_tracker", fake_flush_tracker)

    from types import SimpleNamespace

    settings = Settings(
        _env_file=None,
        model_mode="live",
        environment="staging",
        agent_model="gpt-5-mini",
        embedding_model="text-embedding-3-small",
        openai_api_key="sk-testdummy12345678",
        opik_enabled=True,
        opik_api_key="test-opik-key",
        opik_workspace="test-workspace",
        opik_project_name="test-project",
        reference_date=date(2026, 10, 26),
    )
    provider = ScriptedProvider([
        ModelTurn(
            response_id="opik-t1",
            tool_calls=[
                ModelToolCall(
                    call_id="opik-tc1",
                    name="search_hr_policy",
                    arguments={"query": "cuti tahunan", "top_k": 2},
                )
            ],
            output_items=[
                SimpleNamespace(type="reasoning", summary=["hidden reasoning step"]),
                SimpleNamespace(
                    type="function_call",
                    call_id="opik-tc1",
                    name="search_hr_policy",
                    arguments='{"query": "cuti tahunan", "top_k": 2}',
                ),
            ],
            input_tokens=120,
            output_tokens=30,
        ),
        ModelTurn(
            response_id="opik-t2",
            text="Jatah cuti tahunan adalah 12 hari kerja [HR-LEAVE-001].",
            input_tokens=180,
            output_tokens=25,
        ),
    ])
    tracker = OpikTracker(settings)
    tracker_flush_calls = 0
    original_flush = tracker.flush

    def spy_flush() -> None:
        nonlocal tracker_flush_calls
        tracker_flush_calls += 1
        original_flush()

    monkeypatch.setattr(tracker, "flush", spy_flush)

    cache = NullCache()
    retrieval = RetrievalService(repository, provider, cache, 0)
    tools = ToolExecutor(
        repository,
        retrieval,
        settings,
        today_factory=lambda: date(2026, 10, 26),
    )
    agent = AgentService(repository, provider, tools, settings, tracker=tracker)
    app = create_app(settings=settings, repository=repository, cache=cache, agent=agent)

    with TestClient(app) as test_client:
        res = test_client.post(
            "/api/v1/chat",
            headers=AUTH_ALYA,
            json={"message": "Diagnosis: diabetes; token-secret_XYZ"},
        )
        assert res.status_code == 200
        payload = res.json()
        assert payload["outcome"] == "answered"

        # (c) Local DB trace still omits raw or redacted "message"
        local_trace = test_client.get(f"/api/v1/traces/{payload['trace_id']}", headers=AUTH_ALYA)
        assert local_trace.status_code == 200
        local_trace_json = local_trace.json()
        assert "message" not in local_trace_json
        assert "diabetes" not in json.dumps(local_trace_json).casefold()
        assert "secret_XYZ" not in json.dumps(local_trace_json)

    # (d) Exiting `with TestClient(app):` invokes lifespan shutdown -> agent.tracker.flush()
    assert tracker_flush_calls == 1
    assert fake_client.flush_calls >= 1
    assert flush_tracker_calls >= 1

    # (b) Opik trace input["message"] is present and PII/medical-redacted
    assert len(fake_client.traces) == 1
    opik_trace = fake_client.traces[0]
    trace_input = opik_trace.init_kwargs["input"]
    assert "message" in trace_input
    assert "[REDACTED_MEDICAL]" in trace_input["message"]
    assert "[REDACTED_TOKEN]" in trace_input["message"]
    assert "diabetes" not in trace_input["message"].casefold()
    assert "secret_XYZ" not in trace_input["message"]

    # (a) Base metadata survives root_trace.end() merged with outcome/citations/tokens
    assert opik_trace.end_kwargs is not None
    end_meta = opik_trace.end_kwargs["metadata"]
    assert end_meta["trace_id"] == payload["trace_id"]
    assert end_meta["role"] == "employee"
    assert end_meta["safety_identifier"] == stable_safety_id("EMP-001")
    assert end_meta["environment"] == "staging"
    assert end_meta["model"] == "gpt-5-mini"
    assert end_meta["outcome"] == "answered"
    assert end_meta["citations"] == ["HR-LEAVE-001"]

    # LLM spans include redacted latest_input preview without leaking reasoning/system prompt
    llm_spans = [s for s in opik_trace.spans if s.init_kwargs.get("type") == "llm"]
    assert len(llm_spans) == 2
    assert "[REDACTED_MEDICAL]" in llm_spans[0].init_kwargs["input"]["latest_input"]
    assert "[REDACTED_TOKEN]" in llm_spans[0].init_kwargs["input"]["latest_input"]
    assert "HR-LEAVE-001" in llm_spans[1].init_kwargs["input"]["latest_input"]
    assert "hidden reasoning step" not in llm_spans[1].init_kwargs["input"]["latest_input"]


def test_opik_llm_preview_extraction_and_non_blocking_debounced_flush(monkeypatch) -> None:
    import threading
    import time
    from types import SimpleNamespace
    import opik
    from src.opik_tracker import OpikTracker, _extract_latest_turn_preview

    # Preview extraction never returns system prompts or raw SDK reasoning items
    assert (
        _extract_latest_turn_preview([
            {"role": "system", "content": "CONFIDENTIAL SYSTEM PROMPT"},
            SimpleNamespace(type="reasoning", summary=["internal thought"]),
        ])
        == ""
    )

    long_msg = "A" * 450
    preview_user = _extract_latest_turn_preview([
        {"role": "system", "content": "SYSTEM"},
        {"role": "user", "content": long_msg},
        SimpleNamespace(type="reasoning", summary=["internal thought"]),
    ])
    assert preview_user == "A" * 300
    assert len(preview_user) == 300

    preview_tool = _extract_latest_turn_preview([
        {"role": "user", "content": "Pertanyaan awal"},
        {"type": "function_call", "call_id": "1", "name": "get_calendar", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "1", "output": "B" * 400},
        SimpleNamespace(type="reasoning", summary=["post-tool thought"]),
    ])
    assert preview_tool == "B" * 300
    assert len(preview_tool) == 300

    # Debounced flush runs in daemon thread without blocking LiveOpikTrace.end()
    monkeypatch.setenv("OPIK_API_KEY", "test-opik-key")
    monkeypatch.setenv("OPIK_WORKSPACE", "test-workspace")
    monkeypatch.setenv("OPIK_PROJECT_NAME", "test-project")
    flushed_event = threading.Event()

    class SlowFlushFakeClient:
        def __init__(self) -> None:
            self.flush_calls = 0

        def trace(self, **kwargs):
            return SimpleNamespace(
                span=lambda **skw: SimpleNamespace(end=lambda **ekw: None),
                end=lambda **ekw: None,
            )

        def flush(self) -> bool:
            time.sleep(0.05)
            self.flush_calls += 1
            flushed_event.set()
            return True

    fake_client = SlowFlushFakeClient()
    monkeypatch.setattr(opik, "Opik", lambda **kwargs: fake_client)
    monkeypatch.setattr(opik, "flush_tracker", lambda: None)

    settings = Settings(
        _env_file=None,
        model_mode="live",
        agent_model="gpt-5-mini",
        embedding_model="text-embedding-3-small",
        openai_api_key="sk-testdummy12345678",
        opik_enabled=True,
        opik_api_key="test-opik-key",
    )
    tracker = OpikTracker(settings)
    tracker._flush_delay_seconds = 0.02

    auth = AuthContext(employee_id="EMP-001", display_name="Alya Pratama", role="employee")
    trace = tracker.trace_turn("trace-debounce-1", "Cek saldo cuti", auth)
    started = time.monotonic()
    trace.end(output_data="Saldo cuti Anda 8 hari.", outcome="answered")
    elapsed = time.monotonic() - started

    assert elapsed < 0.04
    assert flushed_event.wait(timeout=2.0)
    assert fake_client.flush_calls == 1


def test_benchmark_domain_rejection_messages_are_explicit() -> None:
    repo = MemoryRepository()
    monday = date(2026, 10, 26)
    bima_balances = repo.get_balances("EMP-002")

    # Case 2: Bima (3 days) requests 5 workdays -> explicit requested vs available days & rejection
    with pytest.raises(DomainError) as insufficient_err:
        validate_leave_request(
            PrepareLeaveArgs(
                start_date=date(2026, 12, 7),
                end_date=date(2026, 12, 11),
                leave_type="annual",
                reason="Cuti keluarga",
            ),
            bima_balances,
            False,
            monday,
        )
    assert "diminta 5 hari kerja" in str(insufficient_err.value)
    assert "saldo tersedia hanya 3 hari kerja" in str(insufficient_err.value)
    assert "tidak cukup" in str(insufficient_err.value)

    # Case 4: Saturday-Sunday -> explicit 0 workdays rejection
    with pytest.raises(DomainError) as weekend_err:
        validate_leave_request(
            PrepareLeaveArgs(
                start_date=date(2026, 12, 12),
                end_date=date(2026, 12, 13),
                leave_type="annual",
                reason=None,
            ),
            repo.get_balances("EMP-001"),
            False,
            monday,
        )
    assert "0 hari kerja" in str(weekend_err.value)

    # Case 5: Inverted dates -> explicit no-auto-swap & fix inverted order message
    with pytest.raises(DomainError) as inverted_err:
        validate_leave_request(
            PrepareLeaveArgs(
                start_date=date(2026, 12, 8),
                end_date=date(2026, 12, 7),
                leave_type="annual",
                reason=None,
            ),
            repo.get_balances("EMP-001"),
            False,
            monday,
        )
    assert "sebelum tanggal mulai" in str(inverted_err.value)
    assert "urutan tanggal yang terbalik" in str(inverted_err.value)
    assert "tidak menukar tanggal" in str(inverted_err.value)


def test_opik_atomic_span_emission_and_trace_id_upsert(monkeypatch) -> None:
    from types import SimpleNamespace
    import opik
    from src.opik_tracker import OpikTracker

    monkeypatch.setattr(security, "_CACHED_TERMS", None)
    monkeypatch.setattr(security, "_LAST_DB_ATTEMPT", 9999999999.0)
    monkeypatch.setenv("OPIK_API_KEY", "test-opik-key")
    monkeypatch.setenv("OPIK_WORKSPACE", "test-workspace")
    monkeypatch.setenv("OPIK_PROJECT_NAME", "test-project")

    trace_calls: list[dict] = []
    span_calls: list[dict] = []

    class FakeOpikTraceWithId:
        def __init__(self, trace_id: str) -> None:
            self.id = trace_id

        def span(self, **kwargs):
            span_calls.append(kwargs)
            return SimpleNamespace()

        def end(self, **kwargs) -> None:
            raise AssertionError("Trace.end() should not be called when trace id is available")

    class FakeClientWithId:
        def trace(self, **kwargs):
            trace_calls.append(kwargs)
            return FakeOpikTraceWithId(kwargs.get("id") or "01900000-0000-7000-8000-000000000001")

        def flush(self) -> bool:
            return True

    fake_client = FakeClientWithId()
    monkeypatch.setattr(opik, "Opik", lambda **kwargs: fake_client)
    monkeypatch.setattr(opik, "flush_tracker", lambda: None)

    settings = Settings(
        _env_file=None,
        model_mode="live",
        agent_model="gpt-5-mini",
        embedding_model="text-embedding-3-small",
        openai_api_key="sk-testdummy12345678",
        opik_enabled=True,
        opik_api_key="test-opik-key",
    )
    tracker = OpikTracker(settings)
    tracker._flush_delay_seconds = 0.01

    auth = AuthContext(employee_id="EMP-001", display_name="Alya Pratama", role="employee")
    trace = tracker.trace_turn("trace-atomic-1", "Berapa saldo saya?", auth)
    with trace.span(
        name="llm:respond",
        span_type="llm",
        input_data=[{"role": "user", "content": "Berapa saldo saya?"}],
        metadata={"turn": 0, "role": "employee"},
    ) as llm_span:
        llm_span.set_output({"text": "Saldo Anda 8 hari.", "input_tokens": 50, "output_tokens": 12})

    # Atomic emission happens once upon span exit with full attributes (no 2-step update race)
    assert len(span_calls) == 1
    sp = span_calls[0]
    assert sp["name"] == "llm:respond"
    assert sp["type"] == "llm"
    assert sp["start_time"] <= sp["end_time"]
    assert sp["input"]["latest_input"] == "Berapa saldo saya?"
    assert sp["output"]["text"] == "Saldo Anda 8 hari."
    assert sp["usage"] == {"prompt_tokens": 50, "completion_tokens": 12, "total_tokens": 62}
    assert sp["model"] == "gpt-5-mini"
    assert sp["provider"] == "openai"

    trace.end(output_data="Saldo Anda 8 hari.", outcome="answered", citations=[])
    tracker.flush()

    assert len(trace_calls) == 2
    init_call, upsert_call = trace_calls
    assert "id" not in init_call
    assert upsert_call["id"] == "01900000-0000-7000-8000-000000000001"
    assert upsert_call["name"] == "HR Agent Turn"
    assert upsert_call["start_time"] <= upsert_call["end_time"]
    assert upsert_call["input"] == {"message": "Berapa saldo saya?", "history_length": 0}
    assert upsert_call["output"] == {"answer": "Saldo Anda 8 hari."}
    assert upsert_call["metadata"]["trace_id"] == "trace-atomic-1"
    assert upsert_call["metadata"]["outcome"] == "answered"
    assert upsert_call["tags"] == ["answered"]

