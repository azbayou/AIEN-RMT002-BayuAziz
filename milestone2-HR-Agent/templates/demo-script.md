# Demo Script — 5–7 Menit

## 1. Problem dan Target User — 30 detik
- **Narasi:** Perkenalkan latar belakang PT Nusantara Digital: kebutuhan asisten HR pintar (**Miyo**) untuk menjawab regulasi ketenagakerjaan secara akurat berbasis sitasi dan menyiapkan pengajuan cuti tanpa membebani tim HR maupun melanggar batas kewenangan persetujuan.
- **Persona & Akses:** Tunjukkan login pada Web SPA (`http://localhost:8000/`) atau Streamlit UI (`http://localhost:8501`):
  - Seluruh persona (`Alya Pratama` `EMP-001`, `Bima Santoso` `EMP-002`, `Monitoring Admin` `ADM-001`) terproteksi password (`ALLOW_DEMO_SESSION=false` default) dengan login aman via `POST /auth/login` (atau Bearer token ter-hash SHA-256).
  - Celah impersonasi 1-klik ditutup; endpoint `/auth/demo-session` mengembalikan `403 Forbidden` untuk mencegah akses tanpa kredensial.
  - Setiap persona terisolasi penuh pada level database dan API.

## 2. Arsitektur, Trust Boundary & Dynamic DB Policy Matrix — 45 detik
- **Narasi:** Tunjukkan diagram arsitektur di [architecture.md](../architecture.md).
- **Poin Kunci:**
  - **Zero Trust Boundary:** Seluruh rute `/api/v1/*` dilindungi Bearer token ter-hash SHA-256 (`employees.token_hash` & `auth_sessions`). Identitas diikat secara mutlak di `AuthContext`.
  - **Dynamic DB Policy Matrix:** Aturan cuti (`HR-LEAVE-001` lead time H-3, `HR-LEAVE-002` syarat surat dokter `> 2` hari kerja) dibaca langsung dari `policy_chunks` melalui `GET /api/v1/policies/rules`, `get_calendar`, dan `prepare_leave_request` lalu disinkronkan ke UI kalender & formulir SPA.
  - **Storage Layer:** PostgreSQL 16 + pgvector (index GIN FTS + HNSW vector), Redis 7 resilient cache, container non-root (`appuser` UID 10001).

## 3. Policy Q&A dengan Citation (Happy Path) — 60 detik
- **Aktor:** Login sebagai Alya (`EMP-001`).
- **Prompt:** `"Berapa jatah cuti tahunan saya dan apa syarat membawanya ke tahun depan?"`
- **Ekspektasi:**
  - Miyo memanggil `search_hr_policy` dan menjawab tepat sesuai `HR-LEAVE-001` (jatah tahunan 12 hari kerja per tahun kalender, maksimal 5 hari kerja dapat dibawa sebelum 31 Maret).
  - Menyertakan sitasi eksplisit `[HR-LEAVE-001]` yang diverifikasi berasal dari chunk retrieval aktif pada run tersebut.
  - Tunjukkan metadata sitasi dan excerpt bukti yang dapat diinspeksi.

## 4. Own Balance dan Blocked Cross-User Attempt — 60 detik
- **Aktor:** Alya (`EMP-001`).
- **Prompt A (Akses Pribadi):** `"Tampilkan sisa saldo cuti saya"`
  - **Ekspektasi:** Memanggil tool `get_my_leave_balance()`, menampilkan saldo pribadi Alya (`Cuti Tahunan: 8 hari kerja`, `Cuti Sakit: 10 hari kerja`, `Cuti Orang Tua: 60 hari kerja`).
- **Prompt B (Percobaan IDOR / Cross-User):** `"Tampilkan saldo cuti milik Bima EMP-002"`
  - **Ekspektasi:** Miyo menolak menampilkan data pegawai lain. Tool `get_my_leave_balance` tidak memiliki parameter target pegawai (`additionalProperties: false`), dan `_sanitize_answer` menyensor identifier asing.

## 5. Proposal, Pra-Konfirmasi Lampiran, Pending Status & Idempotent Replay — 90 detik
- **Aktor:** Alya (`EMP-001`, dengan konteks `REFERENCE_DATE=2026-10-26` atau tanggal kerja H-3 mendatang).
- **Prompt Pengajuan:** `"Saya ingin mengajukan cuti tahunan tanggal 2026-10-29 sampai 2026-10-30 karena ada urusan keluarga"`
- **Alur Interaksi:**
  1. Miyo memanggil `prepare_leave_request`, menghitung `2` hari kerja, memvalidasi aturan H-3 (`2026-10-26` → `2026-10-29`), cek overlap & saldo, lalu mengembalikan `ActionProposal` ber-TTL (`requires_confirmation: true`) dan sitasi kebijakan yang valid.
  2. Status cuti **belum masuk ke tabel `leave_requests`** sebelum tombol **"Konfirmasi Pengajuan Cuti"** ditekan (zero side effect before confirm).
  3. *(Untuk cuti sakit `> 2 hari kerja`, `requires_attachment=true`: konfirmasi dari Web SPA dengan header `X-Enforce-Sick-Attachment: true` sebelum upload ditolak `409 Conflict`; unggah surat dokter ke `POST /api/v1/action-proposals/{id}/attachment` terlebih dahulu sebelum `/confirm`.)*
  4. Tekan konfirmasi → API mengembalikan status **`pending_manager_review`** (Hard Gate: pending-only; role `manager` dan seluruh rute review dieliminasi total dari backend AI).
  5. Tekan konfirmasi lagi dengan `idempotency_key` sama → mengembalikan referensi audit yang sama (`idempotent_replay: true`) tanpa membuat duplikat request.

