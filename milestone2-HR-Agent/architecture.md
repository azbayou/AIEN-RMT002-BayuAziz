# Architecture Assignment

---

## 1. Problem Framing, Personas, and Scope

### 1.1 Problem Framing
Karyawan sering menghadapi kesulitan dalam menavigasi dokumen kebijakan HR yang panjang dan kompleks untuk mengetahui hak mereka (seperti jatah cuti, aturan kerja remote/WFH, dan prosedur izin sakit). Di sisi lain, sistem AI yang langsung mengeksekusi perubahan data (seperti persetujuan cuti otomatis) tanpa pengawasan menimbulkan risiko kepatuhan ketenagakerjaan dan kebocoran data pribadi (PII).

Sistem **Miyo HR Assistant** dirancang sebagai asisten kebijakan HR enterprise yang menggabungkan:
1. **Grounded RAG (Retrieval-Augmented Generation)** dengan sitasi terverifikasi untuk menjamin jawaban akurat tanpa halusinasi.
2. **Action Safety dua fase** di mana asisten hanya dapat menyiapkan proposal sementara (*pending-only*), dan eksekusi membutuhkan konfirmasi eksplisit karyawan serta persetujuan akhir manajer.
3. **Data Isolation & Privacy** berbasis token bearer, isolasi data antar pegawai (*no IDOR*), dan redaksi otomatis terhadap informasi medis dan PII sebelum masuk ke log/trace.

### 1.2 User Personas
| Persona | Role | Identitas & Token | Wewenang & Batasan |
|---|---|---|---|
| **Alya Pratama** | Regular Employee | `EMP-001` (`token-alya`) | Membaca kebijakan HR, melihat saldo cuti sendiri, membuat proposal cuti sendiri, membuat tiket HR. |
| **Bima Satria** | Regular Employee | `EMP-002` (`token-bima`) | Membaca kebijakan HR, melihat saldo cuti sendiri, terisolasi penuh dari data Alya & Citra. |
| **Citra Dewi** | Regular Employee | `EMP-003` (`token-citra`) | Membaca kebijakan HR, melihat saldo cuti sendiri, terisolasi penuh dari data pegawai lain. |
| **HR Operations / Manager** | System Administrator | `token-admin` | Mengakses ringkasan metrik monitoring operasional (`/api/v1/monitoring/summary`), review trace tersanitasi. Tidak dapat melihat data medis sensitif mentah. |

### 1.3 Scope & Non-Scope
- **In Scope:**
  - Tanya jawab kebijakan HR berbahasa Indonesia berbasis sitasi dokumen (`HR-LEAVE-001`, dsb.).
  - Pengecekan saldo cuti resmi milik pegawai aktif dari PostgreSQL.
  - Perhitungan hari kerja (*inclusive business days*) dengan skipping akhir pekan (Sabtu-Minggu) dan validasi lead time (minimal 3 hari kerja ke depan).
  - Pembuatan draft proposal cuti ber-TTL (15 menit) dengan token konfirmasi unik.
  - Konfirmasi pengajuan cuti yang menghasilkan status `pending_manager_review` dengan jaminan idempotency.
  - Redaksi otomatis PII (email, no HP Indonesia, token rahasia, istilah medis).
  - Graceful degradation saat Redis atau Embedding provider mengalami gangguan.
- **Out of Scope (Non-Negotiable Constraints):**
  - AI dilarang menyetujui (*approve*) permohonan cuti secara mandiri.
  - AI dilarang mengakses, menampilkan, atau memodifikasi data milik pegawai lain.
  - AI dilarang menyimpan API key, kredensial, atau plaintext PII ke trace database.

---

## 2. End-to-End System Architecture

