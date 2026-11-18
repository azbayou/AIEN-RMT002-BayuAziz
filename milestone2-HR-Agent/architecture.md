# Architecture Assignment

---

## 1. Problem Framing, Personas, and Scope

### 1.1 Problem Framing
Karyawan sering menghadapi kesulitan menavigasi dokumen kebijakan HR untuk mengetahui hak cuti, aturan kerja jarak jauh (WFH), dan ketentuan izin sakit beserta dokumen pendukungnya. Di sisi lain, sistem AI yang langsung menyetujui cuti, menyimpan teks medis sensitif tanpa redaksi, atau membocorkan data antar pegawai menimbulkan risiko kepatuhan ketenagakerjaan dan privasi (UU PDP).

Sistem **Miyo HR Assistant** dirancang sebagai asisten kebijakan HR enterprise yang menggabungkan:
1. **Grounded Hybrid RAG** berbasis PostgreSQL (`to_tsvector` GIN + `pgvector` HNSW + RRF) dengan sitasi terverifikasi `[DOCUMENT_ID]` dan abstensi wajib bila bukti tidak valid.
2. **Dynamic DB Policy Matrix** di mana aturan lead time cuti tahunan (`HR-LEAVE-001`) dan ambang surat dokter cuti sakit (`HR-LEAVE-002`) dibaca langsung dari `policy_chunks` aktif di database sehingga perubahan kebijakan langsung memperbarui validasi domain, kalender, API `/api/v1/policies/rules`, dan UI SPA tanpa perubahan kode.
3. **Two-Phase Action Safety & Pending-Only Gate** di mana asisten hanya menyiapkan `ActionProposal` ber-TTL, mewajibkan upload lampiran medis pra-konfirmasi jika diperlukan, dan mengunci seluruh pengajuan pada status `pending_manager_review` tanpa kemampuan approval otomatis di API.
4. **Zero-Trust Identity Isolation & Recursive Redaction** berbasis hash token (`employees.token_hash` dan `auth_sessions`), redaksi offline-safe (`_BASELINE_MEDICAL_TERMS` + tabel `medical_terms`), dan sanitasi rekursif sebelum penyimpanan trace maupun pengiriman ke Opik.

### 1.2 User Personas
| Persona | Role | Identitas & Autentikasi | Saldo Awal (`employees.json`) | Wewenang & Batasan |
|---|---|---|---|---|
| **Alya Pratama** | `employee` | `EMP-001` (Demo SSO `POST /auth/demo-session` atau Bearer token ter-hash) | Annual `8 hari`, Sick `10 hari`, Parental `60 hari` | Membaca kebijakan HR, melihat saldo & request pribadi, mengajukan proposal & lampiran cuti sakit, membuat tiket HR, melihat trace pribadi. |
| **Bima Santoso** | `employee` | `EMP-002` (Demo SSO `POST /auth/demo-session` atau Bearer token ter-hash) | Annual `3 hari`, Sick `10 hari`, Parental `60 hari` | Akses mandiri atas data pribadi; terisolasi penuh dari saldo, proposal, lampiran, dan trace milik Alya. |
| **Monitoring Admin** | `monitoring_admin` | `ADM-001` (Wajib login password `POST /auth/login` pada UI; demo session diblokir `403`) | `-` | Mengakses `/api/v1/monitoring/summary|rules|alerts`, analitik agregat, tiket operasional, dan trace tersanitasi. Diblokir (`403`) dari lampiran medis pegawai dan approval cuti. |

