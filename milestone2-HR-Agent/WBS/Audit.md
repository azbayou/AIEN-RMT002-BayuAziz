# Laporan Audit Komprehensif Implementasi Agent (WBS-00 s/d WBS-12)

- **Tanggal Audit:** 6 November 2026
- **Auditor:** Independent AI Engineering Auditor
- **Ruang Lingkup:**
  - `src/agent.py` (Agent Service, Loop, System Prompt, Citations)
  - `src/tools.py` (Tool Schemas, Execution, Identity Binding)
  - `src/providers.py` & `src/providers2.py` (Responses API, Retries, Testing Mock)
  - `src/retrieval.py` (Hybrid Search, RRF, Versioned Caching)
  - `src/security.py` (PII, Token Hashing, Medical Redaction)
  - `src/setup_lab.py` (Database DDL & Seeding)
  - `src/repository.py` (Persistence, Postgres vs Memory)
  - `src/api.py` (FastAPI Endpoints, Authorization, Problem Details)
  - `Dockerfile` (Non-Root Delivery, Multi-service Image)
  - Dokumen pelacak WBS (`WBS/00-baseline-dan-definition-of-done.md` s/d `WBS/12-Dockerfile.md`)
- **Status Akhir Audit:** **75% SIAP — Layak untuk Unit Test Mock, namun Memiliki Blocker Kritis untuk Live Environment & Evaluasi Docker**.

---

## 1. Ringkasan Eksekutif

Secara arsitektur konseptual, pekerjaan yang telah diselesaikan menunjukkan pemahaman yang kuat terhadap prinsip dasar rekayasa sistem AI yang aman (*Secure AI Engineering*). Pendekatan **Identity Binding** (mengunci identitas dari Bearer token dan menolak argumen ID dari prompt/LLM) serta **Action Safety Boundary** (proposal cuti bersifat *pending-only* dengan TTL dan kunci idempotensi) sudah diterapkan dengan baik dan sesuai dengan spesifikasi rubrik.

Namun, terdapat **3 blocker kritis** dan **beberapa penyimpangan logika** yang akan menggagalkan eksekusi saat sistem diuji menggunakan Docker Compose atau model OpenAI asli (*live mode*):

1. **Format Message State Inkompatibel dengan OpenAI Responses API:** Format percakapan di `src/agent.py` tidak memasukkan output asisten dan menggunakan format tool call lama, yang akan memicu error HTTP 400 di lingkungan live.
2. **PostgresRepository Belum Diimplementasi (`NotImplementedError`):** `build_runtime` pada `src/api.py` memanggil kelas ini secara default, sehingga container API di Docker akan langsung crash saat *startup*.
3. **DDL Tabel PostgreSQL Belum Lengkap:** `src/setup_lab.py` lupa membuat tabel `action_proposals`, `leave_requests`, `tickets`, dan `traces`.

---

## 2. Matriks Kepatuhan Rubrik (Rubric & Hard Gate Compliance)

| Kriteria Rubrik | Target Skor | Status | Evaluasi & Catatan |
|---|:---:|:---:|---|
| **Hard Gate: Identity Isolation** | Mandatory | 🟢 Lulus | Akses saldo dan pengajuan cuti terikat murni ke `AuthContext.employee_id`. IDOR dicegah. |
| **Hard Gate: Pending-only Actions** | Mandatory | 🟢 Lulus | Tidak ada jalur kode yang dapat meng-approve cuti. Status selalu `pending_manager_review`. |
| **Hard Gate: Confirmation & Idempotency** | Mandatory | 🟢 Lulus | Proposal memiliki expiry date, memvalidasi kunci idempotensi, dan mencegah duplikasi replay. |
| **Hard Gate: PII & Secret Redaction** | Mandatory | 🟡 Perlu Perbaikan | Hashing token aman. Over-redaction kata "sakit" pada "cuti sakit" perlu diproteksi agar tidak merusak data. |
| **Hard Gate: Valid Citation & Abstain** | Mandatory | 🔴 Berisiko Gagal | Jika model mengutip ID palsu bersamaan dengan ID valid, validasi saat ini meloloskannya tanpa *abstain*. |
| **RAG & Hybrid Retrieval** | 20 Poin | 🟢 Sangat Baik | Menggabungkan *lexical search* + *dense vector*, RRF ($k=60$), reranking, dan versioned Redis cache. |
| **FastAPI & Problem Detail** | 15 Poin | 🟢 Baik | 8 Endpoint tersedia, exception mapping aman, validation error dibungkus RFC-7807 problem detail. |
| **Docker Non-Root Delivery** | 6 Poin | 🟡 Blocker Runtime | Image non-root (`appuser`), tetapi startup container akan gagal karena `PostgresRepository`. |
| **Monitoring & Alert Rules** | 15 Poin | 🔴 Menyimpang | Endpoint `/api/v1/monitoring/alerts` di-hardcode `return []`, belum mengevaluasi `monitoring_rules.json`. |

