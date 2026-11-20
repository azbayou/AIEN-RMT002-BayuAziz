# Final Presentation Outline — Miyo HR Assistant (PT Nusantara Digital)

---

## Slide 1: User Problem and Measurable Success Criteria
- **User Problem:**
  - Karyawan kesulitan menavigasi dokumen regulasi ketenagakerjaan dan SOP internal HR untuk mengetahui hak cuti, aturan kerja fleksibel (WFH), dan syarat dokumen cuti sakit.
  - Pengelolaan aturan manual rentan inkonsistensi ketika kebijakan berubah, sementara agen AI tanpa guardrail berisiko melakukan persetujuan sepihak atau membocorkan data medis/PII pegawai.
- **Measurable Success Criteria:**
  - **Retrieval Recall@3 $\ge 80\%$** (diukur dari `trace.retrieved_document_ids[:3]`) dan **Citation Validity $= 100\%$** (diukur terhadap `trace.retrieved_document_ids`).
  - **Zero Unauthorized Approval:** $100\%$ permohonan cuti berstatus `pending_manager_review`; role `manager` dan seluruh rute review dieliminasi total dari sistem AI.
  - **Zero Cross-Employee Access (IDOR Prevention):** $100\%$ pemblokiran akses saldo, lampiran medis, dan trace antar pegawai.
  - **Data Privacy & Redaction:** Penyensoran PII/medis di trace DB & Opik Cloud (telemetri strictly metadata-only), serta pemblokiran akses lampiran medis bagi `monitoring_admin` (`403`).
  - **Performance:** Latensi p95 $< 8000\text{ ms}$ dengan degradasi aman bila Redis/embedding terganggu.

---

## Slide 2: Why RAG + Bounded Agent + Dynamic DB Policy Matrix
- **Kelemahan Pendekatan Statis:**
  - *Context Stuffing / Prompt Hardcoding:* Mahal, *lost in the middle*, dan menyulitkan pembaruan kebijakan.
  - *Fine-Tuning:* Bobot model statis dan tidak memiliki sitasi chunk terverifikasi.
- **Pendekatan Miyo:**
  - **Grounded Hybrid RAG:** Mengambil chunk versi terbaru dan berlaku (`effective_date <= today`) dari PostgreSQL (`to_tsvector` + `pgvector`).
  - **Dynamic DB Policy Matrix:** `policy_chunks` → `src/domain.py` / `get_calendar` / `GET /api/v1/policies/rules` → Web SPA. Perubahan kebijakan di DB otomatis mengubah validasi & kalender UI tanpa mengubah kode.
  - **Bounded Agent Turns:** Maksimal 4 putaran, 6 pemanggilan tool, 700 output tokens, deadline total 30 detik, `max_retries=0` pada OpenAI SDK (retry tunggal di `_call`), dan abstensi wajib bila bukti tidak sah.

---

## Slide 3: Architecture and Trust Boundaries
- **Komponen Sistem:**
  - **Presentation Layer:** Modern Web SPA (`web/index.html` + `web/app.js` dengan `DOMPurify`) di port `8000` (`/` dan `/portal/`) serta Streamlit UI (`app.py`) di port `8501`.
  - **Application Layer:** FastAPI Orchestrator (`src/api.py`, non-root `appuser` UID `10001`) dengan hash-only auth (`employees.token_hash` & `auth_sessions`, tanpa `persona_tokens`).
  - **Data & Cache Layer:** PostgreSQL 16 (`pgvector`, GIN + HNSW, transaksi `FOR UPDATE`) dan Redis 7 (`ResilientCache` timeout 0.5 detik).
- **Trust Boundaries (TB):**
  - **TB 1 (Public/Client):** Input chat, file upload (magic bytes PDF/PNG/JPEG), audio STT, dan DOM Markdown disanitasi; semua `/api/v1/*` wajib Bearer token (`ALLOW_DEMO_SESSION=false` default).
  - **TB 2 (API Gateway):** Seluruh persona wajib `/auth/login` (password); celah impersonasi 1-klik ditutup (`/auth/demo-session` mengembalikan `403`); rute review manajer dieliminasi.
  - **TB 3 (Repository & DB):** Predikat kepemilikan `auth.employee_id`, `monitoring_admin` menerima agregat anonim (`low_balance_employees=[]`) dan diblokir `403` dari lampiran medis.
  - **TB 4 (External AI & Opik):** `store=False`, `safety_identifier` ber-hash SHA-256, dokumen kebijakan sebagai *untrusted data*, Opik menerima telemetri strictly metadata-only tanpa prompt/jawaban mentah.

---

