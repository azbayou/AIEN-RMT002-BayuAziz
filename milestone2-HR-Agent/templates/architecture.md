# Architecture Submission — Milestone 2

Dokumen arsitektur utama tersedia lengkap pada [architecture.md](../architecture.md). Ringkasan inti keputusan arsitektur (*Architecture Decision Records*) untuk Milestone 2 **Miyo HR Assistant**:

## System Overview

- **Presentation Layer:** Modern Web SPA (`web/index.html`, `web/app.js` dengan sanitasi `DOMPurify`, disajikan di `/` dan `/portal/` port `8000`) serta Streamlit UI (`app.py`, port `8501`).
- **Application Layer:** FastAPI Orchestrator (`src/api.py`, non-root `appuser` UID 10001) dengan autentikasi hash SHA-256 (`employees.token_hash` & `auth_sessions`), **Dynamic DB Policy Matrix** (`GET /api/v1/policies/rules`), `AgentService` berbatas turn/tool (maks 4 turn, 6 tool call, 700 output token), 6 strict tools, dan evaluator API-driven (`src/run_evaluation.py`).
- **Data & Cache Layer:** PostgreSQL 16 + `pgvector` (index GIN `to_tsvector` + HNSW cosine, tabel `proposal_attachments`, `leave_attachments`, `evaluation_cases`, `auth_sessions`, `traces`) serta Redis 7 dengan `ResilientCache` (timeout 0.5s, degradasi ke cache miss).

## Architecture Decision Records (ADR)

### 1. Grounded Hybrid RAG (FTS GIN + pgvector HNSW + RRF) + Dynamic DB Policy Matrix
- **Decision:** Menggabungkan PostgreSQL `to_tsvector('simple', ...)` (GIN) dan `pgvector` cosine similarity (HNSW) via Reciprocal Rank Fusion ($k=60$, tie-breaker `0.0002 * overlap`) dengan filter `effective_date <= active_today` dan versi terbaru per `document_id`. Aturan lead time tahunan (`HR-LEAVE-001`) dan ambang surat dokter (`HR-LEAVE-002`) diekstrak secara dinamis dari `policy_chunks` melalui `src/domain.py` dan `GET /api/v1/policies/rules`.
- **Context:** Pertanyaan kebijakan membutuhkan pencocokan kode dokumen eksak dan makna semantik, sementara aturan cuti di UI/backend harus langsung berubah bila isi database `policy_chunks` diperbarui tanpa mengubah kode atau prompt.
- **Alternatives considered:** Context stuffing seluruh kebijakan ke prompt sistem; fine-tuning LLM; vector-only search tanpa lexical FTS.
- **Trade-offs:** Memerlukan perawatan index GIN/HNSW serta pola kalimat Bahasa Indonesia yang konsisten untuk parser angka dinamis, namun menghilangkan halusinasi dan inkonsistensi kebijakan.
- **Production follow-up:** Skema aturan terstruktur berdampingan dengan dokumen Markdown dan kamus stemming Bahasa Indonesia.

### 2. Bounded Agent, Pending-Only Actions & Pre-Confirmation Attachment Gate
- **Decision:** Membatasi eksekusi agent dengan 6 strict tools (`additionalProperties: false`), menunda penulisan `create_hr_ticket` (`defer_tickets=True`) hingga turn selesai tanpa abstensi (`Outcome.escalated`), mewajibkan upload lampiran medis ke `proposal_attachments` sebelum `/confirm` untuk cuti sakit di atas ambang kebijakan (`409` jika belum ada), dan mengunci `POST /api/v1/manager/leave-requests/{id}/review` ke HTTP `403`.
- **Context:** LLM dan API tidak boleh menyetujui cuti (`approved`), meninggalkan tiket yatim saat turn abstain, atau membuat pengajuan cuti sakit panjang tanpa dokumen pendukung.
- **Alternatives considered:** Eksekusi mutasi langsung di tool tanpa konfirmasi; upload lampiran pasca-konfirmasi; endpoint approval di dalam backend AI.
- **Trade-offs:** Membutuhkan alur 2 fase (plus upload pra-konfirmasi pada cuti sakit panjang), tetapi menjamin 100% kepatuhan Hard Gate pending-only dan idempotency.
- **Production follow-up:** Integrasi webhook satu arah ke sistem HRIS eksternal tempat manajer manusia meninjau antrean `pending_manager_review`.

### 3. Hash-Only Auth Sessions & Offline-Safe Recursive PII Redaction
- **Decision:** Menghapus tabel `persona_tokens`, menyimpan token sesi hanya dalam bentuk hash SHA-256 di `auth_sessions`, melindungi seluruh `/api/v1/*` dengan `Depends(current_auth)`, memblokir `monitoring_admin` dari mengunduh lampiran medis (`403`), menyediakan 23 `_BASELINE_MEDICAL_TERMS` in-memory + DB `medical_terms` (cooldown 60s), dan menjalankan `redact_trace` rekursif + ringkasan Opik tanpa prompt mentah.
- **Context:** Kredensial demo tidak boleh tersimpan dalam plaintext, dan telemetry/trace harus aman dari kebocoran PII/medis baik saat PostgreSQL aktif maupun dalam mode unit test offline.
- **Alternatives considered:** Redaksi hanya berbasis query DB tanpa baseline offline; mengekspos token demo pada endpoint publik.
- **Trade-offs:** Akun `monitoring_admin` wajib login password lewat `/auth/login`, namun mencegah eskalasi hak akses dan kebocoran data sensitif.
- **Production follow-up:** Integrasi OIDC/OAuth2 enterprise dan pemetaan ontologi medis ICD-10 / SNOMED-CT.
