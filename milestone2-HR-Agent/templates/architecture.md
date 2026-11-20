# Architecture Submission — Milestone 2

Dokumen arsitektur utama tersedia lengkap pada [architecture.md](../architecture.md). Ringkasan inti keputusan arsitektur (*Architecture Decision Records*) untuk Milestone 2 **Miyo HR Assistant**:

## System Overview

- **Presentation Layer:** Modern Web SPA (`web/index.html`, `web/app.js` dengan sanitasi `DOMPurify`, disajikan di `/` dan `/portal/` port `8000`) serta Streamlit UI (`app.py`, port `8501`).
- **Application Layer:** FastAPI Orchestrator (`src/api.py`, non-root `appuser` UID 10001) dengan autentikasi hash SHA-256 (`employees.token_hash` & `auth_sessions`), **Dynamic DB Policy Matrix** (`GET /api/v1/policies/rules`), `AgentService` berbatas turn/tool (maks 4 turn, 6 tool call, 700 output token, deadline total 30 detik), 6 strict tools (5 base employee + 1 role-gated admin analytics), dan evaluator API-driven (`src/run_evaluation.py`).
- **Data & Cache Layer:** PostgreSQL 16 + `pgvector` (index GIN `to_tsvector` + HNSW cosine, tabel `proposal_attachments`, `leave_attachments`, `evaluation_cases`, `auth_sessions`, `traces`) serta Redis 7 dengan `ResilientCache` (timeout 0.5s, degradasi ke cache miss).

## Architecture Decision Records (ADR)

### ADR-001: Grounded Hybrid RAG (FTS GIN + pgvector HNSW + RRF) + Dynamic DB Policy Matrix
- **Decision:** Menggabungkan PostgreSQL `to_tsvector('simple', ...)` (GIN) dan `pgvector` cosine similarity (HNSW) via Reciprocal Rank Fusion ($k=60$, tie-breaker `0.0002 * overlap`) dengan filter `effective_date <= active_today` dan versi terbaru per `document_id`. Aturan lead time tahunan (`HR-LEAVE-001`) dan ambang surat dokter (`HR-LEAVE-002`) diekstrak secara dinamis dari `policy_chunks` melalui `src/domain.py` dan `GET /api/v1/policies/rules`.
- **Context:** Pertanyaan kebijakan membutuhkan pencocokan kode dokumen eksak dan makna semantik, sementara aturan cuti di UI/backend harus langsung berubah bila isi database `policy_chunks` diperbarui tanpa mengubah kode atau prompt.
- **Alternatives considered:** Context stuffing seluruh kebijakan ke prompt sistem; fine-tuning LLM; vector-only search tanpa lexical FTS.
- **Trade-offs:** Memerlukan perawatan index GIN/HNSW serta pola kalimat Bahasa Indonesia yang konsisten untuk parser angka dinamis, namun menghilangkan halusinasi dan inkonsistensi kebijakan.
- **Production follow-up:** Skema aturan terstruktur berdampingan dengan dokumen Markdown dan kamus stemming Bahasa Indonesia.

### ADR-002: Bounded Agent, Pending-Only Actions & Conditional Pre-Confirmation Attachment Gate
- **Decision:** Membatasi eksekusi agent dengan 6 strict tools (`additionalProperties: false`), menunda penulisan `create_hr_ticket` (`defer_tickets=True`) dan `prepare_leave_request` (`defer_proposals=True`) hingga turn selesai tanpa abstensi (`Outcome.escalated`), mewajibkan upload lampiran medis ke `proposal_attachments` sebelum `/confirm` untuk cuti sakit di atas ambang batas kebijakan saat header `X-Enforce-Sick-Attachment: true` dikirim oleh Web SPA (HTTP `409` jika belum ada lampiran, tetap kompatibel penuh tanpa 409 pada starter Streamlit `app.py`), mengeliminasi role `manager` dan seluruh rute `/api/v1/manager/leave-requests*`, serta mengunci seluruh status pengajuan pada `pending_manager_review`.
- **Context:** LLM dan API dilarang keras menyetujui cuti (`approved`), meninggalkan tiket/proposal yatim saat turn abstain, atau membuat pengajuan cuti sakit panjang tanpa dokumen pendukung.
- **Alternatives considered:** Eksekusi mutasi langsung di tool tanpa konfirmasi; upload lampiran pasca-konfirmasi; endpoint approval di dalam backend AI.
- **Trade-offs:** Membutuhkan alur 2 fase (plus upload pra-konfirmasi pada cuti sakit panjang di Web SPA), tetapi menjamin 100% kepatuhan Hard Gate pending-only dan idempotency.
- **Production follow-up:** Integrasi webhook satu arah ke sistem HRIS eksternal tempat manajer manusia meninjau antrean `pending_manager_review`.

