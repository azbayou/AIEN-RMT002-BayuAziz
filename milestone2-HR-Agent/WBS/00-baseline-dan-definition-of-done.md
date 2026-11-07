# WBS-00 — Baseline dan Definition of Done

- **Target:** seluruh repository, terutama `pelajari.md`, `brief.md`, `rubric.md`, dan `docker-delivery.md`.
- **Owner:** Pemilik repo + agent AI.
- **Status:** DONE

## Pekerjaan

1. Pastikan working tree bersih dari perubahan yang tidak terkait.
2. Pasang dependency dari `requirements.txt`.
3. Jalankan `pytest -m "not live"` dan catat failure baseline.
4. Buat daftar acceptance test dari `submission-checklist.md`.
5. Tetapkan aturan yang tidak boleh berubah: identity binding, pending-only action,
   valid citation, redacted trace, dan non-root Docker image.

## Output

- Baseline test report.
- Daftar hard gate yang dapat diverifikasi.
- Keputusan dependency dan migration approach.

## Acceptance criteria

- Semua pekerjaan memiliki owner dan dependency.
- Tidak ada implementasi yang dimulai sebelum kontrak endpoint dan data dipahami.


==============================
## Catatan Baseline & Hasil Eksekusi

### 1. Baseline Test Report (pytest -m "not live")
- **Waktu Eksekusi:** Baseline awal sebelum implementasi kode.
- **Hasil:** `12 failed, 4 passed, 1 deselected, 5 errors (Total: 22 test items, 21 selected)`
  - **4 PASSED:**
    - `test_unsupported_leave_type_is_rejected_by_contract` (Validasi Pydantic kontrak dasar)
    - `test_supplied_personas_match_public_identity_contract` (Kontrak persona UI)
    - `test_persona_change_clears_prior_response_and_confirmation_key` (State UI Streamlit)
    - `test_supplied_ui_uses_documented_api_paths` (Routing endpoint UI Streamlit)
  - **5 ERRORS (Blokir Fixture FastAPI `create_app`):**
    - `test_health_and_auth_contract`
    - `test_chat_returns_contract_and_trace`
    - `test_monitoring_is_admin_only`
    - `test_trace_cannot_be_read_by_another_employee`
    - `test_balance_tool_has_no_cross_employee_argument`
    *(Penyebab: `src/api.py::create_app` masih `raise NotImplementedError`)*
  - **12 FAILURES (Skeleton Belum Diimplementasikan):**
    - `test_actions.py` (3 test): `MemoryRepository` belum punya method `save_proposal`.
    - `test_agent_reliability.py` (3 test): `AgentService.run` dan `chunk_policy` masih `NotImplementedError`.
    - `test_domain.py` (4 test): `business_days` dan `validate_leave_request` masih `NotImplementedError`.
    - `test_retrieval_security.py` (2 test): `RetrievalService.search` dan `redact` masih `NotImplementedError`.
  - **1 DESELECTED:**
    - `test_live_api.py::test_live_policy_question` (dilewati karena marker `live`).

### 2. Hard Gates yang Terkunci (Non-Negotiable)
1. **Identity Binding:** `employee_id` hanya bersumber dari `AuthContext` via token bearer, dilarang mengambil dari argumen/body/prompt.
2. **Pending-only Action:** Asisten tidak boleh meng-approve cuti; status hanya boleh `pending_manager_review`.
3. **Explicit Confirmation & Idempotency:** Action proposal ber-TTL tidak langsung menulis ke database cuti tanpa konfirmasi eksplisit; request berulang dengan key sama tidak menduplikasi data.
4. **Valid Citation & Abstain:** Model wajib menyertakan sitasi valid dari chunk kebijakan yang diretrieve; jika sitasi invalid atau tidak ditemukan, wajib abstain/fallback.
5. **Redacted Trace & PII:** Redaksi email, nomor telepon Indonesia, secret token, dan catatan diagnosis medis sebelum disimpan di trace.
6. **Non-Root Docker Delivery:** Container Docker wajib berjalan sebagai non-root dan build image tidak boleh membutuhkan `OPENAI_API_KEY`.

### 3. Keputusan Environment & Dependencies
- **OS Host:** Linux Mint (Ubuntu 24.04-based) dengan Conda environment `hr-agent` (Python 3.11).
- **Target Delivery:** Multi-service Docker Compose (PostgreSQL 16 pgvector, Redis 7, FastAPI API, Streamlit UI) sesuai `docker-delivery.md`.
- **Status WBS-00:** Selesai (DONE). Siap lanjut ke **WBS-01 (Implementasi `src/domain.py`)**.

