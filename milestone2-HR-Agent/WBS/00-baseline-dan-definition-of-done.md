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
## Checkpoint Submission — 2026-11-05

| WBS | Status checkpoint | Bukti | Kesimpulan sebelum submission |
|---|---|---|---|
| WBS-00 | DONE untuk baseline | Baseline terdokumentasi; hard gate sudah ditetapkan | Tidak perlu implementasi baru, tetapi laporan baseline perlu diperbarui bila suite berubah |
| WBS-01 | DONE | `python -m pytest tests/test_domain.py` -> 5 passed | Tidak ada TODO wajib dari modul domain |
| WBS-02 | BELUM FINAL | Redaction test terisolasi lulus; full file masih terblokir API/retrieval | Ganti daftar istilah medis hardcode dengan sumber konfigurasi/aturan yang direview, tambah edge test, dan pastikan semua call site telemetry melakukan redaction sebelum persist |
| WBS-03 | BELUM FINAL | Validasi invalid model/message lulus; konfigurasi helper terkompilasi | Integrasikan pemeriksaan database, index, cache, dan model ke `/readyz`; tambah test kontrak dan problem-detail API; review kembali validator terhadap environment production |
| WBS-04 | BELUM FINAL | `tests/test_actions.py` -> 3 passed; smoke auth/redaction lulus | Implementasikan loader employee dari fixture/seed, selesaikan `PostgresRepository` dengan parameterized SQL/transaction, dan tambah test owner isolation untuk proposal/request/trace |
| WBS-05 | CHECKPOINT - IMPLEMENTED | Cache resilience smoke test dan regression domain/action lulus | Tambah test Redis failure/JSON/TTL dan integrasikan versioned key serta cache health ke retrieval/API |
| WBS-06 | CHECKPOINT - IMPLEMENTED | Provider fake/compile smoke validation | Tambah test fake OpenAI client, wiring timeout, strict tool schema, dan verifikasi SDK live |
| WBS-07 | CHECKPOINT - IMPLEMENTED | Parser policy deterministik/compile validation | Tambah schema seed lengkap, test PostgreSQL idempotency/dimensi/reset, wiring `PostgresRepository`, dan verifikasi Docker seed |
| WBS-08 | CHECKPOINT - IMPLEMENTED | Retrieval acceptance test dan compile validation | Tambah test cache/failure/version isolation, wiring settings, production repository search, dan citation edge cases |
| WBS-09 | CHECKPOINT - IMPLEMENTED | `tests/test_tools.py` + domain/action: 12 passed; extra tool fields rejected | Tambah fake-client provider compatibility, agent/API error mapping, dan verifikasi proposal production |
| WBS-10 | CHECKPOINT - IMPLEMENTED | Agent loop, abstention, redacted trace implementation; reliability tests pending rerun | Tambah test multi-turn/budget/citation valid, rapikan provider conversation items, cegah trace duplicate, dan integrasikan API error mapping |
| WBS-11 | CHECKPOINT - IMPLEMENTED | `tests/test_api.py`: 4 passed; dependency regressions: 15 passed | Tambah test endpoint/alerts/readiness, perbaiki fixture token distinct, selesaikan PostgresRepository, dan finalisasi monitoring integration |
| WBS-12 | CHECKPOINT - IMPLEMENTED | Compose valid, Docker build sukses, image `appuser`, API/agent image tests: 7 passed | Jalankan Compose runtime/seed, cek endpoint, dan review PostgresRepository sebelum submission |

### TODO sebelum submission

1. Implementasikan WBS-05 cache, terutama degradation Redis tanpa mengubah correctness retrieval.
2. Implementasikan WBS-06 provider live/fake dengan timeout, retry bounded, `store=False`, strict tools, dan safety ID ter-hash.
3. Implementasikan WBS-07 setup/seed agar policy metadata, identity, saldo, dan hash token masuk ke storage.
4. Implementasikan WBS-08 retrieval; hilangkan `NotImplementedError` dan pastikan citation berasal dari chunk hasil run yang sama.
5. Implementasikan WBS-09 tools dengan validasi Pydantic dan identity dari `AuthContext`.
6. Implementasikan WBS-10 agent dengan bounded loop, abstention, valid citation, usage, dan trace ter-redact.
7. Implementasikan WBS-11 API, auth, authorization, problem detail, health/readiness, dan delapan endpoint.
8. Jalankan ulang `python -m pytest -m "not live"`, lalu validasi Docker Compose, seed, readiness, dan hard gate submission.