```mermaid
flowchart TD
    subgraph ClientLayer["Client & Presentation Layer"]
        UI["Streamlit UI (Port 8501)"]
        CLI["Evaluator CLI / Grader"]
    end

    subgraph APILayer["Application & API Layer (FastAPI Port 8000)"]
        AUTH["Bearer Token Authenticator"]
        API["FastAPI Orchestrator (8 Endpoints)"]
        SEC["Security & Redaction Engine"]
        AGENT["AgentService (Persona Miyo)"]
        TOOLS["Strict Tool Executor (4 Tools)"]
        RET["RetrievalService (Hybrid RRF)"]
    end

    subgraph DataLayer["Storage & Cache Infrastructure"]
        PG[("PostgreSQL 16 + pgvector (Port 5432)")]
        REDIS[("Redis 7 Cache (Port 6379)")]
    end

    subgraph ExternalServices["External LLM Enclave"]
        OPENAI["OpenAI API (gpt-6-luna / text-embedding-3-small)"]
    end

    UI -->|"HTTP Bearer token"| AUTH
    CLI -->|"HTTP /api/v1/*"| AUTH
    AUTH -->|"Validated AuthContext"| API
    API -->|"Request Message"| AGENT
    AGENT -->|"Sanitize/Redact"| SEC
    AGENT -->|"Multi-turn Tool Call"| TOOLS
    TOOLS -->|"search_hr_policy"| RET
    TOOLS -->|"leave/balance ops"| PG
    RET -->|"Cache Check / Set"| REDIS
    RET -->|"Hybrid Search / Embeddings"| PG
    RET -->|"Query Vectorizer"| OPENAI
    AGENT -->|"Responses API (store=False)"| OPENAI
    API -->|"Save Redacted Trace"| PG
```

---

## 3. Trust Boundaries & Security Enclaves

```mermaid
flowchart TD
    subgraph TB0["Trust Boundary 0: Public & Client Zone"]
        USER["Browser / Streamlit User"]
    end

    subgraph TB1["Trust Boundary 1: Authentication Gateway"]
        direction TB
        BEARER["Bearer Header Validation"]
        HASH_AUTH["SHA-256 Token Matching (SSOT: data/employees.json)"]
        CTX["Immutable AuthContext (employee_id, display_name, roles)"]
        BEARER --> HASH_AUTH --> CTX
    end

    subgraph TB2["Trust Boundary 2: Application Execution Enclave"]
        direction TB
        INPUT_VAL["Pydantic Strict Validation (extra='forbid')"]
        TOOL_GUARD["Identity Binding Enforcement (AuthContext only)"]
        REDACT_PIPE["PII & Medical Term Redaction Engine"]
        INPUT_VAL --> TOOL_GUARD --> REDACT_PIPE
    end

    subgraph TB3["Trust Boundary 3: Internal Data Enclave"]
        direction TB
        SQL_TX["Parameterized SQL with FOR UPDATE Locks"]
        ROW_ISOLATION["Owner Predicates (WHERE employee_id = auth.employee_id)"]
        SQL_TX --> ROW_ISOLATION
    end

    subgraph TB4["Trust Boundary 4: External Third-Party Enclave"]
        direction TB
        EXT_LLM["OpenAI API with store=False"]
        SAFETY_ID["Hashed safety_identifier (SHA-256)"]
        EXT_LLM --- SAFETY_ID
    end

    USER -->|"Untrusted HTTP Request"| TB1
    CTX -->|"Trusted Identity Context"| TB2
    REDACT_PIPE -->|"Safe Sanitized Queries"| TB3
    TOOL_GUARD -->|"Sanitized Tool Inputs"| TB4
```

### Trust Boundary Rules
1. **TB0 &rarr; TB1 (Public ke Gateway):** Semua input dari luar dianggap *untrusted*. Header `Authorization: Bearer <token>` wajib diperiksa. Token di-hash dengan SHA-256 sebelum dicocokkan dengan data repositori.
2. **TB1 &rarr; TB2 (Gateway ke Application):** Objek `AuthContext` bersifat *immutable*. Semua tool dilarang menerima argumen `employee_id` dari model atau request body pengguna.
3. **TB2 &rarr; TB3 (Application ke Storage):** Seluruh query database menggunakan parameter binding (mencegah SQL Injection). Transaksi konfirmasi cuti menggunakan row-level locking (`SELECT ... FOR UPDATE`) dan predicate `WHERE employee_id = %s` untuk mengunci isolasi penyewa (*tenant isolation*).
4. **TB2 &rarr; TB4 (Application ke External LLM):** Panggilan ke OpenAI menggunakan `store=False`, `safety_identifier` yang di-hash dengan SHA-256, teks dokumen kebijakan di-treat sebagai *untrusted data* (anti prompt-injection), dan PII diredaksikan sebelum masuk log.

---

## 4. Hybrid RAG & Policy Retrieval Flow