==============================
## Checkpoint Submission — 2026-11-07 (FINAL)

| WBS | Status checkpoint | Bukti | Kesimpulan sebelum submission |
|---|---|---|---|
| WBS-00 | **DONE** | Baseline & 6 Hard Gates terkunci | Terpenuhi 100% |
| WBS-01 | **DONE** | `tests/test_domain.py`: 8 passed | Validasi business days, overlap, lead time terpenuhi |
| WBS-02 | **DONE** | `tests/test_retrieval_security.py`: 6 passed | Redaction SSOT (`data/medical_terms.json`), lookbehind `cuti sakit` |
| WBS-03 | **DONE** | `tests/self_test_contracts_config.py`: 17 passed | Pydantic contracts `extra="forbid"`, RFC 7807 problem details |
| WBS-04 | **DONE** | `tests/self_test_cache_providers.py`: 8 passed, `tests/test_repository_postgres.py`: 2 passed | MemoryRepository via `data/employees.json`, PostgresRepository pool + `FOR UPDATE` |
| WBS-05 | **DONE** | `tests/test_agent_reliability.py`: Redis outage degraded | ResilientCache graceful degradation, versioned cache key |
| WBS-06 | **DONE** | `tests/self_test_cache_providers.py`: passed | OpenAIProvider store=False, safety_id SHA-256 hash, transient retry |
| WBS-07 | **DONE** | `tests/self_test_setup_and_retrieval.py`: 6 passed | Stable chunk IDs, schema DDL + vector index, offline seed |
| WBS-08 | **DONE** | `tests/self_test_setup_and_retrieval.py`: passed | Hybrid lexical + vector search (RRF k=60), reranking keyword |
| WBS-09 | **DONE** | `tests/test_tools.py`: 4 passed, `tests/self_test_tools_agent.py`: passed | 4 strict tools, identity bound to AuthContext, side-effect free proposal |
| WBS-10 | **DONE** | `tests/test_agent_reliability.py`: 7 passed, live API chat passed | Multi-turn Responses loop, strict citation validation & abstention, telemetry cost |
| WBS-11 | **DONE** | `tests/test_api.py`: 4 passed, `tests/self_test_api_docker.py`: passed | 8 endpoints, auth matrix, dynamic monitoring rules evaluation |
| WBS-12 | **DONE** | Docker container build & compose healthy, image `appuser` (UID 10001) | Non-root runtime, port 8000, multi-service single image, offline build |
| WBS-13 | **DONE** | `tests/test_domain.py`: 8 passed, `tests/test_retrieval_security.py`: 6 passed | Domain lead time, business days, and redaction test suite 100% passed |
| WBS-14 | **DONE** | `tests/test_actions.py`: 6 passed, `tests/test_repository_postgres.py`: 2 passed | Pending-only, explicit confirmation, idempotency key, owner isolation verified |
| WBS-15 | **DONE** | `tests/test_agent_reliability.py`: 7 passed, `tests/test_live_api.py`: 1 passed | Non-live suite passed, live policy question with citations passed against Docker API |
| WBS-16 | **DONE** | `src/run_evaluation.py`: 15/15 passed (100%), 6/6 hard gates, `release_decision: release` | `outputs/evaluation_report.json` generated and verified |
| WBS-17 | **DONE** | `architecture.md`, `risk-register.csv`, `data/monitoring_rules.json`, `README.md` | 6 ADR, Mermaid trust boundaries, 9 mitigations with runnable test evidence |
| WBS-18 | **DONE** | Full checklist verified: git diff check, containers healthy, OpenAPI, Streamlit | Keputusan release: **`READY`** |

### Ringkasan Status Final
- **Seluruh 19 Modul WBS (WBS-00 s/d WBS-18):** Telah selesai 100% dan berstatus **DONE**.
- **Test Suite:** 38 passed non-live, 2 passed PostgreSQL integration, 44 passed self-tests, 1 passed live test.
- **Evaluation Runner:** 15/15 cases passed (100%), 6/6 hard gates passed, release decision: **RELEASE**.
- **Release Validation:** Seluruh checklist release terpenuhi, keputusan rilis: **`READY`**.
- **6 Hard Gates:** Terpenuhi 100% pada level unit, integrasi repository, API, Docker container, dan evaluasi live model LLM.
