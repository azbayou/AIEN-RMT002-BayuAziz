# Milestone P2M2 — Asisten Kebijakan HR dan Cuti

Sistem **Miyo HR Assistant** menggabungkan backend **FastAPI**, **Hybrid RAG (PostgreSQL FTS `to_tsvector` + pgvector cosine + RRF)**, **Redis resilient cache**, dan dual frontend (**Web SPA** pada `http://localhost:8000/` serta **Streamlit UI** pada `http://localhost:8501`). Sistem menjawab pertanyaan kebijakan HR dengan sitasi terverifikasi, membaca saldo cuti milik pengguna terautentikasi, mengekstrak aturan cuti secara dinamis dari database (`policy_chunks`), menyiapkan proposal cuti ber-TTL, memvalidasi lampiran surat dokter sebelum konfirmasi, dan hanya membuat permintaan berstatus `pending_manager_review` sesudah konfirmasi eksplisit. Semua persona dan data bersifat sintetis.

**Level:** Intermediate · **Hasil akhir:** API FastAPI, test suite deterministik & live, evaluation runner, risk register, dan dokumentasi arsitektur.

Mulai dari [brief.md](brief.md), ikuti [lab.md](lab.md), lalu gunakan [assessment.md](assessment.md), [rubric.md](rubric.md), dan [submission-checklist.md](submission-checklist.md).

## Arsitektur & Komponen Utama

- `src/`:
  - `config.py`: konfigurasi Pydantic (`Settings`) yang aman berjalan tanpa `.env` untuk unit test in-memory, dengan `gemini_stt_model=gemini-2.5-flash` dan `reference_date` opsional.
  - `setup_lab.py`: satu-satunya modul `src/` yang membaca `data/`; melakukan seeding idempoten ke PostgreSQL (`employees` dengan PBKDF2 random-salt, `auth_sessions`, `policy_chunks` dengan index GIN + HNSW, `proposal_attachments`, `leave_attachments`, `evaluation_cases`, `medical_terms`, `monitoring_rules`), serta menghapus tabel `persona_tokens`.
  - `domain.py`: ekstraksi dinamis aturan cuti dari teks kebijakan (`get_annual_leave_lead_days`, `get_sick_leave_doc_threshold`), perhitungan hari kerja (`business_days`, `count_lead_business_days`, `compute_earliest_annual_leave_date`), dan `validate_leave_request`.
  - `retrieval.py`: Hybrid Search (PostgreSQL `to_tsvector('simple', ...)` + `pgvector` cosine similarity) dengan RRF ($k=60$), tie-breaker `0.0002 * overlap`, dan cache key ber-fingerprint dinamis (`retrieval:{policy_index_version}:{fp}:{top_k}:{digest}`).
  - `tools.py` & `agent.py`: 6 strict tools (5 base + 1 role-gated `get_team_hr_analytics`), penundaan commit `create_hr_ticket` hingga akhir turn sukses (`Outcome.escalated`), serta validator sitasi `[DOCUMENT_ID]` yang kebal terhadap kurung siku prosa seperti `[Penting]`/`[Catatan]`.
  - `security.py` & `repository.py`: redaksi offline-safe (`_BASELINE_MEDICAL_TERMS` 23 istilah + tabel `medical_terms` dengan cooldown 60s), `redact_trace` rekursif untuk objek Pydantic/nested, dan `MemoryRepository` 100% in-memory tanpa koneksi DB/file.
  - `api.py`: endpoint publik (`/healthz`, `/readyz`, `/api`, `/auth/personas`, `/auth/demo-session`, `/auth/login`) dan seluruh rute `/api/v1/*` terproteksi Bearer token, termasuk **Dynamic DB Policy Matrix** (`/api/v1/policies/rules`), lampiran pra-konfirmasi (`/api/v1/action-proposals/{id}/attachment`), dan `/api/v1/evaluation/cases`.
  - `run_evaluation.py`: evaluator otomatis yang mengambil skenario dari `GET /api/v1/evaluation/cases` dan memvalidasi `GET /api/v1/traces/{trace_id}` (tanpa membaca `data/`).