```mermaid
sequenceDiagram
    autonumber
    actor Employee as Karyawan
    participant Agent as AgentService
    participant Tools as ToolExecutor
    participant Retrieval as RetrievalService
    participant Cache as ResilientCache
    participant Provider as OpenAI / Deterministic
    participant DB as PostgreSQL (pgvector)

    Employee->>Agent: "Berapa jatah cuti tahunan saya?"
    Agent->>Provider: LLM Turn 1 (tools definition)
    Provider-->>Agent: Call search_hr_policy(query="cuti tahunan", top_k=3)
    Agent->>Tools: execute("search_hr_policy", args, AuthContext)
    Tools->>Retrieval: search("cuti tahunan", top_k=3)
    Retrieval->>Cache: get("policies-2026-01:hash(query)")
    alt Cache Hit
        Cache-->>Retrieval: Cached List of PolicyChunk
    else Cache Miss / Redis Down
        Retrieval->>Provider: embed(["cuti tahunan"])
        Provider-->>Retrieval: Vector embedding [1536 dim]
        Retrieval->>DB: Lexical Search (ILIKE) + Vector Search (<=> cosine)
        DB-->>Retrieval: Candidate Chunks
        Retrieval->>Retrieval: Reciprocal Rank Fusion (RRF k=60) + Keyword Rerank
        Retrieval->>Cache: setex(key, ttl=900s, chunks)
    end
    Retrieval-->>Tools: Top 3 Grounded PolicyChunk
    Tools-->>Agent: Formatted Policy Results
    Agent->>Provider: LLM Turn 2 (with function_call_output)
    Provider-->>Agent: Text with citation "[HR-LEAVE-001]"
    Agent->>Agent: Validate citation: is [HR-LEAVE-001] in retrieved chunks? (YES)
    Agent-->>Employee: Answer + Valid Citation Metadata
```

---

## 5. Two-Phase Action Safety & Idempotent Confirmation Flow

```mermaid
sequenceDiagram
    autonumber
    actor Employee as Karyawan
    participant Agent as AgentService
    participant Tools as ToolExecutor
    participant DB as PostgreSQL (pgvector)
    participant Manager as HR Manager

    Note over Employee,Agent: Fase 1: Pembuatan Proposal (Pending Only, Bebas Efek Samping)
    Employee->>Agent: "Ajukan cuti tahunan 2026-12-01 s/d 2026-12-03"
    Agent->>Tools: execute("prepare_leave_request", args, AuthContext)
    Tools->>Tools: Validasi domain (3 hari kerja, lead time, saldo)
    Tools->>DB: save_proposal(ActionProposal with TTL=15m)
    Tools-->>Agent: ActionProposal (requires_confirmation=True)
    Agent-->>Employee: Respon Outcome: action_proposed + Detail Proposal

    Note over Employee,DB: Fase 2: Konfirmasi Eksplisit & Idempotensi
    Employee->>Agent: POST /api/v1/actions/confirm {proposal_id, idempotency_key}
    Agent->>DB: Begin DB Transaction (FOR UPDATE lock on employee balance)
    alt Proposal Valid & Not Expired & Key Baru
        DB->>DB: Insert leave_requests (status='pending_manager_review')
        DB->>DB: Insert confirmation_audit (idempotency_key, request_id)
        DB->>DB: Commit Transaction
        Agent-->>Employee: Status 200: {status: 'confirmed', request_status: 'pending_manager_review'}
    else Replay dengan Idempotency Key yang Sama
        DB-->>Agent: Return existing confirmation record
        Agent-->>Employee: Status 200: Idempotent replay result (Tanpa duplicate request)
    else Proposal Expired / Overlap / Wrong Employee
        DB-->>Agent: Rollback Transaction
        Agent-->>Employee: Status 409 / 404 Problem Details RFC 7807
    end

    Note over DB,Manager: Fase 3: Review Manajer (Di Luar Kuasa AI)
    Manager->>DB: Review permohonan berstatus 'pending_manager_review'
    Manager->>DB: Setujui / Tolak secara manual di portal HR
```

---

## 6. Resilience & Graceful Cache Degradation Flow

```mermaid
flowchart TD
    Q["Search Query"] --> CACHE_REQ["ResilientCache.get(key)"]
    CACHE_REQ --> TRY_REDIS{"Redis Accessible & Valid JSON?"}

    TRY_REDIS -->|"Yes (Cache Hit)"| RETURN_CACHE["Return Cached PolicyChunk Immediately (Latency < 2ms)"]
    TRY_REDIS -->|"No (Redis Outage / Corrupt JSON)"| LOG_WARN["Log Warning & Degrade Gracefully to Cache Miss (No Crash)"]

    LOG_WARN --> QUERY_DB["Execute PostgreSQL Hybrid Search"]
    QUERY_DB --> TRY_EMBED{"Embedding Provider Healthy?"}

    TRY_EMBED -->|"Yes"| FULL_HYBRID["Combine Lexical + Vector via RRF (k=60)"]
    TRY_EMBED -->|"Timeout / Error"| LEX_ONLY["Degrade to Lexical-only Search (ILIKE)"]

    FULL_HYBRID --> CACHE_SET["Attempt ResilientCache.set(key, ttl)"]
    LEX_ONLY --> CACHE_SET

    CACHE_SET --> SET_REDIS{"Redis Available?"}
    SET_REDIS -->|"Yes"| STORED["Key Stored with TTL"]
    SET_REDIS -->|"No"| SUPPRESS["Suppress RedisError Silently (Zero Side Effect)"]

    STORED --> FINAL_RETURN["Return Policy Results to Tool Executor"]
    SUPPRESS --> FINAL_RETURN
```

