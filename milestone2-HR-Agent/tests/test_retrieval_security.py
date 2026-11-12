from __future__ import annotations

from src.cache import NullCache
from src.providers import DeterministicProvider
from src.repository import MemoryRepository
from src.retrieval import RetrievalService
from src.security import redact


def test_hybrid_retrieval_prefers_lexical_match(repository: MemoryRepository) -> None:
    service = RetrievalService(repository, DeterministicProvider(), NullCache(), 0)
    results = service.search("jatah cuti tahunan", top_k=2)
    assert results[0].document_id == "HR-LEAVE-001"


def test_redaction_covers_sensitive_patterns() -> None:
    value = redact(
        "Hubungi alya@example.com atau 081234567890; token-secret_ABCDEF123; diagnosis: diabetes."
    )
    assert "alya@example.com" not in value
    assert "081234567890" not in value
    assert "ABCDEF123" not in value
    assert "diabetes" not in value


def test_redaction_handles_multiline_values_and_is_idempotent() -> None:
    value = redact(
        "Error kontak: user@example.com\n"
        "Telepon +62 812-3456-7890\n"
        "Bearer secret-ABC123\n"
        "diagnosis: hipertensi."
    )
    assert "user@example.com" not in value
    assert "+62 812-3456-7890" not in value
    assert "secret-ABC123" not in value
    assert "hipertensi" not in value
    assert redact(value) == value


def test_redaction_preserves_leave_policy_term() -> None:
    value = redact("Pegawai mengajukan cuti sakit karena demam.")
    assert "cuti sakit" in value
    assert "demam" not in value


def test_redaction_preserves_various_hr_sick_leave_formats() -> None:
    # 1. Cuti Sakit berawalan resmi
    val1 = redact("• Cuti Sakit: 8 hari kerja")
    assert "Cuti Sakit: 8 hari kerja" in val1
    assert "[REDACTED_MEDICAL]" not in val1

    # 2. Format ringkas saldo 'Sakit: X hari kerja'
    val2 = redact("Per 10 November 2026, saldo cuti Anda:\n• Tahunan: 6 hari kerja\n• Sakit: 8 hari kerja\n• Orang tua: 60 hari kerja")
    assert "Sakit: 8 hari kerja" in val2
    assert "[REDACTED_MEDICAL]" not in val2

    # 3. Istilah administratif lain (izin sakit, saldo sakit)
    val3 = redact("Pengajuan izin sakit dan saldo sakit 5 hari kerja.")
    assert "izin sakit" in val3
    assert "saldo sakit" in val3
    assert "[REDACTED_MEDICAL]" not in val3

    # 4. Tetap meredaksi keluhan gejala/diagnosa medis individual secara presisi
    val4 = redact("Karyawan tidak masuk karena sakit kepala dan demam tinggi.")
    assert "[REDACTED_MEDICAL] kepala" in val4
    assert "[REDACTED_MEDICAL] tinggi" in val4


def test_redaction_covers_phone_variants_and_token_prefixes() -> None:
    value = redact("Kontak 0812.3456.7890, sk-abcdefghijkl, api-key-prod_123456.")
    assert "0812.3456.7890" not in value
    assert "sk-abcdefghijkl" not in value
    assert "api-key-prod_123456" not in value


def test_balance_tool_has_no_cross_employee_argument(client) -> None:
    response = client.post(
        "/api/v1/chat",
        headers={"Authorization": "Bearer token-alya"},
        json={"message": "Tampilkan saldo EMP-002"},
    )
    assert response.status_code == 200
    trace = client.get(
        f"/api/v1/traces/{response.json()['trace_id']}",
        headers={"Authorization": "Bearer token-alya"},
    ).json()
    assert trace["employee_id"] == "EMP-001"