- `web/` & `app.py`: Web SPA Vue 3 + Tailwind (dengan sanitasi `DOMPurify`) dan Streamlit client (`app.py`, `ui_contract.py`).
- `Dockerfile` & `docker-compose.yml`: image non-root (`appuser` UID 10001) tanpa build-time API key untuk layanan `postgres`, `redis`, `api`, dan `streamlit`.

## Dynamic DB Policy Matrix (`policy_chunks` → Domain/Calendar/Rules → SPA)

Aturan bisnis cuti tidak ditanam statis di kode atau prompt:
1. **Database (`policy_chunks`):** Dokumen kebijakan HR (`HR-LEAVE-001`, `HR-LEAVE-002`, `HR-LEAVE-003`, dll.) difilter berdasarkan `effective_date <= active_today` dan `version` terbaru per `document_id`.
2. **Domain & Tools (`src/domain.py`, `src/tools.py`):** `get_policy_document_text` dan `policy_fingerprint()` membaca teks kebijakan aktif langsung dari repository sehingga perubahan batas hari pengajuan (misal H-3 menjadi H-1) atau ambang surat dokter (`> 2 hari kerja` menjadi `> 1 hari kerja`) otomatis memperbarui validasi `prepare_leave_request`, hasil tool `get_calendar`, dan menginvalidasi cache retrieval.
3. **API & SPA (`src/api.py`, `web/app.js`):** Endpoint terautentikasi `GET /api/v1/policies/rules` menyajikan `server_date`, `annual_lead_days`, `earliest_annual_start_date`, `sick_doc_threshold`, dan `policy_summaries`. Frontend SPA memanggil `refreshPolicyRules()` saat workspace dimuat, membuka tab kalender, membuka modal pengajuan, dan sesudah chat.

## Menjalankan Aplikasi

### Mode Docker Compose (Direkomendasikan untuk Grader & Produksi Lokal)

Ikuti kontrak pada [docker-delivery.md](docker-delivery.md):

```bash
cp .env.example .env
# Isi OPENAI_API_KEY, AGENT_MODEL, dan EMBEDDING_MODEL pada .env lokal
docker compose -p p2m2_demo build api streamlit
docker compose -p p2m2_demo up -d postgres redis
docker compose -p p2m2_demo run --rm api python -m src.setup_lab
docker compose -p p2m2_demo up -d api streamlit
docker compose -p p2m2_demo run --rm api python -m pytest -p no:cacheprovider -m "not live"
```