### 1.3 Scope & Non-Scope
- **In Scope:**
  - Tanya jawab kebijakan HR berbahasa Indonesia dengan sitasi `[DOCUMENT_ID]` yang terverifikasi pada chunk retrieval aktif.
  - Pengecekan saldo cuti resmi milik pegawai aktif (`get_my_leave_balance` tanpa argumen identitas).
  - Perhitungan hari kerja (`business_days`, `count_lead_business_days`, `compute_earliest_annual_leave_date`) berdasarkan aturan lead time H-N dinamis dari `policy_chunks`.
  - Pembuatan `ActionProposal` ber-TTL (15 menit) tanpa menulis ke `leave_requests` sebelum konfirmasi.
  - Upload lampiran pra-konfirmasi (`POST /api/v1/action-proposals/{proposal_id}/attachment` ke `proposal_attachments`) sebelum konfirmasi cuti sakit melebihi ambang batas kebijakan.
  - Konfirmasi idempoten (`POST /api/v1/action-proposals/{proposal_id}/confirm`) yang membuat satu row `leave_requests` berstatus `pending_manager_review` dan memigrasikan lampiran ke `leave_attachments`.
  - Pembuatan tiket HR (`create_hr_ticket`) yang ditunda selama turn agent dan hanya di-commit bila turn berakhir sukses tanpa abstensi (`Outcome.escalated`).
  - Redaksi otomatis PII (email, nomor HP, token/API key/JWT/DSN, istilah medis) serta graceful degradation saat Redis atau Embedding provider terganggu.
- **Out of Scope (Non-Negotiable Constraints):**
  - API dan AI dilarang menyetujui (`approved`) permohonan cuti; endpoint `/api/v1/manager/leave-requests/{id}/review` dikunci HTTP `403`.
  - AI dan pegawai dilarang membaca saldo, request, lampiran, atau trace milik pegawai lain.
  - `monitoring_admin` dilarang mengunduh lampiran medis pegawai (`GET /api/v1/leave-requests/{id}/attachment` mengembalikan `403`).
  - Sistem dilarang menyimpan plaintext API key, password, demo token (`persona_tokens` dihapus), prompt mentah, atau chain-of-thought di DB maupun Opik.

---

## 2. End-to-End System Architecture

```mermaid
flowchart TD
    subgraph ClientLayer["Client & Presentation Layer"]
        SPA["Modern Web SPA (FastAPI / & /portal/, DOMPurify)"]
        ST["Streamlit UI (Port 8501)"]
        CLI["Evaluator CLI (src.run_evaluation)"]
    end

    subgraph APILayer["Application & API Layer (FastAPI Port 8000, Non-Root UID 10001)"]
        AUTH["Hash Auth & Session Gateway (/auth/* -> employees + auth_sessions)"]
        API["FastAPI Orchestrator (/api/v1/* Protected Routes)"]
        SEC["Security & Recursive Redactor (Offline Baseline + DB medical_terms)"]
        AGENT["AgentService (Miyo, Deferred Tickets, Strict Citations)"]
        TOOLS["Strict Tool Executor (5 Base + 1 Role-Gated Analytics Tool)"]
        RET["RetrievalService (Hybrid RRF + Fingerprint Cache Key)"]
        DOM["Dynamic Domain Engine (policy_chunks -> Rules & Calendar)"]
    end

    subgraph DataLayer["Storage & Cache Infrastructure"]
        PG[("PostgreSQL 16 + pgvector (GIN FTS + HNSW Vector, Port 5432)")]
        REDIS[("Redis 7 Cache (0.5s Timeout, Port 6379)")]
    end

    subgraph ExternalServices["External AI & Observability Enclaves"]
        OPENAI["OpenAI API (Responses store=False + Embeddings)"]
        GEMINI["Gemini STT API (x-goog-api-key header)"]
        OPIK["Opik Cloud Telemetry (Pseudonymized & Redacted Metadata)"]
    end

    SPA -->|"Auth Bootstrap /auth/* & Bearer /api/v1/*"| AUTH
    ST -->|"Bearer Token /api/v1/*"| AUTH
    CLI -->|"GET /evaluation/cases, POST /chat, GET /traces/{id}"| AUTH
    AUTH -->|"Validated AuthContext"| API
    API -->|"Rules & Validation"| DOM
    API -->|"Chat Turn"| AGENT
    API -->|"Audio STT"| GEMINI
    AGENT -->|"Redact Trace & Outputs"| SEC
    AGENT -->|"Bounded Turns & Tool Calls"| TOOLS
    TOOLS -->|"search_hr_policy"| RET
    TOOLS -->|"Live Policy Rules & Leave Ops"| DOM
    TOOLS -->|"Balances / Proposals / Deferred Tickets"| PG
    RET -->|"Cache Check / Set (Fingerprint Key)"| REDIS
    RET -->|"FTS (GIN) + Vector (HNSW)"| PG
    RET -->|"Query Embedding"| OPENAI
    AGENT -->|"Responses API (store=False)"| OPENAI
    API -->|"Save Redacted Trace"| PG
    AGENT -->|"Telemetry Summary (No Raw Prompts)"| OPIK
```