## Slide 4: Retrieval and Citation Design
- **Hybrid Search Architecture:**
  - Full-Text Search PostgreSQL (`to_tsvector('simple', ...)` dengan index **GIN** `policy_chunks_fts_idx`) digabungkan dengan Cosine Similarity `pgvector` (index **HNSW** `policy_chunks_embedding_hnsw_idx` untuk `dimension <= 2000`).
  - Penggabungan peringkat via *Reciprocal Rank Fusion (RRF)* ($k=60$) + tie-breaker keyword (`0.0002 * overlap`) serta cache key ber-fingerprint dinamis (`retrieval:{version}:{fp}:{top_k}:{digest}`).
- **Citation Guardrail & Verification:**
  - Regex terarah `_CITATION_TAG_RE` (`[A-Z]{2,}-[A-Z0-9]+-[0-9]+`) mendukung multi-ID bracket `[DOC-A, DOC-B]` dan mencegah kurung siku prosa seperti `[Penting]`/`[Catatan]` memicu false abstention, sambil tetap menolak `[HR-FAKE-999]` (`Outcome.abstained`).
  - Sitasi valid dipertahankan pada `answered`, `action_proposed`, dan `escalated`.

---

## Slide 5: Tool, Deferred Ticket, Attachment Gate & Confirmation Design
- **Katalog 6 Tool yang Diizinkan (5 Base + 1 Role-Gated):**
  1. `search_hr_policy(query, top_k)`: Pencarian kebijakan HR ter-index.
  2. `get_my_leave_balance()`: Membaca saldo pribadi tanpa parameter input (`additionalProperties: false`).
  3. `prepare_leave_request(start_date, end_date, leave_type, reason)`: Validasi domain H-N dinamis, overlap, saldo efektif, sanitasi `reason`, dan pembuatan `ActionProposal` ber-TTL (deferred DB write).
  4. `create_hr_ticket(category, summary)`: Di-stage (`defer_tickets=True`) dan hanya di-commit jika turn berakhir sukses tanpa abstensi (`Outcome.escalated`).
  5. `get_calendar(days)`: Mengembalikan `annual_lead_days`, `earliest_annual_leave_date`, `sick_doc_threshold`, dan status `can_book_annual_leave` live dari DB.
  6. `get_team_hr_analytics(metric_focus, low_balance_threshold)`: Khusus role `monitoring_admin`, mengembalikan agregat anonim tanpa PII individual.
- **Two-Phase Confirmation & Attachment Gate:**
  - Proposal cuti sakit dengan `requires_attachment=True` mewajibkan upload surat dokter ke `POST /api/v1/action-proposals/{id}/attachment` (`proposal_attachments`) sebelum `/confirm` pada Web SPA via header `X-Enforce-Sick-Attachment: true` (`409` jika belum, tetap kompatibel penuh tanpa 409 pada Streamlit `app.py`).
  - `POST /api/v1/action-proposals/{id}/confirm` memvalidasi ulang tanggal tidak masa lalu, lampiran, overlap (`pending_manager_review` & `approved`), dan saldo dalam transaksi `FOR UPDATE`, lalu membuat tepat satu request `pending_manager_review` dengan `idempotency_key`.

---

## Slide 6: FastAPI and Deployment
- **Docker Delivery Contract:**
  - Multi-container orchestration: `api`, `postgres`, `redis`, `streamlit`.
  - Image non-root `appuser:10001` dibangun tanpa runtime API key; `.dockerignore` mengecualikan `.env`, `docs/`, `**/__pycache__`, `**/*.py[cod]`, `outputs/`.
  - `docker-compose.yml` menyertakan `REFERENCE_DATE`, `MODEL_MODE`, `GEMINI_STT_MODEL=gemini-2.5-flash`, `ALLOW_DEMO_SESSION: "false"`, `INPUT_COST_PER_1M`, dan `OUTPUT_COST_PER_1M` tanpa bind-mount host pada container `api`.
- **Health & Presentation Endpoints:**
  - `/healthz`: Liveness HTTP 200.
  - `/readyz`: Status `database`, `cache`, dan `configuration` (degradasi aman 200 saat Redis tidak tersedia).
  - Web SPA disajikan langsung pada `http://localhost:8000/` (dan `/portal/`), Streamlit pada `http://localhost:8501`, dan OpenAPI metadata pada `/openapi.json` tanpa mengekspos `vercel.json` (404).

---

## Slide 7: Evaluation Results, Test Suite, and Failure Analysis
- **Deterministic & Live Test Suite (Container & Clean-Env Verified):**
  - **45/45 item test deterministik lulus** (1 deselected in 2.19s, berjalan tanpa `.env` maupun database eksternal).
  - **1/1 live test lulus** (`tests/test_live_api.py::test_live_policy_question` dengan `-m live` in 6.22s).
