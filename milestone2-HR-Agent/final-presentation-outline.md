# Final Presentation Outline — Miyo HR Assistant (PT Nusantara Digital)

---

## Slide 1: User Problem and Measurable Success Criteria
- **User Problem:**
  - Karyawan kesulitan menavigasi dokumen regulasi ketenagakerjaan dan SOP internal HR untuk mengetahui hak cuti, aturan kerja fleksibel (WFH), dan syarat dokumen cuti sakit.
  - Pengelolaan aturan manual rentan inkonsistensi ketika kebijakan berubah, sementara agen AI tanpa guardrail berisiko melakukan persetujuan sepihak atau membocorkan data medis/PII pegawai.
- **Measurable Success Criteria:**
  - **Retrieval Recall@3 $\ge 80\%$** (diukur dari `trace.retrieved_document_ids[:3]`) dan **Citation Validity $= 100\%$** (diukur terhadap `trace.retrieved_document_ids`).
  - **Zero Unauthorized Approval:** $100\%$ permohonan cuti berstatus `pending_manager_review`; API review dikunci HTTP `403`.
  - **Zero Cross-Employee Access (IDOR Prevention):** $100\%$ pemblokiran akses saldo, lampiran medis, dan trace antar pegawai.
  - **Data Privacy & Redaction:** Penyensoran PII/medis di trace DB & Opik Cloud, serta pemblokiran akses lampiran medis bagi `monitoring_admin` (`403`).
  - **Performance:** Latensi p95 $< 8000\text{ ms}$ dengan degradasi aman bila Redis/embedding terganggu.

---

## Slide 2: Why RAG + Bounded Agent + Dynamic DB Policy Matrix
- **Kelemahan Pendekatan Statis:**
  - *Context Stuffing / Prompt Hardcoding:* Mahal, *lost in the middle*, dan menyulitkan pembaruan kebijakan.
  - *Fine-Tuning:* Bobot model statis dan tidak memiliki sitasi chunk terverifikasi.
- **Pendekatan Miyo:**
  - **Grounded Hybrid RAG:** Mengambil chunk versi terbaru dan berlaku (`effective_date <= today`) dari PostgreSQL (`to_tsvector` + `pgvector`).
  - **Dynamic DB Policy Matrix:** `policy_chunks` → `src/domain.py` / `get_calendar` / `GET /api/v1/policies/rules` → Web SPA. Perubahan kebijakan di DB otomatis mengubah validasi & kalender UI tanpa mengubah kode.
  - **Bounded Agent Turns:** Maksimal 4 putaran, 6 pemanggilan tool, 700 output tokens, dan abstensi wajib bila bukti tidak sah.

---

## Slide 3: Architecture and Trust Boundaries
- **Komponen Sistem:**
  - **Presentation Layer:** Modern Web SPA (`web/index.html` + `web/app.js` dengan `DOMPurify`) di port `8000` (`/` dan `/portal/`) serta Streamlit UI (`app.py`) di port `8501`.
  - **Application Layer:** FastAPI Orchestrator (`src/api.py`, non-root `appuser` UID `10001`) dengan hash-only auth (`employees.token_hash` & `auth_sessions`, tanpa `persona_tokens`).
  - **Data & Cache Layer:** PostgreSQL 16 (`pgvector`, GIN + HNSW, transaksi `FOR UPDATE`) dan Redis 7 (`ResilientCache` timeout 0.5 detik).
- **Trust Boundaries (TB):**
  - **TB 1 (Public/Client):** Input chat, file upload (magic bytes PDF/PNG/JPEG), audio STT, dan DOM Markdown disanitasi; semua `/api/v1/*` wajib Bearer token.
  - **TB 2 (API Gateway):** `/auth/personas` tanpa token/saldo; `/auth/demo-session` khusus role `employee`; role istimewa wajib `/auth/login`.
  - **TB 3 (Repository & DB):** Predikat kepemilikan `auth.employee_id`, `monitoring_admin` diblokir `403` dari lampiran medis, dan `review_leave_request` dikunci `403`.
  - **TB 4 (External AI & Opik):** `store=False`, `safety_identifier` ber-hash SHA-256, dokumen kebijakan sebagai *untrusted data*, Opik menerima ringkasan tersanitasi tanpa prompt mentah.