---

## 3. Trust Boundaries & Security Enclaves

```mermaid
flowchart TD
    subgraph TB0["Trust Boundary 0: Public & Client Zone"]
        USER["Browser SPA (DOMPurify XSS Guard) / Streamlit / CLI"]
    end

    subgraph TB1["Trust Boundary 1: Authentication & Session Gateway"]
        direction TB
        BOOTSTRAP["/auth/personas (No Tokens/Balances), /auth/demo-session (Employee Only), /auth/login (PBKDF2)"]
        BEARER["Bearer Header Validation on ALL /api/v1/*"]
        HASH_AUTH["SHA-256 Lookup (employees.token_hash UNION auth_sessions.session_token_hash)"]
        CTX["Immutable AuthContext (employee_id, display_name, role, department, manager_id)"]
        BOOTSTRAP --> BEARER --> HASH_AUTH --> CTX
    end

    subgraph TB2["Trust Boundary 2: Application Execution Enclave"]
        direction TB
        INPUT_VAL["Pydantic Validation & Role Guards (manager_auth / admin_auth / 403 Review Lock)"]
        TOOL_GUARD["Identity Binding (AuthContext only, no employee_id arg on tools)"]
        REDACT_PIPE["Offline-Safe PII & Recursive ActionProposal Redactor (redact_trace)"]
        INPUT_VAL --> TOOL_GUARD --> REDACT_PIPE
    end

    subgraph TB3["Trust Boundary 3: Internal Data Enclave"]
        direction TB
        SQL_TX["Parameterized SQL + FOR UPDATE Locks + Pending-Only Confirmation"]
        ROW_ISOLATION["Owner Predicates & Attachment Privacy (monitoring_admin blocked 403)"]
        SQL_TX --> ROW_ISOLATION
    end

    subgraph TB4["Trust Boundary 4: External LLM & Telemetry Enclave"]
        direction TB
        EXT_LLM["OpenAI API (store=False, hashed safety_identifier, untrusted policy context)"]
        OPIK_OUT["Opik Telemetry (No raw prompt/history/CoT; PolicyChunk summarized & redacted)"]
        EXT_LLM --- OPIK_OUT
    end

    USER -->|"Untrusted HTTP Request"| TB1
    CTX -->|"Trusted Identity Context"| TB2
    REDACT_PIPE -->|"Sanitized Queries & Transactions"| TB3
    TOOL_GUARD -->|"Sanitized Tool Inputs"| TB4
```

### Trust Boundary Rules
1. **TB0 → TB1 (Public ke Gateway):** Seluruh input pengguna, file lampiran (magic bytes PDF/PNG/JPEG, maks 5 MB), dan audio dianggap *untrusted*. Markdown pada Web SPA disanitasi dengan `DOMPurify.sanitize(...)`. Seluruh rute `/api/v1/*` (termasuk `/api/v1/policies/rules` dan `/api/v1/evaluation/cases`) wajib menyertakan Bearer token yang valid; hanya hash SHA-256 yang disimpan pada `employees.token_hash` dan `auth_sessions.session_token_hash` (`persona_tokens` dihapus).
2. **TB1 → TB2 (Gateway ke Application):** `AuthContext` bersifat *immutable*. Tool `get_my_leave_balance` (`additionalProperties: false`) dan `prepare_leave_request` tidak pernah menerima parameter `employee_id` dari LLM. Endpoint `/api/v1/manager/leave-requests/{id}/review` dikunci HTTP `403` agar approval otomatis mustahil dilakukan melalui API.
3. **TB2 → TB3 (Application ke Storage):** Seluruh query SQL menggunakan parameter binding. Transaksi `/confirm` mengunci baris `employees` dan `leave_balances` dengan `FOR UPDATE`, memvalidasi tanggal tidak berada di masa lalu, memverifikasi `proposal_attachments` untuk cuti sakit berlampiran wajib, mengecek overlap (`pending_manager_review` & `approved`), memigrasikan lampiran ke `leave_attachments`, dan mengunci status baru pada `pending_manager_review`. Akses `GET /api/v1/leave-requests/{id}/attachment` memblokir `monitoring_admin` dengan `403`.
4. **TB2 → TB4 (Application ke External LLM/Opik):** Panggilan OpenAI menggunakan `store=False` dan `safety_identifier` ber-hash SHA-256. Dokumen kebijakan diperlakukan sebagai *untrusted data*. Sebelum dikirim ke Opik Cloud, `OpikTracker` menghapus `user_message`, `history`, dan array `messages` mentah, meringkas `PolicyChunk`, lalu menjalankan `redact_trace(...)` secara rekursif.