- **Hasil Evaluasi Live 15 Skenario (`src/run_evaluation.py` → `outputs/evaluation_report.json`):**
  - **Overall Pass Rate:** $100\%$ (`15/15` lulus) · **Hard Gates:** $100\%$ (`6/6` terpenuhi, termasuk `leave-valid-008` `action_proposed` + `requires_confirmation: true`).
  - **No System Approved Requests:** $100\%$ (True, zero unconfirmed/approved leave requests in DB).
  - **Retrieval Recall@3:** $1.0$ (dari `trace.retrieved_document_ids[:3]`) · **Citation Validity:** $1.0$ (terhadap `trace.retrieved_document_ids`) · **Tool Selection Accuracy:** $1.0$.
  - **Latency p50 / p95:** $2930.08\text{ ms} / 4289.9\text{ ms}$ (jauh di bawah batas SLA $< 8000\text{ ms}$).
  - **Release Decision:** **`release`** (`evaluated_at: 2026-11-20T02:57:59.317813+00:00`).

---

## Slide 8: Monitoring & Privacy Evidence
- **Observabilitas Real-Time (`/api/v1/monitoring/summary`, `/rules`, `/alerts`):**
  - Metrik live evaluator: `p50 = 2930.08 ms`, `p95 = 4289.9 ms` ($< 8000\text{ ms}$), total `53,661` input tokens dan `1,496` output tokens (`estimated_cost = $0.006114`).
  - Aturan alert `agent-error-spike` (`error_rate > 0.20`) dan `agent-latency-p95` (`p95_latency_ms > 8000`) di-seed dari `data/monitoring_rules.json` ke tabel `monitoring_rules`.
- **Privacy & Redaction Controls:**
  - `_BASELINE_MEDICAL_TERMS` (36 istilah ID+EN) + tabel `medical_terms` (cooldown 60s) menjaga redaksi bekerja offline maupun online, dengan negative lookbehind melindungi frasa legal `"cuti sakit"`, `"rumah sakit"`, dan `"surat keterangan sakit"`.
  - `redact_trace` bekerja rekursif pada `ActionProposal` dan nested payload; Opik menerima telemetri strictly metadata-only (`message_length`, `history_turns`, `role`, `employee_hash`, `answer_length`, `citations`, `outcome`, `usage`).

---

## Slide 9: Governance Controls and Residual Risks
- **Governance Controls (`risk-register.csv`):**
  - Memetakan 11 risiko inti (`R-001`..`R-011`) lengkap dengan owner dan bukti test otomatis: mayoritas berstatus `Mitigated`, sedangkan celah enterprise (`R-005` ontologi ICD-10 dan `R-010` kalender libur nasional SKB 3 Menteri) dicatat jujur sebagai `Partially Mitigated`.
- **Residual Risks & Batasan Sistem:**
  - *Kalender Libur Nasional:* Baru mengecualikan akhir pekan (Sabtu–Minggu), belum terhubung ke API SKB 3 Menteri.
  - *Kamus Medis Statis/Regex:* Belum terintegrasi ke ontologi medis terenkripsi ICD-10 / SNOMED-CT.
  - *Auth & HRIS Approval:* Menggunakan sesi token password lokal (`auth_sessions`) dan antrean baca-saja (`pending_manager_review`) sebelum integrasi OIDC dan webhook HRIS eksternal.

---

## Slide 10: Demo, Limitations, and Next Steps
- **Live Demo Flow (5–7 Menit):**
  1. Login Web SPA (password via `/auth/login`) & Policy Q&A dengan sitasi terverifikasi `[HR-LEAVE-001]`.
  2. Cek saldo pribadi (Alya `8 hari` tahunan) & blokir percobaan akses lintas pegawai (`EMP-002`).
  3. Pengajuan cuti tahunan/sakit: upload lampiran pra-konfirmasi → konfirmasi 2 fase → `pending_manager_review` → *idempotent replay*.
  4. Abstain tanpa tiket yatim + redaksi medis offline-safe (`diabetes`, `darah tinggi`) + pemblokiran lampiran medis pada `monitoring_admin`.
  5. Monitoring admin: overview agregat anonim tanpa PII pegawai (`low_balance_employees=[]`).
- **Next Steps:**
  - Integrasi API Kalender Libur Nasional (SKB 3 Menteri).
  - Integrasi OIDC/OAuth2 perusahaan serta webhook persetujuan manajer dua arah pada sistem HRIS.
  - Pemetaan ontologi medis terenkripsi (ICD-10 / SNOMED-CT) untuk kepatuhan penuh UU PDP.
