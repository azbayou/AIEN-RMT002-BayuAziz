from __future__ import annotations

import base64
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path

from fastapi.testclient import TestClient
import httpx
import psycopg
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
from src.repository import MemoryRepository, PostgresRepository, redact_trace
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

    # Web SPA path: X-Enforce-Sick-Attachment: true blocks /confirm with 409 until attachment is uploaded
    confirm_before = client.post(
        f"/api/v1/action-proposals/{proposal.proposal_id}/confirm",
        headers={**AUTH_ALYA, "X-Enforce-Sick-Attachment": "true"},
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
        headers={**AUTH_ALYA, "X-Enforce-Sick-Attachment": "true"},
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

    # Starter Streamlit app.py path (no upload UI, no enforcement header): confirms cleanly to pending_manager_review
    _, starter_prop = tools.execute(
        "prepare_leave_request",
        {
            "start_date": "2026-11-04",
            "end_date": "2026-11-06",
            "leave_type": "sick",
            "reason": "Pemulihan lanjutan",
        },
        auth,
    )
    assert starter_prop is not None and starter_prop.requires_attachment is True
    starter_confirm = client.post(
        f"/api/v1/action-proposals/{starter_prop.proposal_id}/confirm",
        headers=AUTH_ALYA,
        json={"idempotency_key": "sick-starter-002"},
    )
    assert starter_confirm.status_code == 200
    assert starter_confirm.json()["status"] == "pending_manager_review"


# (f) Auth boundaries & pending-only hard gate
def test_auth_boundaries_and_pending_only_review_lock() -> None:
    repo = MemoryRepository()
    _, _, _, _, client = _build_runtime(repo, reference_date=date(2026, 10, 26))

    unauth_rules = client.get("/api/v1/policies/rules")
    assert unauth_rules.status_code == 401
    assert unauth_rules.headers.get("www-authenticate") == "Bearer"
    assert client.get("/api/v1/evaluation/cases").status_code == 401

    personas_resp = client.get("/auth/personas")
    assert personas_resp.status_code == 200
    personas = personas_resp.json()
    assert len(personas) == 3
    for p in personas:
        assert "balances" not in p
        assert "demo_token" not in p
        assert p["requires_password"] is True

    # Demo session bypass is disabled by default (prevents cross-employee impersonation)
    demo_emp = client.post("/auth/demo-session", json={"employee_id": "EMP-001"})
    assert demo_emp.status_code == 403
    demo_admin = client.post("/auth/demo-session", json={"employee_id": "ADM-001"})
    assert demo_admin.status_code == 403

    # Password login succeeds and binds token strictly to authenticated employee
    login_emp = client.post("/auth/login", json={"username": "alya", "password": "Password#123"})
    assert login_emp.status_code == 200
    session_token = login_emp.json()["access_token"]
    assert session_token.startswith("sess_")
    assert (
        client.get(
            "/api/v1/leave-balances/me",
            headers={"Authorization": f"Bearer {session_token}"},
        ).status_code
        == 200
    )

    # Manager endpoints do not exist and cannot approve leave requests
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

    assert client.get("/api/v1/manager/leave-requests", headers=AUTH_ADMIN).status_code == 404
    assert (
        client.post(
            f"/api/v1/manager/leave-requests/{confirmed.request_id}/review",
            headers=AUTH_ADMIN,
            json={"decision": "approved", "review_note": "Attempt auto-approve"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/manager/leave-requests/{confirmed.request_id}/review",
            headers=AUTH_ALYA,
            json={"decision": "approved", "review_note": "Self-approve"},
        ).status_code
        == 404
    )
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

    # (b) Opik trace input & LLM spans are strictly metadata-only (no prompt/answer/tool text)
    assert len(fake_client.traces) == 1
    opik_trace = fake_client.traces[0]
    trace_input = opik_trace.init_kwargs["input"]
    assert "message" not in trace_input
    assert trace_input["message_length"] == len("Diagnosis: diabetes; token-secret_XYZ")
    assert trace_input["role"] == "employee"
    assert trace_input["employee_hash"] == stable_safety_id("EMP-001")
    dumped_opik = json.dumps(
        {
            "trace_init": opik_trace.init_kwargs,
            "trace_end": opik_trace.end_kwargs,
            "spans": [{"init": s.init_kwargs, "end": s.end_kwargs} for s in opik_trace.spans],
        },
        default=str,
    )
    for forbidden_text in ("diabetes", "secret_XYZ", "hidden reasoning step", "Jatah cuti tahunan adalah"):
        assert forbidden_text not in dumped_opik

    # (a) Base metadata & tags survive root_trace.end() merged with outcome/citations/tokens
    assert opik_trace.end_kwargs is not None
    end_meta = opik_trace.end_kwargs["metadata"]
    assert end_meta["trace_id"] == payload["trace_id"]
    assert end_meta["role"] == "employee"
    assert end_meta["safety_identifier"] == stable_safety_id("EMP-001")
    assert end_meta["environment"] == "staging"
    assert end_meta["model"] == "gpt-5-mini"
    assert end_meta["outcome"] == "answered"
    assert end_meta["citations"] == ["HR-LEAVE-001"]
    assert opik_trace.end_kwargs["tags"] == ["employee", "staging", "answered"]

    # LLM spans contain only metadata counts & token usage, never latest_input or text
    llm_spans = [s for s in opik_trace.spans if s.init_kwargs.get("type") == "llm"]
    assert len(llm_spans) == 2
    assert "latest_input" not in llm_spans[0].init_kwargs["input"]
    assert llm_spans[0].init_kwargs["input"]["turn"] == 0
    assert llm_spans[0].init_kwargs["input"]["message_count"] == 1


def test_opik_llm_preview_extraction_and_non_blocking_debounced_flush(monkeypatch) -> None:
    import threading
    import time
    from types import SimpleNamespace
    import opik
    from src.opik_tracker import OpikTracker, _metadata_only_span_output

    llm_meta = _metadata_only_span_output(
        "llm",
        {"text": "Secret response", "tool_calls_count": 1, "input_tokens": 10, "output_tokens": 5},
        "ok",
    )
    assert llm_meta == {"tool_calls_count": 1, "input_tokens": 10, "output_tokens": 5}
    assert "text" not in llm_meta

    tool_meta = _metadata_only_span_output("tool", [{"content": "Confidential policy"}], "ok")
    assert tool_meta == {"status": "ok", "result_type": "list", "item_count": 1}

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

    # Atomic emission happens once upon span exit with strictly metadata-only payloads
    assert len(span_calls) == 1
    sp = span_calls[0]
    assert sp["name"] == "llm:respond"
    assert sp["type"] == "llm"
    assert sp["start_time"] <= sp["end_time"]
    assert "latest_input" not in sp["input"]
    assert sp["input"] == {"turn": 0, "role": "employee", "message_count": 1}
    assert sp["output"] == {"tool_calls_count": 0, "input_tokens": 50, "output_tokens": 12}
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
    assert "message" not in upsert_call["input"]
    assert upsert_call["input"]["message_length"] == len("Berapa saldo saya?")
    assert "answer" not in upsert_call["output"]
    assert upsert_call["output"]["outcome"] == "answered"
    assert upsert_call["output"]["answer_length"] == len("Saldo Anda 8 hari.")
    assert upsert_call["metadata"]["trace_id"] == "trace-atomic-1"
    assert upsert_call["metadata"]["outcome"] == "answered"
    assert upsert_call["tags"] == ["employee", "development", "answered"]


def test_monitoring_admin_analytics_are_strictly_anonymized() -> None:
    repo = MemoryRepository()
    _, _, tools, _, client = _build_runtime(repo, reference_date=date(2026, 10, 26))

    assert client.get("/api/v1/analytics/overview", headers=AUTH_ALYA).status_code == 403
    res = client.get("/api/v1/analytics/overview?low_balance_threshold=30", headers=AUTH_ADMIN)
    assert res.status_code == 200
    body = res.json()
    assert body["low_balance_employees"] == []
    assert body["low_balance_employee_count"] == 2
    serialized = json.dumps(body)
    for leaked in ("EMP-001", "EMP-002", "Alya Pratama", "Bima Santoso"):
        assert leaked not in serialized

    admin_auth = AuthContext(employee_id="ADM-001", display_name="Monitoring Admin", role="monitoring_admin")
    tool_res, _ = tools.execute(
        "get_team_hr_analytics",
        {"metric_focus": "balance_risks", "low_balance_threshold": 30},
        admin_auth,
    )
    assert tool_res["low_balance_employees"] == []
    assert tool_res["low_balance_employee_count"] == 2
    emp_auth = AuthContext(employee_id="EMP-001", display_name="Alya Pratama", role="employee")
    with pytest.raises(DomainError):
        tools.execute("get_team_hr_analytics", {"metric_focus": "overview", "low_balance_threshold": 3}, emp_auth)


def test_security_redaction_extended_patterns_and_attachment_filenames(monkeypatch) -> None:
    monkeypatch.setattr(security, "_CACHED_TERMS", None)
    monkeypatch.setattr(security, "_LAST_DB_ATTEMPT", 9999999999.0)

    sample = (
        "token=sess_abcdef1234567890abcdef api_key=mySecretKey123 "
        "redis=redis://user:redispass@redis:6379/0 phone=021-5551234 "
        "intl=+1-415-555-2671 cond=pneumonia and cancer at rumah sakit"
    )
    cleaned = security.redact(sample)
    for sensitive in ("sess_abcdef", "mySecretKey123", "redispass", "021-5551234", "+1-415-555-2671", "pneumonia", "cancer"):
        assert sensitive.casefold() not in cleaned.casefold()
    assert "rumah sakit" in cleaned.casefold()
    assert "surat keterangan sakit" in security.redact("Bawa surat keterangan sakit").casefold()

    repo = MemoryRepository()
    _, _, tools, _, client = _build_runtime(repo, reference_date=date(2026, 10, 26))
    auth = AuthContext(employee_id="EMP-001", display_name="Alya Pratama", role="employee")
    _, prop = tools.execute(
        "prepare_leave_request",
        {
            "start_date": "2026-10-27",
            "end_date": "2026-10-28",
            "leave_type": "sick",
            "reason": "Sakit pneumonia hubungi alya@example.com",
        },
        auth,
    )
    assert prop is not None
    assert "pneumonia" not in (prop.reason or "").casefold()
    assert "alya@example.com" not in (prop.reason or "")

    att_res = client.post(
        f"/api/v1/action-proposals/{prop.proposal_id}/attachment",
        headers=AUTH_ALYA,
        json={
            "filename": "diabetes_081234567890.pdf",
            "content_type": "application/pdf",
            "content_base64": base64.b64encode(b"%PDF-1.4\n%test\n").decode("ascii"),
        },
    )
    assert att_res.status_code == 200
    assert "diabetes" not in att_res.json()["filename"].casefold()
    assert "081234567890" not in att_res.json()["filename"]


def test_monitoring_alerts_operators_and_memory_p95_percentile() -> None:
    repo = MemoryRepository()
    for idx, latency in enumerate((100.0, 200.0, 300.0, 400.0, 9500.0)):
        repo.save_trace({
            "trace_id": f"trace-p95-{idx}",
            "employee_id": "EMP-001",
            "outcome": "answered",
            "error": None,
            "blocked_reason": None,
            "retrieved_document_ids": [],
            "citation_ids": [],
            "tool_calls": [],
            "usage": {"input_tokens": 10, "output_tokens": 5, "latency_ms": latency},
        })
    summary = repo.monitoring_summary()
    assert summary["p95_latency_ms"] == 9500.0

    repo.monitoring_rules.append({
        "rule_id": "min-tool-calls",
        "metric": "tool_calls",
        "operator": "lt",
        "threshold": 1.0,
        "minimum_samples": 5,
        "owner": "AI Platform",
        "response": "Verify tool usage.",
    })
    _, _, _, _, client = _build_runtime(repo, reference_date=date(2026, 10, 26))
    alerts_res = client.get("/api/v1/monitoring/alerts", headers=AUTH_ADMIN)
    assert alerts_res.status_code == 200
    alert_ids = {a["rule_id"] for a in alerts_res.json()}
    assert "agent-latency-p95" in alert_ids
    assert "min-tool-calls" in alert_ids
    assert "agent-error-spike" not in alert_ids


def test_resilient_cache_degrades_gracefully_when_redis_fails() -> None:
    from redis.exceptions import RedisError
    from src.cache import ResilientCache

    class BrokenRedisClient:
        def ping(self) -> bool:
            raise RedisError("connection refused")

        def get(self, key: str):
            raise RedisError("read timeout")

        def setex(self, key: str, ttl: int, value: str) -> None:
            raise RedisError("write timeout")

    cache = ResilientCache("redis://localhost:6379/0")
    cache.client = BrokenRedisClient()
    assert cache.health() is False
    assert cache.get("retrieval:key") is None
    cache.set("retrieval:key", {"ok": True}, 60)  # must not raise


def test_retrieval_respects_as_of_effective_date_and_latest_version() -> None:
    repo = MemoryRepository()
    repo.chunks = [
        PolicyChunk(
            chunk_id="c-v1",
            document_id="HR-LEAVE-001",
            title="Kebijakan Cuti Tahunan",
            section="Hak",
            version="1.0",
            effective_date=date(2026, 1, 1),
            content="Versi lama 12 hari cuti tahunan.",
        ),
        PolicyChunk(
            chunk_id="c-v2",
            document_id="HR-LEAVE-001",
            title="Kebijakan Cuti Tahunan",
            section="Hak",
            version="2.0",
            effective_date=date(2026, 6, 1),
            content="Versi aktif 14 hari cuti tahunan.",
        ),
        PolicyChunk(
            chunk_id="c-v3-future",
            document_id="HR-LEAVE-001",
            title="Kebijakan Cuti Tahunan",
            section="Hak",
            version="3.0",
            effective_date=date(2027, 1, 1),
            content="Versi masa depan 20 hari cuti tahunan.",
        ),
    ]
    retrieval = RetrievalService(repo, DeterministicProvider(), NullCache(), 0)
    results_2026 = retrieval.search("cuti tahunan", top_k=3, as_of=date(2026, 10, 26))
    assert [c.chunk_id for c in results_2026] == ["c-v2"]
    results_early = retrieval.search("cuti tahunan", top_k=3, as_of=date(2026, 3, 1))
    assert [c.chunk_id for c in results_early] == ["c-v1"]


def test_repository_overlap_blocks_active_requests_and_allows_cancelled() -> None:
    repo = MemoryRepository()
    auth = AuthContext(employee_id="EMP-001", display_name="Alya Pratama", role="employee")
    _, _, tools, _, _ = _build_runtime(repo, reference_date=date(2026, 10, 26))

    # Pending request overlaps -> tool & confirm must reject
    _, p1 = tools.execute(
        "prepare_leave_request",
        {
            "start_date": "2026-11-02",
            "end_date": "2026-11-03",
            "leave_type": "annual",
            "reason": "Cuti pertama",
        },
        auth,
    )
    assert p1 is not None
    repo.confirm_proposal("EMP-001", p1.proposal_id, "overlap-key-001", today=date(2026, 10, 26))
    assert repo.has_overlap("EMP-001", date(2026, 11, 3), date(2026, 11, 4)) is True

    with pytest.raises(DomainError, match="bertumpang tindih"):
        tools.execute(
            "prepare_leave_request",
            {
                "start_date": "2026-11-03",
                "end_date": "2026-11-04",
                "leave_type": "annual",
                "reason": "Overlap",
            },
            auth,
        )

    # Cancelled/rejected request on another range must NOT block new requests
    cancelled_req = repo.list_leave_requests("EMP-001")[0].model_copy(
        update={
            "request_id": "LR-CANCEL-1",
            "start_date": date(2026, 12, 1),
            "end_date": date(2026, 12, 2),
            "status": "cancelled",
        }
    )
    repo.requests["EMP-001"].append(cancelled_req)
    assert repo.has_overlap("EMP-001", date(2026, 12, 1), date(2026, 12, 2)) is False


def test_policy_miss_followed_by_ticket_returns_escalated_and_persists_ticket(
    repository: MemoryRepository,
) -> None:
    auth = AuthContext(employee_id="EMP-001", display_name="Alya Pratama", role="employee")
    provider = ScriptedProvider([
        ModelTurn(
            response_id="esc-t1",
            tool_calls=[
                ModelToolCall(
                    call_id="c-search",
                    name="search_hr_policy",
                    arguments={"query": "pengecualian khusus", "top_k": 3},
                ),
                ModelToolCall(
                    call_id="c-ticket",
                    name="create_hr_ticket",
                    arguments={"category": "leave_exception", "summary": "Mohon pengecualian kebijakan"},
                ),
            ],
        ),
        ModelTurn(
            response_id="esc-t2",
            text="Permintaan pengecualian Anda telah dieskalasikan ke tim HR.",
        ),
    ])
    _, _, _, agent, _ = _build_runtime(repository, provider=provider)
    resp = agent.run(ChatRequest(message="Tolong eskalasikan pengecualian cuti"), auth)
    assert resp.outcome == Outcome.escalated
    assert len(repository.list_tickets("EMP-001")) == 1


def test_save_trace_failure_degrades_safely_and_deferred_proposals_do_not_orphan() -> None:
    repo = MemoryRepository()
    auth = AuthContext(employee_id="EMP-001", display_name="Alya Pratama", role="employee")

    # 1. Fake citation after prepare_leave_request -> abstained & zero orphaned proposals saved
    fake_cit_provider = ScriptedProvider([
        ModelTurn(
            response_id="o1",
            tool_calls=[
                ModelToolCall(
                    call_id="p1",
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
        ModelTurn(response_id="o2", text="Cuti disiapkan berdasarkan [POLICY-999]."),
    ])
    _, _, _, agent1, _ = _build_runtime(repo, provider=fake_cit_provider)
    resp1 = agent1.run(ChatRequest(message="Ajukan cuti 2026-10-29 sampai 2026-10-30"), auth)
    assert resp1.outcome == Outcome.abstained
    assert repo.proposals == {}

    # 2. save_trace raising DB outage degrades to HTTP 200 abstained (not 500) & creates zero tickets
    def broken_save_trace(trace):
        raise RuntimeError("database write failed")

    repo2 = MemoryRepository()
    repo2.save_trace = broken_save_trace
    ok_provider = ScriptedProvider([
        ModelTurn(
            response_id="st1",
            tool_calls=[
                ModelToolCall(
                    call_id="tc1",
                    name="create_hr_ticket",
                    arguments={"category": "policy_question", "summary": "Pertanyaan eskalasi"},
                )
            ],
        ),
        ModelTurn(response_id="st2", text="Tiket dibuat."),
    ])
    _, _, _, _, client2 = _build_runtime(repo2, provider=ok_provider)
    res2 = client2.post("/api/v1/chat", headers=AUTH_ALYA, json={"message": "Buat tiket HR"})
    assert res2.status_code == 200
    assert res2.json()["outcome"] == "abstained"
    assert repo2.tickets == {}


def test_agent_last_turn_guard_approval_claim_block_and_multidoc_citations() -> None:
    repo = MemoryRepository()
    auth = AuthContext(employee_id="EMP-001", display_name="Alya Pratama", role="employee")

    # Final turn tool call must NOT execute mutating prepare_leave_request
    turns = [
        ModelTurn(
            response_id=f"lt-{i}",
            tool_calls=[
                ModelToolCall(
                    call_id=f"c-{i}",
                    name="prepare_leave_request",
                    arguments={
                        "start_date": "2026-10-29",
                        "end_date": "2026-10-30",
                        "leave_type": "annual",
                        "reason": "Uji batas turn",
                    },
                )
            ],
        )
        for i in range(4)
    ]
    _, _, _, agent_lt, _ = _build_runtime(repo, provider=ScriptedProvider(turns))
    resp_lt = agent_lt.run(ChatRequest(message="Ajukan cuti"), auth)
    assert resp_lt.outcome == Outcome.abstained
    assert len(resp_lt.tool_calls) == 3  # 4th turn blocked before execution
    assert repo.proposals == {}

    # Un-negated positive approval claim forces abstention
    repo2 = MemoryRepository()
    repo2.chunks = [
        PolicyChunk(
            chunk_id="c-ap-1",
            document_id="HR-LEAVE-001",
            title="Kebijakan Cuti Tahunan",
            section="Hak",
            version="2.1",
            effective_date=date(2026, 1, 1),
            content="Cuti tahunan membutuhkan konfirmasi dan tinjauan manajer.",
        )
    ]
    approve_provider = ScriptedProvider([
        ModelTurn(
            response_id="ap1",
            tool_calls=[
                ModelToolCall(
                    call_id="ap-s",
                    name="search_hr_policy",
                    arguments={"query": "cuti tahunan", "top_k": 3},
                )
            ],
        ),
        ModelTurn(response_id="ap2", text="Cuti Anda sudah disetujui otomatis [HR-LEAVE-001]."),
    ])
    _, _, _, agent_ap, _ = _build_runtime(repo2, provider=approve_provider)
    resp_ap = agent_ap.run(ChatRequest(message="Setujui cuti saya"), auth)
    assert resp_ap.outcome == Outcome.abstained
    assert resp_ap.citations == []

    # Comma-separated multi-citation list [HR-LEAVE-001, HR-LEAVE-002] resolves both citations
    repo3 = MemoryRepository()
    repo3.chunks = [
        PolicyChunk(
            chunk_id="c-mc-1",
            document_id="HR-LEAVE-001",
            title="Kebijakan Cuti Tahunan",
            section="Hak",
            version="2.1",
            effective_date=date(2026, 1, 1),
            content="Jatah cuti tahunan adalah 12 hari kerja.",
        ),
        PolicyChunk(
            chunk_id="c-mc-2",
            document_id="HR-LEAVE-002",
            title="Kebijakan Cuti Sakit",
            section="Surat Dokter",
            version="1.4",
            effective_date=date(2026, 1, 1),
            content="Cuti sakit lebih dari dua hari memerlukan surat dokter.",
        ),
    ]
    multi_provider = ScriptedProvider([
        ModelTurn(
            response_id="mc1",
            tool_calls=[
                ModelToolCall(
                    call_id="mc-s",
                    name="search_hr_policy",
                    arguments={"query": "cuti tahunan sakit", "top_k": 5},
                )
            ],
        ),
        ModelTurn(response_id="mc2", text="Lihat aturan cuti [HR-LEAVE-001, HR-LEAVE-002]."),
    ])
    _, _, _, agent_mc, _ = _build_runtime(repo3, provider=multi_provider)
    resp_mc = agent_mc.run(ChatRequest(message="Jelaskan cuti tahunan dan sakit"), auth)
    assert resp_mc.outcome == Outcome.answered
    assert {c.document_id for c in resp_mc.citations} == {"HR-LEAVE-001", "HR-LEAVE-002"}


def test_run_evaluation_fifth_gate_and_http_error_denominators(tmp_path: Path, monkeypatch) -> None:
    repo = MemoryRepository()
    repo.evaluation_cases = [
        {
            "case_id": "policy-annual-001",
            "category": "policy",
            "input": "Berapa jatah cuti tahunan?",
            "expected_documents": ["HR-LEAVE-001"],
            "expected_tools": ["search_hr_policy"],
            "hard_gate": False,
        }
    ]
    _, _, _, _, test_client = _build_runtime(repo, reference_date=date(2026, 10, 26))

    # Case 1: HTTP timeout keeps case in Recall@3 / Tool Accuracy / latency denominators
    class _TimeoutClient:
        def __init__(self, *args, **kwargs):
            self._headers = kwargs.get("headers") or {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url: str):
            return test_client.get(url, headers=self._headers)

        def post(self, url: str, json=None):
            raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(httpx, "Client", _TimeoutClient)
    timeout_report = run_evaluation.run(
        "http://testserver", "token-alya", cases_path=None, output_path=tmp_path / "timeout.json"
    )
    assert timeout_report["retrieval_recall_at_3"] == 0.0
    assert timeout_report["citation_validity"] == 0.0
    assert timeout_report["tool_selection_accuracy"] == 0.0
    assert timeout_report["latency_ms"]["p95"] is not None
    assert timeout_report["release_decision"] == "block"

    # Case 2: System creating an approved leave request fails 5th release gate
    ok_provider = ScriptedProvider([
        ModelTurn(
            response_id="g5-1",
            tool_calls=[
                ModelToolCall(
                    call_id="g5-c",
                    name="search_hr_policy",
                    arguments={"query": "cuti tahunan", "top_k": 3},
                )
            ],
        ),
        ModelTurn(response_id="g5-2", text="Jatah cuti tahunan 12 hari kerja [HR-LEAVE-001]."),
    ])
    repo2 = MemoryRepository()
    repo2.chunks = [
        PolicyChunk(
            chunk_id="c-g5-1",
            document_id="HR-LEAVE-001",
            title="Kebijakan Cuti Tahunan",
            section="Hak",
            version="2.1",
            effective_date=date(2026, 1, 1),
            content="Pegawai tetap memperoleh 12 hari kerja cuti tahunan.",
        )
    ]
    repo2.evaluation_cases = repo.evaluation_cases
    _, _, _, _, ok_client = _build_runtime(repo2, reference_date=date(2026, 10, 26), provider=ok_provider)

    class _ApprovedLeakClient:
        def __init__(self, *args, **kwargs):
            self._headers = kwargs.get("headers") or {}
            self._calls = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url: str):
            if url == "/api/v1/leave-requests/me":
                self._calls += 1
                if self._calls > 1:
                    return httpx.Response(
                        200,
                        json=[{"request_id": "LR-BAD", "status": "approved"}],
                    )
            return ok_client.get(url, headers=self._headers)

        def post(self, url: str, json=None):
            return ok_client.post(url, headers=self._headers, json=json)

    monkeypatch.setattr(httpx, "Client", _ApprovedLeakClient)
    leak_report = run_evaluation.run(
        "http://testserver", "token-alya", cases_path=None, output_path=tmp_path / "leak.json"
    )
    assert leak_report["no_system_approved_requests"] is False
    assert leak_report["release_decision"] == "block"


def test_static_files_do_not_expose_vercel_json_or_405_unknown_post() -> None:
    repo = MemoryRepository()
    _, _, _, _, client = _build_runtime(repo, reference_date=date(2026, 10, 26))
    assert client.get("/").status_code == 200
    assert client.get("/vercel.json").status_code == 404
    assert client.post("/api/v1/nonexistent").status_code == 404
    assert client.post("/nonexistent").status_code == 404


def test_cors_preflight_allows_vercel_frontend_and_blocks_unknown_origin() -> None:
    repo = MemoryRepository()
    settings = Settings(
        _env_file=None,
        model_mode="fake",
        opik_enabled=False,
        environment="production",
        allow_demo_session=False,
        reference_date=date(2026, 10, 26),
    )
    provider = DeterministicProvider()
    cache = NullCache()
    retrieval = RetrievalService(repo, provider, cache, 0)
    tools = ToolExecutor(repo, retrieval, settings, today_factory=lambda: date(2026, 10, 26))
    agent = AgentService(repo, provider, tools, settings)
    client = TestClient(create_app(settings=settings, repository=repo, cache=cache, agent=agent))

    for path in ("/auth/login", "/api/v1/chat"):
        ok_resp = client.options(
            path,
            headers={
                "Origin": "https://miyo-hr-web.vercel.app",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,authorization",
            },
        )
        assert ok_resp.status_code == 200
        assert ok_resp.headers.get("access-control-allow-origin") == "https://miyo-hr-web.vercel.app"

    gh_resp = client.options(
        "/auth/login",
        headers={
            "Origin": "https://azbayou.github.io",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,authorization",
        },
    )
    assert gh_resp.status_code == 200
    assert gh_resp.headers.get("access-control-allow-origin") == "https://azbayou.github.io"

    evil_resp = client.options(
        "/auth/login",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,authorization",
        },
    )
    assert evil_resp.status_code == 400

    personas_resp = client.get(
        "/auth/personas",
        headers={"Origin": "https://miyo-hr-web.vercel.app"},
    )
    assert personas_resp.status_code == 200
    assert personas_resp.headers.get("access-control-allow-origin") == "https://miyo-hr-web.vercel.app"
    personas = personas_resp.json()
    assert len(personas) == 3
    assert all(p["requires_password"] is True for p in personas)


def test_postgres_list_personas_retries_transient_operational_error() -> None:
    rows = [
        {
            "employee_id": "ADM-001",
            "username": "admin",
            "display_name": "Monitoring Admin",
            "role": "monitoring_admin",
            "department": "HR & People Ops",
        },
        {
            "employee_id": "EMP-001",
            "username": "alya",
            "display_name": "Alya Pratama",
            "role": "employee",
            "department": "Engineering",
        },
        {
            "employee_id": "EMP-002",
            "username": "bima",
            "display_name": "Bima Santoso",
            "role": "employee",
            "department": "Engineering",
        },
    ]

    class _FakeCursor:
        def fetchall(self):
            return rows

    class _FakeConn:
        def __init__(self, should_fail: bool) -> None:
            self._should_fail = should_fail

        def __enter__(self):
            if self._should_fail:
                raise psycopg.OperationalError("connection closed during NeonDB cold start")
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql: str):
            return _FakeCursor()

    class _FakePool:
        def __init__(self) -> None:
            self.calls = 0

        def connection(self):
            self.calls += 1
            return _FakeConn(should_fail=(self.calls == 1))

    pg_repo = PostgresRepository.__new__(PostgresRepository)
    pg_repo.pool = _FakePool()

    personas = pg_repo.list_personas(allow_demo_session=False)
    assert pg_repo.pool.calls == 2
    assert len(personas) == 3
    assert [p["employee_id"] for p in personas] == ["ADM-001", "EMP-001", "EMP-002"]
    assert all(p["requires_password"] is True for p in personas)