---

## 4. Hybrid RAG, Dynamic Policy Matrix & Citation Flow

```mermaid
sequenceDiagram
    autonumber
    actor Employee as Karyawan / SPA
    participant API as FastAPI (/api/v1/policies/rules & /chat)
    participant Agent as AgentService (Miyo)
    participant Tools as ToolExecutor & Domain
    participant Retrieval as RetrievalService
    participant Cache as ResilientCache (Redis)
    participant DB as PostgreSQL (GIN + pgvector HNSW)

    Employee->>API: GET /api/v1/policies/rules (Bearer token)
    API->>DB: get_policy_document_text("HR-LEAVE-001", "HR-LEAVE-002") [latest version, effective_date <= today]
    DB-->>API: Teks kebijakan aktif
    API->>Tools: Extract annual_lead_days, earliest_annual_start_date, sick_doc_threshold
    API-->>Employee: Dynamic Policy Rules JSON -> Sinkronkan UI Kalender & Form

    Employee->>API: POST /api/v1/chat ("Kapan paling cepat cuti tahunan?")
    API->>Agent: Run bounded turn
    Agent->>Tools: search_hr_policy(query, top_k=3) & get_calendar(days=14)
    Tools->>Retrieval: search(query, top_k=3)
    Retrieval->>DB: policy_fingerprint()
    Retrieval->>Cache: get("retrieval:{ver}:{fp}:{top_k}:{hash}")
    alt Cache Miss / Redis Down
        Retrieval->>DB: FTS to_tsvector/to_tsquery (GIN) + Vector <=> (HNSW) [latest version & effective_date <= today]
        DB-->>Retrieval: Candidate Chunks
        Retrieval->>Retrieval: RRF (k=60) + Tie-breaker (0.0002 * overlap)
        Retrieval->>Cache: set(key, ttl=900s)
    end
    Tools->>DB: get_calendar() reads live HR-LEAVE-001/002 -> annual_lead_days, earliest_annual_leave_date, can_book_annual_leave
    Tools-->>Agent: PolicyChunks + Live Calendar
    Agent->>Agent: Validasi sitasi _CITATION_TAG_RE ([A-Z]{2,}-[A-Z0-9]+-[0-9]+) <= retrieved_ids
    Agent-->>Employee: Jawaban ber-sitasi valid (prosa [Penting]/[Catatan] tidak memicu false abstain)
```

---

## 5. Two-Phase Action Safety, Attachment Gate & Idempotent Confirmation Flow