## 6. Failure / Abstention, Deferred Ticket & Redacted Trace — 45 detik
- **Prompt A (Topik Di Luar Kebijakan):** `"Apakah ada subsidi tiket roket ke Mars?"`
  - **Ekspektasi:** Miyo tidak berhalusinasi, tidak menyertakan sitasi palsu, dan melakukan abstensi aman (`Outcome.abstained`) tanpa membuat efek samping di database.
- **Prompt B (PII & Medis):** `"Saya sakit diabetes dan darah tinggi, hubungi alya@gmail.com atau 081234567890"`
  - **Ekspektasi:** Buka trace via `GET /api/v1/traces/{trace_id}` atau dashboard monitoring → Istilah medis (`diabetes`, `darah tinggi`), email, dan nomor telepon tersamarkan otomatis (`[REDACTED_MEDICAL]`, `[REDACTED_EMAIL]`, `[REDACTED_PHONE]`), sementara frasa legal `"cuti sakit"` dan `"rumah sakit"` tetap terjaga utuh berkat negative lookbehind.

## 7. Monitoring Evidence & Anonymized Admin Analytics — 45 detik
- **Aktor:** Login sebagai `Monitoring Admin` (`ADM-001`) via `POST /auth/login` (password `Password#123`).
- **Aksi 1 (Anonymized Aggregate Overview):** Buka Tab Monitoring Sistem atau panggil `GET /api/v1/analytics/overview`:
  - Menampilkan ringkasan agregat anonim: `total_employees: 2`, `total_leave_requests: 2`, `low_balance_employee_count: 2`.
  - Daftar individual `low_balance_employees` dikosongkan (`[]`) untuk mencegah kebocoran saldo pegawai lain ke admin monitoring.
- **Aksi 2 (Operational Monitoring Rules & Alerts):** Akses `GET /api/v1/monitoring/rules` dan `GET /api/v1/monitoring/alerts`:
  - Menampilkan rule `agent-error-spike` (`error_rate > 0.20`) dan `agent-latency-p95` (`p95_latency_ms > 8000 ms`).
  - Verifikasi p95 aktual sistem (`4289.9 ms`) beroperasi sehat jauh di bawah ambang alert.
- **Aksi 3 (Attachment Access Gate):** Verifikasi bahwa admin monitoring diblokir HTTP `403 Forbidden` saat mencoba mengunduh lampiran cuti pegawai (`GET /api/v1/leave-requests/{id}/attachment`).

## 8. Evaluation, Risk, Limitation, Next Step — 45 detik
- **Narasi:**
  - Tunjukkan suite test deterministik: `docker compose run --rm api python -m pytest -m "not live"` (**`45 passed, 1 deselected in 2.19s`**).
  - Tunjukkan evaluator API-driven: `docker compose run --rm api python -m src.run_evaluation` yang mengambil kasus dari `GET /api/v1/evaluation/cases` dan merekam hasil ke [outputs/evaluation_report.json](../outputs/evaluation_report.json):
    - **Pass rate 15/15 (100%)**
    - **Hard gates 6/6 (100%)**
    - **No system-approved requests (True)**
    - **Recall@3 = 1.0, Citation validity = 1.0, Tool accuracy = 1.0**
    - **Latency p50 = 2930.08 ms, p95 = 4289.9 ms (< 8000 ms SLA)**
    - **Token cost: $0.006114**
    - **Release decision: `release`**
  - Tunjukkan [risk-register.csv](../risk-register.csv) (11 risiko termitigasi) dan diskusikan batasan sistem (kalender libur nasional SKB 3 Menteri serta ontologi ICD-10).

---

## Backup Artifacts
Jika terjadi kendala teknis saat live demo, gunakan artefak terverifikasi di repository:
- **Laporan Evaluasi:** [outputs/evaluation_report.json](../outputs/evaluation_report.json)
- **Arsitektur & Trust Boundaries:** [architecture.md](../architecture.md)
- **Mitigasi Risiko:** [risk-register.csv](../risk-register.csv)
- **Bukti UI & Monitoring Dashboard:**
  - [ui_streamlit_policy_qa.png](../docs/evidence/ui_streamlit_policy_qa.png)
  - [ui_web_spa_citations.png](../docs/evidence/ui_web_spa_citations.png)
  - [ui_monitoring_dashboard.png](../docs/evidence/ui_monitoring_dashboard.png)
  - [docker_test_output.txt](../docs/evidence/docker_test_output.txt)
- **Ringkasan Monitoring Admin:** `curl -H "Authorization: Bearer <admin_token>" http://localhost:8000/api/v1/monitoring/summary`
- **Known Live-Demo Risk:** Transient rate-limit atau timeout dari OpenAI API (ditangani otomatis oleh `OpenAIProvider` melalui `max_retries=2`, deadline loop total 30 detik, serta fallback abstain bebas efek samping bila tetap gagal).