---

## 7. Telemetry & PII Redaction Pipeline

```mermaid
flowchart LR
    RAW["Raw Tool Output / Error / Prompt"] --> REGEX_PHONE["1. Phone Redactor (+62 / 08xx)"]
    REGEX_PHONE --> REGEX_EMAIL["2. Email Redactor ([a-zA-Z0-9._%+-]+@...)"]
    REGEX_EMAIL --> REGEX_TOKEN["3. Token Redactor (Bearer / secret-token_*)"]
    REGEX_TOKEN --> REGEX_MED["4. Medical Terms Redactor (SSOT: data/medical_terms.json)"]
    REGEX_MED --> LOOKBEHIND["5. Negative Lookbehind Preservation ('cuti sakit' preserved)"]
    LOOKBEHIND --> SANITIZED["Redacted Payload [REDACTED]"]
    SANITIZED --> TRACE_DB[("PostgreSQL traces table")]
    SANITIZED --> MON_API["Admin Monitoring API (No Plaintext Leaks)"]
```

---

## 8. Operational Monitoring Rules & Response Procedures

Sistem mengevaluasi telemetry secara dinamis dari `data/monitoring_rules.json`:

| Rule ID | Metric Target | Operator | Threshold | Minimum Samples | Owner | Action Response Procedure |
|---|---|:---:|:---:|:---:|---|---|
| `agent-error-spike` | `error_rate` | `>` | `0.20` (20%) | 5 | AI Platform | Periksa trace ter-redaksi dan koneksi OpenAI / PostgreSQL; nonaktifkan mutating tools jika error berlanjut. |
| `agent-latency-p95` | `p95_latency_ms` | `>` | `8000 ms` | 5 | AI Platform | Periksa latensi OpenAI responses API, connection pool database, dan status Redis cache hit rate. |

---

## 9. Architecture Decision Records (ADR)

### ADR-001: Hybrid Search (Lexical + Vector) dengan Reciprocal Rank Fusion (RRF $k=60$)
- **Context:** Pencarian kebijakan membutuhkan akurasi kata kunci eksak (seperti nomor klausul `HR-LEAVE-001` atau istilah spesifik) sekaligus pemahaman semantik untuk pertanyaan alami pegawai.
- **Decision:** Menggabungkan Lexical Search (PostgreSQL `ILIKE` dengan reranking) dan Vector Cosine Similarity (`<=>` pgvector 1536 dimensi) menggunakan rumus Reciprocal Rank Fusion:
  $$\text{score}(d) = \sum_{m \in \{\text{lexical}, \text{vector}\}} \frac{1}{k + \text{rank}_m(d)}, \quad k = 60$$
- **Alternatives Considered:** Vector-only search (gagal pada kode regulasi eksak); Elasticsearch eksternal (terlalu berat untuk milestone).
- **Trade-offs:** Memerlukan dua query dalam satu pemanggilan retrieval, tetapi memberikan akurasi tertinggi dan toleransi kegagalan jika provider embedding down.
- **Production Follow-up:** Mengaktifkan index HNSW (`vector_cosine_ops`) dan PostgreSQL Full-Text Search (`tsvector`) untuk dataset skala jutaan dokumen.

### ADR-002: Pending-Only Actions dengan Two-Phase Confirmation & Idempotency Key
- **Context:** LLM tidak boleh memiliki otoritas untuk mengubah status saldo atau menyetujui permohonan cuti secara langsung tanpa verifikasi manusia.
- **Decision:** Menerapkan siklus 2 fase: Fase 1 hanya menghasilkan objek `ActionProposal` ber-TTL 15 menit. Fase 2 menerima endpoint eksplisit `/api/v1/actions/confirm` dengan `idempotency_key`. Status akhir cuti di database terkunci pada `pending_manager_review`.
- **Alternatives Considered:** Eksekusi langsung via tool agent (berisiko tinggi); persetujuan otomatis jika saldo cukup (melanggar aturan kepatuhan).
- **Trade-offs:** Pengguna harus melakukan satu langkah tambahan (klik konfirmasi), namun menjamin 100% kepatuhan audit HR dan ketiadaan efek samping liar.
- **Production Follow-up:** Integrasi webhook notifikasi Slack/Email ke manajer divisi yang bersangkutan.