```mermaid
sequenceDiagram
    autonumber
    actor Employee as Karyawan
    participant API as FastAPI
    participant Tools as ToolExecutor
    participant DB as PostgreSQL
    participant HRIS as Portal HRIS (Manajer Manusia)

    Note over Employee,DB: Fase 1: Pembuatan Proposal (Tanpa menulis leave_requests)
    Employee->>API: POST /api/v1/chat ("Ajukan cuti sakit 3 hari kerja")
    API->>Tools: prepare_leave_request(start_date, end_date, "sick", reason)
    Tools->>DB: Baca HR-LEAVE-002 aktif -> threshold dinamis & validasi saldo/overlap/H-N
    Tools->>DB: INSERT action_proposals (TTL=15m, requires_attachment=True)
    Tools-->>API: ActionProposal (requires_confirmation=True)
    API-->>Employee: Outcome: action_proposed + Detail Proposal & Valid Citations

    Note over Employee,DB: Fase 1b: Upload Lampiran Wajib Pra-Konfirmasi (jika requires_attachment=True)
    opt Konfirmasi sebelum upload lampiran
        Employee->>API: POST /api/v1/action-proposals/{id}/confirm
        API-->>Employee: HTTP 409 Conflict ("dokumen pendukung surat dokter wajib diunggah sebelum konfirmasi")
    end
    Employee->>API: POST /api/v1/action-proposals/{id}/attachment (PDF/PNG/JPEG <= 5MB)
    API->>DB: Simpan ke proposal_attachments

    Note over Employee,DB: Fase 2: Konfirmasi Eksplisit & Idempotensi
    Employee->>API: POST /api/v1/action-proposals/{id}/confirm {idempotency_key}
    API->>DB: BEGIN TX (FOR UPDATE lock on employees & leave_balances)
    alt Valid, belum kadaluarsa, tanggal >= today, lampiran lengkap, tidak overlap
        DB->>DB: INSERT leave_requests (status='pending_manager_review')
        DB->>DB: Migrasi proposal_attachments -> leave_attachments
        DB->>DB: COMMIT
        API-->>Employee: HTTP 200 {status: "pending_manager_review", idempotent_replay: false}
    else Replay Idempotency Key Sama
        DB-->>API: Kembalikan request_id yang sama
        API-->>Employee: HTTP 200 {idempotent_replay: true, status: "pending_manager_review"}
    end

    Note over API,HRIS: Fase 3: Tinjauan Manusia (API Approval Dikunci)
    Employee->>API: POST /api/v1/manager/leave-requests/{id}/review
    API-->>Employee: HTTP 403 Forbidden (Persetujuan akhir hanya di sistem HRIS manusia)
    HRIS->>HRIS: Manajer meninjau antrean pending_manager_review secara manual
```

---

## 6. Resilience, Deferred Side Effects & Graceful Degradation Flow

```mermaid
flowchart TD
    TURN["Agent Turn (Max 4 Turns, Max 6 Tool Calls)"] --> CALL_TOOL{"Tool Dipanggil?"}
    CALL_TOOL -->|"create_hr_ticket"| STAGE["Stage Ticket di Memori (defer_tickets=True, Zero DB Write)"]
    CALL_TOOL -->|"search_hr_policy"| CACHE_REQ["ResilientCache.get(fingerprint_key)"]

    CACHE_REQ --> TRY_REDIS{"Redis Healthy?"}
    TRY_REDIS -->|"Hit"| RET_CACHE["Return Cached Chunks"]
    TRY_REDIS -->|"Outage / Corrupt"| LEX_VEC["Fallback DB Search"]
    LEX_VEC --> TRY_EMBED{"Embedding API Healthy?"}
    TRY_EMBED -->|"Yes"| HYBRID["FTS (GIN) + pgvector (HNSW) via RRF"]
    TRY_EMBED -->|"Timeout / Error"| LEX_ONLY["Degrade ke FTS Lexical-Only (No Poison Cache)"]

    STAGE --> END_CHECK{"Turn Selesai Tanpa Abstain / Error?"}
    END_CHECK -->|"Yes (Outcome.escalated)"| COMMIT_TICKET["Commit Staged Ticket ke Tabel tickets"]
    END_CHECK -->|"Abstained / DomainError / Provider Error"| ROLLBACK_STAGE["Buang Staged Ticket -> Zero DB Side Effect"]
```

---

## 7. Telemetry & Recursive PII Redaction Pipeline