---

## 3. Temuan Audit Rinci & Analisis Penyimpangan

### A. `src/agent.py` (Logika Agent & Loop)

#### 1. Inkompatibilitas Format Conversation History dengan Responses API (Kritis 🔴)
- **Lokasi:** `src/agent.py` baris 80
- **Masalah:**
  ```python
  messages.append({"tool_call_id": call.call_id, "content": redact(str(result))})
  ```
  1. Pada OpenAI Responses API (`client.responses.create`), saat tool dipanggil, payload percakapan selanjutnya **wajib menyertakan item output asisten (`turn.output_items`)** sebelum diikuti oleh item output fungsi.
  2. Format output tool di Responses API menggunakan struktur:
     `{"type": "function_call_output", "call_id": call.call_id, "output": str(result)}`, bukan format Chat Completions legacy `{"tool_call_id": ..., "content": ...}`.
- **Dampak:** Kode saat ini hanya lulus di `DeterministicProvider` (mock), tetapi akan melempar `400 Bad Request` saat `OPENAI_API_KEY` live digunakan.

#### 2. Kebocoran Validasi Sitasi Palsu / Halusinasi (Kritis 🔴)
- **Lokasi:** `src/agent.py` baris 127-138 (`_citations_from_text`)
- **Masalah:**
  Fungsi hanya memfilter dokumen yang berhasil ditemukan. Jika model menghasilkan teks:
  *"Cuti tahunan adalah 12 hari [HR-LEAVE-001] dan bonus cuti 5 hari [HR-FAKE-999]."*
  Fungsi mencocokkan `HR-LEAVE-001`, mengabaikan `HR-FAKE-999`, dan meloloskan respon sebagai `Outcome.answered`!
- **Penyimpangan Aturan:** Sesuai `lab.md` baris 133-134, jika terdapat sitasi yang **tidak berasal dari dokumen hasil retrieval run tersebut**, agen **wajib abstain**. Seluruh `cited_ids` wajib berupa *subset* dari `retrieved_ids`.

#### 3. Penanganan Error Domain Menyebabkan Crash Umum (Kekurangan Logika 🟡)
- **Lokasi:** `src/agent.py` baris 69-86
- **Masalah:**
  Ketika `prepare_leave_request` dijalankan dan saldo pengguna tidak cukup, `validate_leave_request` melempar `DomainError("saldo cuti tidak cukup")`.
  Karena tidak ada penanganan error spesifik di dalam loop tool, error tersebut ditangkap oleh `except Exception as error:` umum di baris 83.
- **Dampak Pengguna:** Pengguna mendapat pesan crash sistem: *"Maaf, layanan sedang tidak dapat memberikan jawaban yang aman."* (`Outcome.abstained`).
- **Saran Logika Lebih Baik:** Tangkap `DomainError` pada tingkat eksekusi tool, tandai status tool sebagai `"blocked"`, dan kirimkan teks penolakan kembali ke model sebagai hasil tool. Model kemudian dapat memberikan penjelasan informatif: *"Pengajuan cuti Anda tidak dapat diproses karena saldo cuti tahunan Anda tersisa 2 hari, sedangkan pengajuan membutuhkan 5 hari kerja."*

#### 4. Metrik Status `ToolCallSummary` Selalu Di-hardcode `"ok"` (Penyimpangan Kontrak 🟡)
- **Lokasi:** `src/agent.py` baris 76
- **Masalah:**
  Kontrak Pydantic pada `contracts.py` mendefinisikan `status: Literal["ok", "blocked", "error"]`. Kode saat ini selalu mengisinya dengan `"ok"`.

---

### B. `src/security.py` (Redaksi & Privasi)

