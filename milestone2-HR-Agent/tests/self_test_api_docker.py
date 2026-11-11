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
AUTH_MANAGER = {"Authorization": "Bearer token-manager"}
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
    assert "app2.py" in dockerfile
    assert "ui/" in dockerfile
    assert "public/" in dockerfile

    # .gitignore checks
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert "!outputs/evaluation_report.json" in gitignore

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

    # .env.example checks
    env_example_path = root / ".env.example"
    assert env_example_path.is_file()
    env_example_content = env_example_path.read_text(encoding="utf-8")
    assert "sk-" not in env_example_content
    assert "npg_" not in env_example_content


def test_evaluation_case_passed_rejects_blocked_action_tool() -> None:
    from src.run_evaluation import _case_passed

    case = {
        "case_id": "leave-valid-008",
        "category": "action",
        "input": "Siapkan cuti tahunan 2026-11-02 sampai 2026-11-03",
        "expected_documents": [],
        "expected_tools": ["prepare_leave_request"],
        "hard_gate": True,
    }

    # Skenario 1: tool berstatus blocked & outcome abstained -> harus gagal (passed is False)
    blocked_payload = {
        "outcome": "abstained",
        "answer": "Maaf, permintaan cuti tidak dapat diproses.",
        "citations": [],
        "tool_calls": [{"name": "prepare_leave_request", "status": "blocked", "duration_ms": 10}],
        "action_proposal": None,
    }
    passed_blocked, failures_blocked = _case_passed(case, blocked_payload)
    assert passed_blocked is False
    assert len(failures_blocked) > 0

    # Skenario 2: tool berstatus ok, outcome action_proposed, proposal requires_confirmation -> harus lulus (passed is True)
    ok_payload = {
        "outcome": "action_proposed",
        "answer": "Proposal cuti telah disiapkan.",
        "citations": [],
        "tool_calls": [{"name": "prepare_leave_request", "status": "ok", "duration_ms": 15}],
        "action_proposal": {
            "proposal_id": "AP-12345",
            "leave_type": "annual",
            "business_days": 2,
            "requires_confirmation": True,
        },
    }
    passed_ok, failures_ok = _case_passed(case, ok_payload)
    assert passed_ok is True
    assert failures_ok == []


# ==============================================================================
# WBS-23: RFC-7807 ProblemDetail Global Error Handler Verification
# ==============================================================================


def test_api_errors_return_rfc7807_problem_detail(api_client: TestClient) -> None:
    # 401 Unauthorized
    res_401 = api_client.post("/api/v1/chat", json={"message": "halo"})
    assert res_401.status_code == 401
    data_401 = res_401.json()
    assert data_401.get("type") == "about:blank"
    assert data_401.get("title") == "Unauthorized"
    assert data_401.get("status") == 401
    assert "detail" in data_401

    # 403 Forbidden
    res_403 = api_client.get("/api/v1/monitoring/summary", headers=AUTH_ALYA)
    assert res_403.status_code == 403
    data_403 = res_403.json()
    assert data_403.get("type") == "about:blank"
    assert data_403.get("title") == "Forbidden"
    assert data_403.get("status") == 403
    assert "detail" in data_403

    # 404 Not Found
    res_404 = api_client.get("/api/v1/traces/tr-unknown-12345", headers=AUTH_ALYA)
    assert res_404.status_code == 404
    data_404 = res_404.json()
    assert data_404.get("type") == "about:blank"
    assert data_404.get("title") == "Not found"
    assert data_404.get("status") == 404
    assert "detail" in data_404


# ==============================================================================
# WBS-25: Manager Leave Review & Lifecycle Verification
# ==============================================================================