```mermaid
flowchart LR
    RAW["Raw Text / Pydantic ActionProposal / Error / SDK Object"] --> SER["1. Recursive Traversal (redact_trace: BaseModel -> dict -> list -> str)"]
    SER --> REGEX_PHONE["2. Phone Redactor (+62 / 08xx -> [REDACTED_PHONE])"]
    REGEX_PHONE --> REGEX_EMAIL["3. Email Redactor ([REDACTED_EMAIL])"]
    REGEX_EMAIL --> REGEX_TOKEN["4. Token/Secret Redactor (token-/sk-/AIza/ghp_/JWT/Postgres DSN -> [REDACTED_TOKEN])"]
    REGEX_TOKEN --> REGEX_MED["5. Medical Redactor (_BASELINE_MEDICAL_TERMS 23 istilah + DB medical_terms, 60s cooldown)"]
    REGEX_MED --> LOOKBEHIND["6. Negative Lookbehind ('cuti sakit', 'saldo sakit' tetap utuh)"]
    LOOKBEHIND --> TRACE_DB[("PostgreSQL traces table (tanpa raw user message)")]
    LOOKBEHIND --> OPIK_CLD["Opik Cloud (message_length, summarized PolicyChunks, pseudonymized safety_id)"]
```

---

## 8. Operational Monitoring Rules & Response Procedures

Aturan monitoring di-seed dari `data/monitoring_rules.json` ke tabel PostgreSQL `monitoring_rules` oleh `src/setup_lab.py` (dengan default in-memory pada `MemoryRepository`):

| Rule ID | Metric Target | Operator | Threshold | Minimum Samples | Owner | Action Response Procedure |
|---|---|:---:|:---:|:---:|---|---|
| `agent-error-spike` | `error_rate` | `>` | `0.20` (20%) | 5 | AI Platform | Periksa trace ter-redaksi dan kesehatan provider/PostgreSQL; nonaktifkan mutating tools jika error berlanjut. |
| `agent-latency-p95` | `p95_latency_ms` | `>` | `8000 ms` | 5 | AI Platform | Periksa latensi LLM/embedding provider, retrieval cache hit rate, dan timing query database. |

---

## 9. Architecture Decision Records (ADR)

### ADR-001: Hybrid Search (PostgreSQL FTS GIN + pgvector HNSW) dengan RRF ($k=60$)
- **Context:** Pencarian kebijakan memerlukan ketepatan istilah/kode regulasi eksak (seperti `HR-LEAVE-001`) sekaligus pemahaman semantik Bahasa Indonesia, serta harus tetap mengembalikan hanya dokumen dengan `effective_date <= active_today` dan `version` terbaru.
- **Decision:** Menggabungkan PostgreSQL Full-Text Search (`to_tsvector('simple', ...)` dengan index GIN `policy_chunks_fts_idx`) dan Vector Cosine Similarity (`<=>` dengan index HNSW `policy_chunks_embedding_hnsw_idx`) melalui Reciprocal Rank Fusion ($k=60$) dan tie-breaker keyword `0.0002 * overlap`.
- **Alternatives Considered:** Vector-only search (lemah pada kode regulasi eksak); `ILIKE` scan penuh (tidak menggunakan index FTS).
- **Trade-offs:** Memerlukan maintenance index GIN/HNSW saat seeding, namun memberikan akurasi recall tinggi dan fallback leksikal otomatis bila embedding provider mengalami outage.
- **Production Follow-up:** Penambahan *stemming*/kamus Bahasa Indonesia khusus atau *cross-encoder reranker* bila korpus mencapai ribuan dokumen.

### ADR-002: Pending-Only Actions, Pra-Konfirmasi Lampiran & Idempotent Confirmation
- **Context:** Agen AI tidak boleh menyetujui cuti secara sepihak, dan cuti sakit di atas ambang batas kebijakan wajib disertai surat dokter sebelum masuk antrean tinjauan.
- **Decision:** Memisahkan fase proposal (`ActionProposal` ber-TTL 15 menit) dari fase konfirmasi (`POST /api/v1/action-proposals/{id}/confirm`), menambahkan tabel `proposal_attachments` + endpoint upload pra-konfirmasi, mengunci status akhir pada `pending_manager_review`, dan mengunci endpoint `/api/v1/manager/leave-requests/{id}/review` ke HTTP `403`.
- **Alternatives Considered:** Upload lampiran sesudah `/confirm` (menimbulkan status `pending_manager_review` tanpa lampiran valid); mengizinkan endpoint API mengubah status menjadi `approved` (melanggar Hard Gate pending-only).
- **Trade-offs:** Menambah satu langkah upload sebelum `/confirm` pada cuti sakit panjang, tetapi menjamin kepatuhan penuh terhadap kebijakan HR.
- **Production Follow-up:** Integrasi webhook satu arah ke sistem HRIS eksternal tempat manajer manusia melakukan persetujuan akhir.