#### 5. Over-Redaction Kata Legal "Cuti Sakit" (Penyimpangan 🟡)
- **Lokasi:** `src/security.py` baris 19-23
- **Masalah:**
  Pola `_MEDICAL_TERM_RE` mencakup kata `sakit`. Frasa legal di HR seperti `"cuti sakit"` teredaksi menjadi `"cuti [REDACTED_MEDICAL]"`, yang dapat mengacaukan parsing tipe cuti di LLM dan penyimpanan riwayat.
- **Perbaikan:** Gunakan negative lookbehind `(?<!cuti\s)\bsakit\b` agar frasa "cuti sakit" dipertahankan, sedangkan keluhan sakit mandiri ("saya sakit", "sakit tipus") tetap teredaksi.

---

### C. `src/setup_lab.py` & `src/repository.py` (Database & Seeding)

#### 6. DDL Tabel Transaksional Tidak Ada di Seeding Script (Kritis 🔴)
- **Lokasi:** `src/setup_lab.py` baris 93-125
- **Masalah:**
  Skrip seeding menjalankan:
  `DROP TABLE IF EXISTS traces, tickets, leave_requests, action_proposals, policy_chunks, leave_balances, employees CASCADE`
  Namun bagian `CREATE TABLE IF NOT EXISTS` **hanya membuat 3 tabel**:
  `employees`, `leave_balances`, dan `policy_chunks`.
  Tabel `action_proposals`, `leave_requests`, `tickets`, dan `traces` **tidak pernah dibuat**.
- **Dampak:** Begitu repository PostgreSQL dijalankan, query insert proposal, request, tiket, dan trace akan melempar error `relation does not exist`.

#### 7. `PostgresRepository` Belum Selesai (Kritis 🔴)
- **Lokasi:** `src/repository.py` baris 206-211
- **Masalah:**
  Kelas `PostgresRepository` masih berisi `raise NotImplementedError`.
  Di sisi lain, `src/api.py` baris 31 menginstansiasi `PostgresRepository` di dalam `build_runtime`.
- **Dampak:** Perintah standar Docker `uvicorn src.api:create_app --factory` akan langsung gagal saat container dijalankan.

---

### D. `src/api.py` (Monitoring & Endpoints)

#### 8. Evaluasi Alert Masih Berupa Stub Kosong (Penyimpangan Rubrik 🟡)
- **Lokasi:** `src/api.py` baris 144-145
- **Masalah:**
  ```python
  @app.get("/api/v1/monitoring/alerts")
  def monitoring_alerts(auth: AuthContext = Depends(admin_auth)) -> list[dict[str, Any]]:
      return []
  ```
  File `data/monitoring_rules.json` mendefinisikan aturan evaluasi `error_rate > 0.2` dan `p95_latency_ms > 8000`. Mengembalikan list kosong statis akan mengurangi nilai kategori *Evaluation dan monitoring* (maksimal hanya 50% poin jika monitoring tidak berfungsi).

---

## 4. Rekomendasi Kode Perbaikan (Actionable Code Fixes)

### Perbaikan 1: Validasi Sitasi Ketat & Penanganan Tool Blocked di `src/agent.py`

Ganti blok perulangan eksekusi tool dan validasi sitasi pada `src/agent.py` dengan logika yang lebih tangguh:

```python
# Di dalam perulangan tool execution:
for call in turn.tool_calls:
    call_started = time.monotonic()
    status = "ok"
    try:
        result, call_proposal = self.tools.execute(call.name, call.arguments, auth)
        proposal = call_proposal or proposal
        if isinstance(result, list):
            retrieved.extend(result)
        content_str = redact(str(result))
    except (DomainError, ValueError) as err:
        status = "blocked"
        content_str = f"Tindakan ditolak oleh kebijakan: {redact(str(err))}"
    except Exception as err:
        status = "error"
        content_str = f"Terjadi kesalahan teknis: {redact(str(err))}"

    tool_summaries.append(
        ToolCallSummary(
            name=call.name,
            status=status,
            duration_ms=max(0, int((time.monotonic() - call_started) * 1000)),
        )
    )
    # Gunakan format output Responses API standar
    messages.append({
        "type": "function_call_output",
        "call_id": call.call_id,
        "output": content_str,
    })

# Di dalam validasi sitasi:
cited_ids = set(re.findall(r"\[([A-Z0-9-]+)\]", answer))
retrieved_ids = {chunk.document_id for chunk in retrieved}

# HARD GATE: Jika model mengutip dokumen di luar hasil retrieval -> WAJIB ABSTAIN
if cited_ids and not cited_ids.issubset(retrieved_ids):
    answer = "Maaf, beberapa sitasi yang dirujuk tidak ditemukan dalam dokumen kebijakan resmi."
    citations = []
    outcome = Outcome.abstained
elif not cited_ids and self._requires_evidence(request.message):
    answer = "Maaf, bukti kebijakan yang valid belum tersedia."
    citations = []
    outcome = Outcome.abstained
else:
    citations = [
        Citation(
            document_id=chunk.document_id,
            title=chunk.title,
            section=chunk.section,
            excerpt=chunk.content[:300],
        )
        for chunk in retrieved
        if chunk.document_id in cited_ids
    ]
    outcome = Outcome.action_proposed if proposal else Outcome.answered
```