def test_manager_leave_review_lifecycle_and_balance_deduction(api_client: TestClient) -> None:
    repo: MemoryRepository = api_client._repo  # type: ignore[attr-defined]

    # 1. Simpan proposal cuti annual 2 hari untuk Alya (EMP-001, saldo awal 8)
    prop_id = "AP-ALYA-LEAVE-01"
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

    # Konfirmasi menggunakan AUTH_ALYA -> status pending_manager_review
    res_conf = api_client.post(
        f"/api/v1/action-proposals/{prop_id}/confirm",
        headers=AUTH_ALYA,
        json={"idempotency_key": "idem-alya-leave-001"},
    )
    assert res_conf.status_code == 200
    assert res_conf.json()["status"] == "pending_manager_review"
    assert res_conf.json()["request_id"] == prop_id

    # Saldo efektif Alya menjadi 6 (8 - 2 hari pending)
    bal_alya = repo.get_balances("EMP-001")
    annual_bal = next(b for b in bal_alya if b.leave_type == "annual")
    assert annual_bal.available_days == 6

    # 2. Pegawai biasa (AUTH_BIMA) mencoba memanggil review -> ditolak dengan 403 Forbidden
    res_bima_unauth = api_client.post(
        f"/api/v1/manager/leave-requests/{prop_id}/review",
        headers=AUTH_BIMA,
        json={"decision": "approved", "review_note": "Reviewed by peer"},
    )
    assert res_bima_unauth.status_code == 403
    assert res_bima_unauth.json()["title"] == "Forbidden"

    # 3. Manager (token-manager) memanggil GET /api/v1/manager/leave-requests -> melihat request milik Alya
    res_team = api_client.get("/api/v1/manager/leave-requests", headers=AUTH_MANAGER)
    assert res_team.status_code == 200
    team_reqs = res_team.json()
    assert any(
        r["request_id"] == prop_id
        and r["employee_id"] == "EMP-001"
        and r["status"] == "pending_manager_review"
        for r in team_reqs
    )

    # 4. Manager menyetujui (decision: "approved") -> status berubah menjadi approved
    res_approve = api_client.post(
        f"/api/v1/manager/leave-requests/{prop_id}/review",
        headers=AUTH_MANAGER,
        json={"decision": "approved", "review_note": "Disetujui untuk cuti tahunan"},
    )
    assert res_approve.status_code == 200
    appr_data = res_approve.json()
    assert appr_data["status"] == "approved"
    assert appr_data["employee_id"] == "EMP-001"
    assert appr_data["reviewed_by"] == "MGR-001"
    assert "audit_reference" in appr_data

    # Saldo dasar Alya dipotong permanen dan saldo efektif tetap 6
    bal_alya_after = repo.get_balances("EMP-001")
    annual_after = next(b for b in bal_alya_after if b.leave_type == "annual")
    assert annual_after.available_days == 6

    # Percobaan review ulang menghasilkan 409 Conflict
    res_repeat = api_client.post(
        f"/api/v1/manager/leave-requests/{prop_id}/review",
        headers=AUTH_MANAGER,
        json={"decision": "approved", "review_note": "Review lagi"},
    )
    assert res_repeat.status_code == 409
    assert res_repeat.json()["title"] == "Conflict"

    # 5. Buat proposal kedua 2 hari untuk Bima (EMP-002, saldo awal 3)
    prop_bima = "AP-BIMA-LEAVE-01"
    repo.save_proposal(
        "EMP-002",
        ActionProposal(
            proposal_id=prop_bima,
            leave_type="annual",
            start_date=date(2026, 11, 9),
            end_date=date(2026, 11, 10),
            business_days=2,
            validation_summary=["valid"],
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        ),
    )
    res_conf_bima = api_client.post(
        f"/api/v1/action-proposals/{prop_bima}/confirm",
        headers=AUTH_BIMA,
        json={"idempotency_key": "idem-bima-leave-001"},
    )
    assert res_conf_bima.status_code == 200

    # Saldo efektif Bima menjadi 1 (3 - 2 reserved)
    bal_bima = repo.get_balances("EMP-002")
    annual_bima = next(b for b in bal_bima if b.leave_type == "annual")
    assert annual_bima.available_days == 1

    # Manager menolak (decision: "rejected")
    res_reject = api_client.post(
        f"/api/v1/manager/leave-requests/{prop_bima}/review",
        headers=AUTH_MANAGER,
        json={"decision": "rejected", "review_note": "Beban kerja sedang tinggi"},
    )
    assert res_reject.status_code == 200
    rej_data = res_reject.json()
    assert rej_data["status"] == "rejected"
    assert rej_data["employee_id"] == "EMP-002"

    # Kuota Bima pulih kembali menjadi 3!
    bal_bima_restored = repo.get_balances("EMP-002")
    annual_restored = next(b for b in bal_bima_restored if b.leave_type == "annual")
    assert annual_restored.available_days == 3

    # 6. Guardrail No Self-Approval: Manager membuat proposal untuk diri sendiri
    prop_mgr = "AP-MGR-LEAVE-01"
    repo.save_proposal(
        "MGR-001",
        ActionProposal(
            proposal_id=prop_mgr,
            leave_type="annual",
            start_date=date(2026, 12, 1),
            end_date=date(2026, 12, 2),
            business_days=2,
            validation_summary=["valid"],
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        ),
    )
    res_conf_mgr = api_client.post(
        f"/api/v1/action-proposals/{prop_mgr}/confirm",
        headers=AUTH_MANAGER,
        json={"idempotency_key": "idem-mgr-leave-001"},
    )
    assert res_conf_mgr.status_code == 200

    # Manager mencoba mereview cuti dirinya sendiri -> 409 Conflict
    res_self_review = api_client.post(
        f"/api/v1/manager/leave-requests/{prop_mgr}/review",
        headers=AUTH_MANAGER,
        json={"decision": "approved", "review_note": "Self approval attempt"},
    )
    assert res_self_review.status_code == 409
    assert res_self_review.json()["title"] == "Conflict"

    # Monitoring Admin dapat melihat seluruh cuti termasuk tim
    res_admin_team = api_client.get("/api/v1/manager/leave-requests", headers=AUTH_ADMIN)
    assert res_admin_team.status_code == 200
    assert len(res_admin_team.json()) >= 3