### ADR-003: Sitasi Ketat dan Kebijakan Abstain Mandatori
- **Context:** Jawaban LLM yang tampak meyakinkan namun tidak berdasar (*hallucination*) berbahaya bagi reputasi perusahaan dan hak pegawai.
- **Decision:** Agen "Miyo" diwajibkan menyertakan sitasi `[HR-XXX-XXX]`. Sistem memvalidasi bahwa setiap dokumen yang disitir merupakan subset sah dari hasil retrieval run yang sedang aktif (`cited_ids.issubset(available_ids)`). Jika sitasi tidak valid atau pertanyaan tidak memiliki dasar dokumen, sistem memaksa respon fallback `Outcome.abstained`.
- **Alternatives Considered:** Membiarkan LLM menjawab berdasarkan general pre-training knowledge.
- **Trade-offs:** Beberapa pertanyaan informal mungkin ditolak, tetapi menjamin 0% risiko misinformasi hak ketenagakerjaan.
- **Production Follow-up:** Menambahkan tombol eskalasi langsung ("Buat Tiket HR") saat status abstensi muncul di UI.

### ADR-004: Sanitasi PII & Redaksi Istilah Medis Berbasis SSOT
- **Context:** Data percakapan dan error trace disimpan untuk audit, namun rentan membocorkan data diagnosis medis dan kontak pribadi karyawan (UU PDP).
- **Decision:** Memusatkan seluruh daftar diagnosis medis pada file konfigurasi `data/medical_terms.json` (Single Source of Truth). Redaksi dilakukan secara *in-memory* sebelum persistensi ke PostgreSQL, dengan aturan *negative lookbehind* untuk mempertahankan frasa legal yang sah seperti `cuti sakit`.
- **Alternatives Considered:** Hardcoding regex di `src/security.py` (sulit diperbarui dan melanggar auditability); redaksi post-hoc saat query (raw data telanjur tersimpan).
- **Trade-offs:** Sedikit overhead komputasi regex CPU pada setiap trace, namun menjamin database trace bersih dari PII.
- **Production Follow-up:** Menghubungkan dictionary medis ke medical ontology eksternal terenkripsi (misal ICD-10).

### ADR-005: Resilient Cache dengan Graceful Degradation
- **Context:** Kegagalan Redis (network partition, restart, memory full) tidak boleh menyebabkan API chat lumpuh (*single point of failure*).
- **Decision:** Membungkus koneksi Redis dalam `ResilientCache` dengan timeout agresif (0.5 detik). Seluruh `RedisError` dan kegagalan deserialisasi JSON ditangkap dan didegradasi menjadi *cache miss* tanpa melempar exception ke pemanggil.
- **Alternatives Considered:** Hard error fail-fast (mematikan aplikasi jika Redis mati).
- **Trade-offs:** Latensi sedikit meningkat saat Redis down karena fallback ke DB hybrid search, namun ketersediaan layanan (*uptime*) tetap 100%.
- **Production Follow-up:** Menerapkan Redis Sentinel atau AWS ElastiCache Multi-AZ untuk failover otomatis.

### ADR-006: Identity Binding Eksklusif via AuthContext
- **Context:** Risiko serangan manipulasi identitas (*Insecure Direct Object Reference* / IDOR dan *prompt injection*) di mana model atau user mencoba membaca data saldo pegawai lain.
- **Decision:** Identitas pegawai (`employee_id`) diikat secara ketat hanya dari bearer token yang divalidasi pada dependency injection FastAPI. Tool `get_my_leave_balance` dan `prepare_leave_request` tidak menerima parameter identitas dari prompt atau JSON LLM.
- **Alternatives Considered:** Mengizinkan LLM mengekstrak `employee_id` dari pesan chat (rawan spoofing).
- **Trade-offs:** Pengguna tidak bisa mengecek saldo rekan kerja meskipun diminta secara eksplisit, yang mana merupakan standar privasi enterprise.
- **Production Follow-up:** Menambahkan autentikasi berbasis OIDC/OAuth2 enterprise (Okta/Azure AD) dengan refresh token ber-TTL pendek.