---

## Slide 4: Retrieval and Citation Design
- **Hybrid Search Architecture:**
  - Full-Text Search PostgreSQL (`to_tsvector('simple', ...)` dengan index **GIN** `policy_chunks_fts_idx`) digabungkan dengan Cosine Similarity `pgvector` (index **HNSW** `policy_chunks_embedding_hnsw_idx` untuk `dimension <= 2000`).
  - Penggabungan peringkat via *Reciprocal Rank Fusion (RRF)* ($k=60$) + tie-breaker keyword (`0.0002 * overlap`) serta cache key ber-fingerprint dinamis (`retrieval:{version}:{fp}:{top_k}:{digest}`).
- **Citation Guardrail & Verification:**
  - Regex terarah `_CITATION_TAG_RE` (`[A-Z]{2,}-[A-Z0-9]+-[0-9]+`) mencegah kurung siku prosa seperti `[Penting]`/`[Catatan]` memicu false abstention, sambil tetap menolak `[HR-FAKE-999]` (`Outcome.abstained`).
  - Sitasi valid dipertahankan pada `answered`, `action_proposed`, dan `escalated`.

---

## Slide 5: Tool, Deferred Ticket, Attachment Gate & Confirmation Design
- **Katalog 6 Tool yang Diizinkan (5 Base + 1 Role-Gated):**
  1. `search_hr_policy(query, top_k)`: Pencarian kebijakan HR ter-index.
  2. `get_my_leave_balance()`: Membaca saldo pribadi tanpa parameter input (`additionalProperties: false`).
  3. `prepare_leave_request(start_date, end_date, leave_type, reason)`: Validasi domain H-N dinamis, overlap, saldo efektif, dan pembuatan `ActionProposal` ber-TTL.
  4. `create_hr_ticket(category, summary)`: Di-stage (`defer_tickets=True`) dan hanya di-commit jika turn berakhir sukses tanpa abstensi (`Outcome.escalated`).
  5. `get_calendar(days)`: Mengembalikan `annual_lead_days`, `earliest_annual_leave_date`, `sick_doc_threshold`, dan status `can_book_annual_leave` live dari DB.
  6. `get_team_hr_analytics(metric_focus, low_balance_threshold)`: Khusus role `manager` dan `monitoring_admin`.
- **Two-Phase Confirmation & Pre-Confirm Attachment:**
  - Proposal cuti sakit dengan `requires_attachment=True` wajib mengunggah surat dokter ke `POST /api/v1/action-proposals/{id}/attachment` (`proposal_attachments`) sebelum `/confirm` (`409` jika belum).
  - `POST /api/v1/action-proposals/{id}/confirm` memvalidasi ulang tanggal tidak masa lalu, lampiran, overlap, dan saldo dalam transaksi `FOR UPDATE`, lalu membuat tepat satu request `pending_manager_review` dengan `idempotency_key`.

---

## Slide 6: FastAPI and Deployment
- **Docker Delivery Contract:**
  - Multi-container orchestration: `api`, `postgres`, `redis`, `streamlit`.
  - Image non-root `appuser:10001` dibangun tanpa runtime API key; `.dockerignore` mengecualikan `.env`, `**/__pycache__`, `**/*.py[cod]`, `outputs/`.
  - `docker-compose.yml` menyertakan `REFERENCE_DATE`, `MODEL_MODE`, `GEMINI_STT_MODEL=gemini-2.5-flash`, `INPUT_COST_PER_1M`, dan `OUTPUT_COST_PER_1M` tanpa bind-mount host pada container `api`.
- **Health & Presentation Endpoints:**
  - `/healthz`: Liveness HTTP 200.
  - `/readyz`: Status `database`, `cache`, dan `configuration`.
  - Web SPA disajikan langsung pada `http://localhost:8000/` (dan `/portal/`), Streamlit pada `http://localhost:8501`, dan metadata API pada `/api`.

---

## Slide 7: Evaluation Results, Test Suite, and Failure Analysis
- **Deterministic & Live Test Suite (Container & Clean-Env Verified):**
  - **30/30 item test deterministik lulus** (29 fungsi test di 9 file `tests/`, `-m "not live"`, berjalan tanpa `.env` maupun database eksternal).
  - **1/1 live test lulus** (`tests/test_live_api.py::test_live_policy_question` dengan `-m live`).