def test_postgres_repository_manager_review_lifecycle() -> None:
    import os
    if os.getenv("RUN_POSTGRES_TESTS") != "1":
        pytest.skip("Set RUN_POSTGRES_TESTS=1 for PostgreSQL integration tests.")

    from src.config import Settings
    from src.repository import PostgresRepository
    from src.setup_lab import reset_and_seed

    settings = Settings()
    reset_and_seed(reset=True)
    repo = PostgresRepository(settings.database_url, settings.embedding_dimensions)

    # Simpan proposal cuti untuk Alya
    prop_id = "AP-PG-ALYA-01"
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
    res_conf = repo.confirm_proposal("EMP-001", prop_id, "idem-pg-001")
    assert res_conf.status == "pending_manager_review"

    # Manager (MGR-001) melihat request tim
    team_reqs = repo.list_team_leave_requests("MGR-001")
    assert any(r.request_id == prop_id for r in team_reqs)

    # Manager menyetujui
    rev_res = repo.review_leave_request(
        reviewer_id="MGR-001",
        request_id=prop_id,
        decision="approved",
        review_note="Disetujui Postgres test",
    )
    assert rev_res.status == "approved"
    assert rev_res.employee_id == "EMP-001"

    # Saldo Alya terpotong dari 8 menjadi 6
    bal = next(b for b in repo.get_balances("EMP-001") if b.leave_type == "annual")
    assert bal.available_days == 6


def test_api_audio_transcribe_endpoint(api_client: TestClient) -> None:
    import base64

    # 1. Tanpa token -> 401
    res_no_auth = api_client.post(
        "/api/v1/audio/transcribe",
        json={"audio_base64": base64.b64encode(b"PROMPT:test audio").decode()},
    )
    assert res_no_auth.status_code == 401

    # 2. Base64 rusak -> 422
    res_corrupt_b64 = api_client.post(
        "/api/v1/audio/transcribe",
        headers=AUTH_ALYA,
        json={"audio_base64": "not-valid-base64-payload!!!"},
    )
    assert res_corrupt_b64.status_code == 422

    # 3. Audio size < 4 bytes -> 422
    too_short_b64 = base64.b64encode(b"ab").decode()
    res_short = api_client.post(
        "/api/v1/audio/transcribe",
        headers=AUTH_ALYA,
        json={"audio_base64": too_short_b64},
    )
    assert res_short.status_code == 422

    # 4. Payload base64 valid dengan AUTH_ALYA -> 200
    valid_payload = base64.b64encode(b"PROMPT:Berapa jatah cuti tahunan?").decode()
    res_valid = api_client.post(
        "/api/v1/audio/transcribe",
        headers=AUTH_ALYA,
        json={
            "audio_base64": valid_payload,
            "filename": "question.wav",
            "language": "id",
        },
    )
    assert res_valid.status_code == 200
    data = res_valid.json()
    assert data["text"] == "Berapa jatah cuti tahunan?"
    assert data["language"] == "id"
    assert "duration_ms" in data
    assert data["duration_ms"] >= 0

    # 5. Default fallback DeterministicProvider transcribe
    default_payload = base64.b64encode(b"RIFF\x24\x00\x00\x00WAVEfmt ").decode()
    res_default = api_client.post(
        "/api/v1/audio/transcribe",
        headers=AUTH_ALYA,
        json={"audio_base64": default_payload},
    )
    assert res_default.status_code == 200
    assert res_default.json()["text"] == "Berapa sisa saldo cuti tahunan saya?"