---

### Perbaikan 2: Lengkapi Skema DDL di `src/setup_lab.py`

Tambahkan pembuatan 4 tabel transaksional pada `reset_and_seed()`:

```python
cursor.execute(
    f"""
    -- Tabel Inti Pegawai, Saldo, dan Kebijakan
    CREATE TABLE IF NOT EXISTS employees (
        employee_id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('employee', 'monitoring_admin')),
        token_hash TEXT NOT NULL UNIQUE
    );
    CREATE TABLE IF NOT EXISTS leave_balances (
        employee_id TEXT NOT NULL REFERENCES employees(employee_id),
        leave_type TEXT NOT NULL,
        available_days INTEGER NOT NULL CHECK (available_days >= 0),
        as_of_date DATE NOT NULL,
        PRIMARY KEY (employee_id, leave_type)
    );
    CREATE TABLE IF NOT EXISTS policy_chunks (
        chunk_id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL,
        title TEXT NOT NULL,
        section TEXT NOT NULL,
        version TEXT NOT NULL,
        effective_date DATE NOT NULL,
        content TEXT NOT NULL,
        embedding vector({dimension}) NOT NULL
    );
    CREATE INDEX IF NOT EXISTS policy_chunks_document_idx
        ON policy_chunks (document_id, version);

    -- Tabel Transaksional (Wajib untuk PostgresRepository)
    CREATE TABLE IF NOT EXISTS action_proposals (
        proposal_id TEXT PRIMARY KEY,
        employee_id TEXT NOT NULL REFERENCES employees(employee_id),
        payload JSONB NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS leave_requests (
        request_id TEXT PRIMARY KEY,
        employee_id TEXT NOT NULL REFERENCES employees(employee_id),
        leave_type TEXT NOT NULL,
        start_date DATE NOT NULL,
        end_date DATE NOT NULL,
        business_days INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (status = 'pending_manager_review'),
        idempotency_key TEXT NOT NULL UNIQUE,
        created_at TIMESTAMPTZ NOT NULL
    );
    CREATE TABLE IF NOT EXISTS tickets (
        ticket_id TEXT PRIMARY KEY,
        employee_id TEXT NOT NULL REFERENCES employees(employee_id),
        category TEXT NOT NULL,
        summary TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS traces (
        trace_id TEXT PRIMARY KEY,
        employee_id TEXT NOT NULL,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """
)
```

---

## 5. Rencana Tindakan Perbaikan (Action Plan)

| Prioritas | Item Tindakan | File Terkait | Target Hasil |
|:---:|---|---|---|
| **P0** | Perbaiki DDL seeding tabel transaksional | `src/setup_lab.py` | Seluruh 7 tabel dibuat di PostgreSQL saat `setup_lab` dijalankan. |
| **P0** | Implementasikan `PostgresRepository` | `src/repository.py` | `build_runtime` dapat terkoneksi dan beroperasi tanpa error pada Docker. |
| **P1** | Perbaiki format pesan & validasi sitasi ketat | `src/agent.py` | Lulus uji Responses API live dan mematuhi Hard Gate invalid citation. |
| **P1** | Handle `DomainError` agar menjadi respon ramah | `src/agent.py`, `src/tools.py` | User diberitahu mengapa cuti ditolak tanpa crash sistem. |
| **P2** | Implementasi evaluasi aturan alert | `src/api.py` | Endpoint `/api/v1/monitoring/alerts` aktif mengevaluasi metrik. |
| **P2** | Implementasikan runner evaluasi 15 kasus | `src/run_evaluation.py` | Menghasilkan laporan JSON evaluasi untuk bukti submission release. |