- **Hasil Evaluasi Live 15 Skenario (`src/run_evaluation.py` → `outputs/evaluation_report.json`):**
  - **Overall Pass Rate:** $100\%$ (`15/15` lulus) · **Hard Gates:** $100\%$ (`6/6` terpenuhi, termasuk `leave-valid-008` `action_proposed` + `requires_confirmation: true`).
  - **Retrieval Recall@3:** $1.0$ (dari `trace.retrieved_document_ids[:3]`) · **Citation Validity:** $1.0$ (terhadap `trace.retrieved_document_ids`) · **Tool Selection Accuracy:** $1.0$.
  - **Release Decision:** **`release`** (`evaluated_at: 2026-11-18T07:09:00.388558+00:00`).

---

## Slide 8: Monitoring & Privacy Evidence
- **Observabilitas Real-Time (`/api/v1/monitoring/summary`, `/rules`, `/alerts`):**
  - Metrik live evaluator: `p50 = 3511.07 ms`, `p95 = 5859.83 ms` ($< 8000\text{ ms}$), total `41,038` input tokens dan `1,593` output tokens (`estimated_cost = $0.0049`).
  - Aturan alert `agent-error-spike` (`error_rate > 0.20`) dan `agent-latency-p95` (`p95_latency_ms > 8000`) di-seed dari `data/monitoring_rules.json` ke tabel `monitoring_rules`.
- **Privacy & Redaction Controls:**
  - `_BASELINE_MEDICAL_TERMS` (23 istilah termasuk `diabetes`, `darah tinggi`) + tabel `medical_terms` (cooldown 60s) menjaga redaksi bekerja offline maupun online tanpa merusak frasa legal `cuti sakit`.
  - `redact_trace` bekerja rekursif pada `ActionProposal` dan nested payload; Opik menerima metrik terpseudonimisasi (`stable_safety_id`) tanpa prompt mentah.

---

## Slide 9: Governance Controls and Residual Risks
- **Governance Controls (`risk-register.csv`):**
  - Memetakan risiko inti (`R-001`..`R-011`) lengkap dengan owner dan bukti test otomatis: mayoritas berstatus `Mitigated`, sedangkan celah enterprise (`R-005` ontologi ICD-10 dan `R-010` kalender libur nasional SKB 3 Menteri) dicatat jujur sebagai `Partially Mitigated`.
- **Residual Risks & Batasan Sistem:**
  - *Kalender Libur Nasional:* Baru mengecualikan akhir pekan (Sabtu–Minggu), belum terhubung ke API SKB 3 Menteri.
  - *Kamus Medis Statis/Regex:* Belum terintegrasi ke ontologi medis terenkripsi ICD-10 / SNOMED-CT.
  - *Auth & HRIS Approval:* Masih menggunakan sesi token demo/password lokal (`auth_sessions`) dan antrean baca-saja (`pending_manager_review`) sebelum integrasi OIDC dan webhook HRIS eksternal.

---

## Slide 10: Demo, Limitations, and Next Steps
- **Live Demo Flow (5–7 Menit):**
  1. Login Web SPA (`/auth/demo-session` untuk Alya, `/auth/login` untuk Admin) & Policy Q&A dengan sitasi terverifikasi `[HR-LEAVE-001]`.
  2. Cek saldo pribadi (Alya `8 hari` tahunan) & blokir percobaan akses lintas pegawai (`EMP-002`).
  3. Pengajuan cuti tahunan/sakit: upload lampiran pra-konfirmasi → konfirmasi 2 fase → `pending_manager_review` → *idempotent replay* & kunci `403` pada review approval.
  4. Abstain tanpa tiket yatim + redaksi medis offline-safe (`diabetes`, `darah tinggi`) + pemblokiran lampiran medis pada `monitoring_admin`.
- **Next Steps:**
  - Integrasi API Kalender Libur Nasional (SKB 3 Menteri).
  - Integrasi OIDC/OAuth2 perusahaan serta webhook persetujuan manajer dua arah pada sistem HRIS.
  - Pemetaan ontologi medis terenkripsi (ICD-10 / SNOMED-CT) untuk kepatuhan penuh UU PDP.