# ==============================================================================
# WBS-28: Sick Leave Medical Attachment Review & Authorization Isolation
# ==============================================================================


def test_sick_leave_attachment_upload_and_manager_review_isolation(api_client: TestClient) -> None:
    import base64
    repo: MemoryRepository = api_client._repo  # type: ignore[attr-defined]

    # 1. Buat dan konfirmasi proposal cuti sick (AP-SICK-01) dan cuti annual (AP-ANN-01) untuk Alya (EMP-001)
    repo.save_proposal(
        "EMP-001",
        ActionProposal(
            proposal_id="AP-SICK-01",
            leave_type="sick",
            start_date=date(2026, 11, 2),
            end_date=date(2026, 11, 4),
            business_days=3,
            validation_summary=["valid"],
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        ),
    )
    res_conf_sick = api_client.post(
        "/api/v1/action-proposals/AP-SICK-01/confirm",
        headers=AUTH_ALYA,
        json={"idempotency_key": "idem-sick-001"},
    )
    assert res_conf_sick.status_code == 200
    assert res_conf_sick.json()["status"] == "pending_manager_review"

    repo.save_proposal(
        "EMP-001",
        ActionProposal(
            proposal_id="AP-ANN-01",
            leave_type="annual",
            start_date=date(2026, 11, 10),
            end_date=date(2026, 11, 11),
            business_days=2,
            validation_summary=["valid"],
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        ),
    )
    res_conf_ann = api_client.post(
        "/api/v1/action-proposals/AP-ANN-01/confirm",
        headers=AUTH_ALYA,
        json={"idempotency_key": "idem-ann-001"},
    )
    assert res_conf_ann.status_code == 200
    assert res_conf_ann.json()["status"] == "pending_manager_review"

    # 2. Guardrail Jenis Cuti: Alya mencoba mengunggah PDF ke cuti annual (AP-ANN-01) -> ditolak 409 Conflict
    valid_pdf_bytes = b"%PDF-1.4 surat keterangan sakit dokter klinika"
    pdf_b64 = base64.b64encode(valid_pdf_bytes).decode("ascii")

    res_ann_upload = api_client.post(
        "/api/v1/leave-requests/AP-ANN-01/attachment",
        headers=AUTH_ALYA,
        json={
            "filename": "surat-dokter.pdf",
            "content_type": "application/pdf",
            "content_base64": pdf_b64,
        },
    )
    assert res_ann_upload.status_code == 409
    assert res_ann_upload.json()["title"] == "Conflict"

    # 3. Guardrail Magic Bytes & Size:
    # 3a. Plain text mengaku PDF -> 422
    fake_pdf_b64 = base64.b64encode(b"Teks biasa bukan dokumen PDF").decode("ascii")
    res_fake = api_client.post(
        "/api/v1/leave-requests/AP-SICK-01/attachment",
        headers=AUTH_ALYA,
        json={
            "filename": "fake.pdf",
            "content_type": "application/pdf",
            "content_base64": fake_pdf_b64,
        },
    )
    assert res_fake.status_code == 422

    # 3b. Data terlalu pendek (< 4 bytes) -> 422
    short_b64 = base64.b64encode(b"ab").decode("ascii")
    res_short = api_client.post(
        "/api/v1/leave-requests/AP-SICK-01/attachment",
        headers=AUTH_ALYA,
        json={
            "filename": "short.pdf",
            "content_type": "application/pdf",
            "content_base64": short_b64,
        },
    )
    assert res_short.status_code == 422

    # 3c. Plain text mengaku image/png -> 422
    res_fake_png = api_client.post(
        "/api/v1/leave-requests/AP-SICK-01/attachment",
        headers=AUTH_ALYA,
        json={
            "filename": "fake.png",
            "content_type": "image/png",
            "content_base64": fake_pdf_b64,
        },
    )
    assert res_fake_png.status_code == 422

    # 4. Upload Valid (PDF & PNG):
    # Alya mengunggah PDF valid ke AP-SICK-01 -> 200 OK
    res_upload_pdf = api_client.post(
        "/api/v1/leave-requests/AP-SICK-01/attachment",
        headers=AUTH_ALYA,
        json={
            "filename": "surat_dokter_resmi.pdf",
            "content_type": "application/pdf",
            "content_base64": pdf_b64,
        },
    )
    assert res_upload_pdf.status_code == 200
    up_data = res_upload_pdf.json()
    assert up_data["request_id"] == "AP-SICK-01"
    assert up_data["employee_id"] == "EMP-001"
    assert up_data["filename"] == "surat_dokter_resmi.pdf"
    assert up_data["content_type"] == "application/pdf"
    assert up_data["file_size_bytes"] == len(valid_pdf_bytes)

    # Verifikasi GET /api/v1/leave-requests/me menyertakan metadata lampiran
    res_my = api_client.get("/api/v1/leave-requests/me", headers=AUTH_ALYA)
    assert res_my.status_code == 200
    my_sick = next(r for r in res_my.json() if r["request_id"] == "AP-SICK-01")
    assert my_sick["has_attachment"] is True
    assert my_sick["attachment_filename"] == "surat_dokter_resmi.pdf"
    assert my_sick["attachment_content_type"] == "application/pdf"
    assert my_sick["attachment_size_bytes"] == len(valid_pdf_bytes)

    # Pemilik sendiri dapat mengunduh kembali lampiran
    res_own_get = api_client.get("/api/v1/leave-requests/AP-SICK-01/attachment", headers=AUTH_ALYA)
    assert res_own_get.status_code == 200
    assert res_own_get.json()["content_base64"] == pdf_b64

    # 5. Guardrail Isolasi Privasi Medis: Pegawai lain (AUTH_BIMA / EMP-002) mencoba mengakses -> 403 Forbidden
    res_bima_leak = api_client.get(
        "/api/v1/leave-requests/AP-SICK-01/attachment",
        headers=AUTH_BIMA,
    )
    assert res_bima_leak.status_code == 403
    assert res_bima_leak.json()["title"] == "Forbidden"

    # 6. Review oleh Manajer Tim:
    # Manajer Alya (token-manager / MGR-001) melihat request dengan has_attachment == True
    res_mgr_team = api_client.get("/api/v1/manager/leave-requests", headers=AUTH_MANAGER)
    assert res_mgr_team.status_code == 200
    mgr_sick = next(r for r in res_mgr_team.json() if r["request_id"] == "AP-SICK-01")
    assert mgr_sick["has_attachment"] is True
    assert mgr_sick["attachment_filename"] == "surat_dokter_resmi.pdf"

    # Manajer mengambil dokumen -> 200 OK, isi PDF sesuai
    res_mgr_doc = api_client.get("/api/v1/leave-requests/AP-SICK-01/attachment", headers=AUTH_MANAGER)
    assert res_mgr_doc.status_code == 200
    assert res_mgr_doc.json()["content_base64"] == pdf_b64

    # Monitoring Admin juga memiliki hak akses audit dokumen medis
    res_admin_doc = api_client.get("/api/v1/leave-requests/AP-SICK-01/attachment", headers=AUTH_ADMIN)
    assert res_admin_doc.status_code == 200
    assert res_admin_doc.json()["filename"] == "surat_dokter_resmi.pdf"

    # Manajer menyetujui cuti sakit tersebut
    res_approve = api_client.post(
        "/api/v1/manager/leave-requests/AP-SICK-01/review",
        headers=AUTH_MANAGER,
        json={"decision": "approved", "review_note": "Dokumen surat dokter sah dan terverifikasi"},
    )
    assert res_approve.status_code == 200
    assert res_approve.json()["status"] == "approved"

    # 7. Guardrail Immutability Pasca-Finalisasi:
    # Setelah berstatus approved, upload ulang lampiran ditolak dengan 409 Conflict
    res_reupload = api_client.post(
        "/api/v1/leave-requests/AP-SICK-01/attachment",
        headers=AUTH_ALYA,
        json={
            "filename": "surat-baru.pdf",
            "content_type": "application/pdf",
            "content_base64": pdf_b64,
        },
    )
    assert res_reupload.status_code == 409
    assert res_reupload.json()["title"] == "Conflict"