### Pengembangan Lokal (Host Python)

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
docker compose up -d postgres redis
python -m src.setup_lab --reset
python -m uvicorn src.api:create_app --factory --reload
# Terminal kedua:
python -m streamlit run app.py
```

*(Untuk PowerShell Windows, aktifkan venv dengan `.\.venv\Scripts\Activate.ps1` dan salin env dengan `Copy-Item .env.example .env`.)*

## Batas Sistem & Jaminan Kepatuhan

- **Pending-Only Guarantee:** Tidak ada tool maupun endpoint yang menyetujui cuti secara otomatis. Konfirmasi membuat tepat satu permintaan `pending_manager_review`. Endpoint `POST /api/v1/manager/leave-requests/{request_id}/review` dikunci mengembalikan HTTP `403` dan tidak pernah menulis status `approved` ataupun memotong saldo di runtime; tab manajer pada Web SPA bersifat *read-only* (*Antrean Tinjauan HRIS*).
- **Isolasi Identitas & Lampiran Medis:** Saldo, permintaan, lampiran, dan trace pegawai lain tidak dapat diakses lintas pengguna. Selain itu, `monitoring_admin` diblokir (`403`) dari mengunduh lampiran medis pada `GET /api/v1/leave-requests/{request_id}/attachment`.
- **Lampiran Pra-Konfirmasi:** Pengajuan cuti sakit yang melebihi ambang kebijakan (`requires_attachment=True`) wajib mengunggah dokumen (`PDF`/`PNG`/`JPEG`) ke `POST /api/v1/action-proposals/{proposal_id}/attachment` sebelum `POST /api/v1/action-proposals/{proposal_id}/confirm` (jika belum ada, API mengembalikan `409 Conflict`).
- **Sitasi Valid & Bebas Efek Samping:** Jawaban kebijakan wajib menyertakan sitasi `[DOCUMENT_ID]` yang ada pada hasil retrieval di run yang sama; bila tidak valid, sistem melakukan *abstain* dan tiket `create_hr_ticket` yang di-stage pada turn tersebut dibatalkan (tidak ditulis ke DB).
- **Kerapihan Rahasia:** Jangan mengunggah `.env`, API key, database dump, atau data pegawai nyata ke repository atau trace.

## 🌐 Akses Aplikasi & Dokumentasi

- **Modern Web SPA (FastAPI Static):** [http://localhost:8000/](http://localhost:8000/) (dan `/portal/`)
- **Streamlit Web UI:** [http://localhost:8501](http://localhost:8501)
- **FastAPI Swagger Interactive Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **FastAPI OpenAPI JSON Specification:** [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)
- **API Metadata:** [http://localhost:8000/api](http://localhost:8000/api)

---

## 🧪 Menjalankan Pengujian (Testing Suite)

Suite `tests/` terdiri atas **9 file** (`conftest.py`, `test_actions.py`, `test_agent_reliability.py`, `test_api.py`, `test_domain.py`, `test_live_api.py`, `test_p0_p1_remediation.py`, `test_retrieval_security.py`, dan `test_supplied_ui.py`) dengan **30 deterministic test items** (29 fungsi test, `-m "not live"`) dan **1 live test** (`-m live`).

### A. Pengujian Deterministik Non-Live (Tanpa DB/Jaringan/Env)
Seluruh 30 test deterministik berjalan 100% in-memory tanpa memerlukan `.env`, PostgreSQL, atau jaringan luar:
```bash
PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider -m "not live" -v
```
Atau di dalam container Docker:
```bash
docker compose -p p2m2_demo exec -T api python -m pytest -p no:cacheprovider -m "not live" -v
```

### B. Pengujian Live API (1 Live Test)
Menjalankan pengujian live (`tests/test_live_api.py::test_live_policy_question`) terhadap API yang sedang berjalan:
```bash
docker compose -p p2m2_demo exec -T -e RUN_LIVE_TESTS=1 -e API_URL=http://localhost:8000 api python -m pytest -p no:cacheprovider -m live -o addopts=""
```

### C. Menjalankan Evaluator Komprehensif (15 Skenario)
Runner mengambil skenario evaluasi langsung dari API (`GET /api/v1/evaluation/cases`), memeriksa setiap trace (`GET /api/v1/traces/{trace_id}`), menghitung `retrieval_recall_at_3` dari `retrieved_document_ids[:3]`, memvalidasi `citation_validity` terhadap `retrieved_document_ids`, memeriksa `forbidden_facts` pada jawaban maupun trace JSON, serta memverifikasi `requires_confirmation is True` dan `outcome == "action_proposed"` pada `leave-valid-008`:
```bash
docker compose -p p2m2_demo exec -T api python -m src.run_evaluation --base-url http://localhost:8000 --token token-alya
```
Hasil evaluasi tersimpan di `outputs/evaluation_report.json` (`evaluated_at: 2026-11-18T07:09:00.388558+00:00`):
- **Total Kasus:** `15 / 15` Passed (`overall_pass_rate: 1.0`)
- **Hard Gates:** `6 / 6` Passed (`hard_gates_passed: true`)
- **Recall@3 & Citation Validity:** `1.0` & `1.0` (`tool_selection_accuracy: 1.0`)
- **Latensi & Biaya:** `p50 = 3511.07 ms`, `p95 = 5859.83 ms`, `41,038` input / `1,593` output tokens (`estimated_cost: $0.0049`)
- **Keputusan Rilis:** `release_decision: "release"`

---

## 👥 Persona & Matriks Otorisasi

Autentikasi API menggunakan pencocokan hash SHA-256 pada tabel `employees.token_hash` dan `auth_sessions.session_token_hash` (tabel `persona_tokens` dihapus oleh `setup_lab.py`). Endpoint `GET /auth/personas` tidak membocorkan saldo maupun token; sesi demo (`sess_...`) hanya dapat dibuat untuk role `employee` melalui `POST /auth/demo-session`, sedangkan role istimewa wajib login password melalui `POST /auth/login`.

| Persona | ID Pegawai | Role | Saldo Awal (`employees.json`) | Hak Akses & Batasan |
|---|---|---|---|---|
| **Alya Pratama** | `EMP-001` | `employee` | Annual `8 hari`, Sick `10 hari`, Parental `60 hari` | Akses kebijakan, saldo, proposal, lampiran, tiket, dan trace milik sendiri. |
| **Bima Santoso** | `EMP-002` | `employee` | Annual `3 hari`, Sick `10 hari`, Parental `60 hari` | Akses kebijakan, saldo, proposal, dan trace pribadi; terisolasi penuh dari Alya. |
| **Monitoring Admin** | `ADM-001` | `monitoring_admin` | `-` | Login wajib password (`requires_password=true`); akses `/api/v1/monitoring/*`, `/api/v1/analytics/overview`, trace ter-redaksi. Diblokir (`403`) dari lampiran medis pegawai dan approval cuti. |

---

## 🛡️ Ringkasan Hard Gates Kepatuhan

| # | Hard Gate | Status | Mekanisme Pencegahan |
|---|---|:---:|---|
| 1 | **Identity Binding & Auth Isolation** | ✅ PASSED | `employee_id` hanya dari `AuthContext`; `/auth/personas` tanpa saldo/token; semua `/api/v1/*` wajib Bearer token. |
| 2 | **Pending-only Action** | ✅ PASSED | Status cuti terkunci `pending_manager_review`; `POST /api/v1/manager/leave-requests/{id}/review` dikunci HTTP `403`. |
| 3 | **Confirmation, Attachment & Idempotency** | ✅ PASSED | Proposal ber-TTL; cuti sakit `> threshold` wajib upload `proposal_attachments` sebelum `/confirm` (`409` jika belum); replay idempotency konsisten. |
| 4 | **Valid Citation & Abstain** | ✅ PASSED | Sitasi `[DOCUMENT_ID]` divalidasi terhadap chunk retrieval aktif; tiket `create_hr_ticket` ditunda dan dibatalkan jika turn berakhir abstain. |
| 5 | **Redacted Trace & Medical Privacy** | ✅ PASSED | Sanitasi PII + `_BASELINE_MEDICAL_TERMS` offline-safe + `redact_trace` rekursif; `monitoring_admin` diblokir (`403`) dari medical attachment; Opik tanpa prompt mentah. |
| 6 | **Non-Root Docker Image** | ✅ PASSED | `Dockerfile` & `Dockerfile.vercel` menggunakan `appuser` (UID 10001), tanpa secret API key, dan `.dockerignore` mengecualikan `**/__pycache__` & `.env`. |

---

## 📊 Monitoring Operasional & Rules

Aturan monitoring di-seed sekali dari [data/monitoring_rules.json](data/monitoring_rules.json) ke tabel PostgreSQL `monitoring_rules` oleh `src/setup_lab.py` (dengan fallback in-memory default pada `MemoryRepository`):
- `agent-error-spike`: Ambang batas `error_rate > 0.20` (minimum 5 sampel) → Owner: `AI Platform`.
- `agent-latency-p95`: Ambang batas `p95_latency_ms > 8000 ms` (minimum 5 sampel) → Owner: `AI Platform`.

Akses monitoring summary membutuhkan Bearer token admin (misal token sesi hasil `/auth/login` atau token demo `token-admin`):
```bash
curl -H "Authorization: Bearer token-admin" http://localhost:8000/api/v1/monitoring/summary
```