### ADR-003: Hash-Only Auth Sessions & Zero-Trust Privacy Redaction
- **Decision:** Menghapus tabel `persona_tokens`, menyimpan token sesi hanya dalam bentuk hash SHA-256 di `auth_sessions`, menonaktifkan `POST /auth/demo-session` secara default (`ALLOW_DEMO_SESSION=false`), membatasi analitik `monitoring_admin` hanya pada agregat anonim (`low_balance_employees=[]`, `low_balance_employee_count`), melindungi seluruh `/api/v1/*` dengan `Depends(current_auth)`, memblokir `monitoring_admin` dari mengunduh lampiran medis (`403`), menyediakan 36 `_BASELINE_MEDICAL_TERMS` in-memory + DB `medical_terms` (cooldown 60s), dan menjalankan `redact_trace` rekursif + telemetri Opik strictly metadata-only tanpa prompt mentah.
- **Context:** Kredensial demo tidak boleh tersimpan dalam plaintext, akun demo tidak boleh membuka celah impersonasi tanpa password, dan telemetry/trace harus aman dari kebocoran PII/medis baik saat PostgreSQL aktif maupun dalam mode unit test offline.
- **Alternatives considered:** Redaksi hanya berbasis query DB tanpa baseline offline; mengizinkan login instan demo session publik di production.
- **Trade-offs:** Akun wajib login password lewat `POST /auth/login` (atau Bearer token ter-hash), namun mencegah eskalasi hak akses dan kebocoran data sensitif.
- **Production follow-up:** Integrasi OIDC/OAuth2 enterprise dan pemetaan ontologi medis ICD-10 / SNOMED-CT.

### ADR-004: Dynamic DB Policy Matrix (`policy_chunks` → Domain/Calendar/API → SPA)
- **Decision:** Memusatkan sumber aturan pada tabel `policy_chunks`. Fungsi `get_policy_document_text`, `policy_fingerprint`, `get_annual_leave_lead_days`, `get_sick_leave_doc_threshold`, dan `count_lead_business_days` mengekstrak aturan secara dinamis untuk validasi tool, hasil `get_calendar`, endpoint `GET /api/v1/policies/rules`, dan sinkronisasi UI Web SPA.
- **Context:** Menanam angka kebijakan (seperti H-3 atau `>2 hari`) di prompt atau kode Python menyebabkan inkonsistensi ketika HR memperbarui dokumen kebijakan.
- **Alternatives considered:** Hardcoding konstanta pada `SYSTEM_INSTRUCTIONS` dan frontend JS.
- **Trade-offs:** Format redaksi angka/kalimat pada kebijakan baru perlu mengikuti pola Bahasa Indonesia standar yang didukung parser `_parse_policy_number`.
- **Production follow-up:** Menyimpan metadata aturan terstruktur (*structured policy schema*) di samping teks Markdown saat ingestion HR.