### ADR-003: Dynamic DB Policy Matrix (`policy_chunks` → Domain/Calendar/API → SPA)
- **Context:** Menanam angka kebijakan (seperti H-3 atau `>2 hari`) di prompt atau kode Python menyebabkan inkonsistensi ketika HR memperbarui dokumen kebijakan.
- **Decision:** Memusatkan sumber aturan pada tabel `policy_chunks`. Fungsi `get_policy_document_text`, `policy_fingerprint`, `get_annual_leave_lead_days`, `get_sick_leave_doc_threshold`, dan `count_lead_business_days` mengekstrak aturan secara dinamis untuk validasi tool, hasil `get_calendar`, endpoint `GET /api/v1/policies/rules`, dan sinkronisasi UI Web SPA.
- **Alternatives Considered:** Hardcoding konstanta pada `SYSTEM_INSTRUCTIONS` dan frontend JS.
- **Trade-offs:** Format redaksi angka/kalimat pada kebijakan baru perlu mengikuti pola Bahasa Indonesia standar yang didukung parser `_parse_policy_number`.
- **Production Follow-up:** Menyimpan metadata aturan terstruktur (*structured policy schema*) di samping teks Markdown saat ingestion HR.

### ADR-004: Hash-Only Auth Sessions & Privacy-First Telemetry Redaction
- **Context:** Menyimpan token demo plaintext (`persona_tokens`), membiarkan `/api/v1/*` tanpa autentikasi, atau mengandalkan query DB tanpa fallback pada `redact()` menimbulkan risiko kebocoran kredensial dan data medis.
- **Decision:** Menghapus tabel `persona_tokens`, menyimpan sesi ber-TTL hanya dalam bentuk hash SHA-256 di `auth_sessions`, mewajibkan `Depends(current_auth)` pada seluruh rute `/api/v1/*`, memblokir `monitoring_admin` dari lampiran medis (`403`), menyediakan 23 `_BASELINE_MEDICAL_TERMS` in-memory dengan cooldown DB 60 detik, dan menerapkan `redact_trace` rekursif + ringkasan Opik tanpa prompt mentah.
- **Alternatives Considered:** Menyimpan token plaintext untuk kemudahan demo; redaksi hanya pada string tingkat atas.
- **Trade-offs:** Akun `monitoring_admin` memerlukan login password pada Web SPA (tidak ada 1-klik demo session), namun menjamin isolasi hak akses istimewa.
- **Production Follow-up:** Integrasi SSO OIDC/OAuth2 enterprise (Okta/Azure AD) dan ontologi medis terenkripsi (ICD-10 / SNOMED-CT).

### ADR-005: Deferred Side-Effect Tickets & Resilient Cache Degradation
- **Context:** Pembuatan tiket langsung di tengah turn berisiko meninggalkan tiket yatim jika turn berikutnya gagal atau abstain, sementara kegagalan Redis tidak boleh melumpuhkan layanan chat.
- **Decision:** Menunda penulisan `create_hr_ticket` (`defer_tickets=True`) hingga seluruh loop agent selesai tanpa status `abstained` (lalu memancarkan `Outcome.escalated`), serta membungkus Redis dalam `ResilientCache` ber-timeout 0.5 detik yang mendegradasi error menjadi *cache miss*.
- **Alternatives Considered:** Menulis tiket segera saat pemanggilan tool; fail-fast jika Redis mati.
- **Trade-offs:** Memerlukan state `staged_tickets` selama satu siklus `AgentService.run()`, namun menjamin properti *zero side effects on abstention*.
- **Production Follow-up:** Redis Sentinel/Cluster HA serta *circuit breaker* cooldown untuk Redis outage berkepanjangan.