### ADR-005: Deferred Side Effects (Tickets & Proposals) & Resilient Cache Degradation
- **Decision:** Menunda penulisan `create_hr_ticket` (`defer_tickets=True`) dan `prepare_leave_request` (`defer_proposals=True`) hingga seluruh loop agent selesai tanpa status `abstained` (dan `save_trace` sukses), membungkus `save_trace` dalam `try/except` dengan degradasi aman ke `Outcome.abstained` (HTTP 200, nol side effect), serta membungkus Redis dalam `ResilientCache` ber-timeout 0.5 detik.
- **Context:** Pembuatan tiket maupun `action_proposals` di tengah turn berisiko meninggalkan record yatim jika turn berikutnya gagal atau abstain, sementara kegagalan Redis tidak boleh melumpuhkan layanan chat.
- **Alternatives considered:** Menulis tiket/proposal segera saat pemanggilan tool; fail-fast jika Redis mati.
- **Trade-offs:** Memerlukan staging state selama satu siklus `AgentService.run()`, namun menjamin *zero side effects on abstention* serta ketahanan penuh terhadap gangguan DB/Redis.
- **Production follow-up:** Redis Sentinel/Cluster HA serta *circuit breaker* cooldown untuk Redis outage berkepanjangan.

### ADR-006: Grounded RAG vs Context Stuffing & Fine-Tuning
- **Context:** Kebijakan HR (`HR-LEAVE-*`, `HR-WORK-*`, `HR-ELIG-*`, `HR-PRIV-*`, `HR-ESC-*`, `HR-OPS-*`) dapat berubah kapan saja (versi & `effective_date`), dan setiap jawaban wajib dapat ditelusuri ke `[DOCUMENT_ID]` resmi.
- **Decision:** Memilih Hybrid RAG (`policy_chunks` di PostgreSQL + `pgvector`) dan mengekstrak aturan operasional langsung dari database daripada menanam teks kebijakan ke prompt sistem (*context stuffing*) atau bobot model (*fine-tuning*).
- **Alternatives considered:**
  - *Context stuffing* seluruh Markdown kebijakan ke `SYSTEM_INSTRUCTIONS`: boros token di setiap request, rawan *lost in the middle*, dan menyulitkan audit sitasi per chunk.
  - *Fine-tuning* LLM pada teks kebijakan: mahal dilatih ulang saat kebijakan berubah, tetap bisa berhalusinasi angka/tanggal, dan tidak memiliki kontrol *effective_date* per versi.
- **Trade-offs:** Membutuhkan pipeline ingestion & indexing embedding, tetapi pembaruan kebijakan cukup me-seed ulang `policy_chunks` tanpa ubah kode/prompt dan otomatis menginvalidasi cache via `policy_fingerprint(as_of)`.
- **Production follow-up:** Penambahan *cross-encoder reranker* dan skema aturan terstruktur berdampingan dengan teks Markdown.

### ADR-007: Bounded Single-Agent vs Multi-Agent Architecture
- **Context:** Alur asisten mencakup Q&A kebijakan, cek saldo pribadi, kalender dinamis, pembuatan proposal cuti, tiket eskalasi, dan analitik agregat admin.
- **Decision:** Menggunakan satu *bounded agent loop* (`AgentService`, maks `4` turn, `6` tool call, `700` output tokens, deadline total `30` detik, `max_retries=0` pada OpenAI SDK + retry tunggal di `_call`, larangan eksekusi tool mutasi di turn terakhir) dibanding arsitektur *multi-agent*.
- **Alternatives considered:** Memisahkan agen khusus per domain (Policy Agent, Leave Agent, Security Supervisor Agent) dengan handoff antar-agent.
- **Trade-offs:** *Multi-agent* melipatgandakan latensi (p95 melampaui SLA `< 8000 ms`), konsumsi token/biaya, serta permukaan kebocoran state/konteks lintas trust boundary, sedangkan domain HR Nusantara Digital dapat ditangani deterministik oleh 1 agen ber-tool strict (`additionalProperties: false`) dan validasi domain di `src/domain.py`.
- **Production follow-up:** Evaluasi pemisahan worker asinkron hanya untuk tugas batch offline (retensi trace & evaluasi terjadwal), bukan pada jalur chat sinkron.
