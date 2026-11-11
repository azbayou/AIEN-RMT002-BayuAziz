# WBS-23-P3 — ProblemDetail Global, Readiness Index, Monitoring, dan Kelengkapan Dokumentasi

- **Target:** `src/api.py`, `src/repository.py`, `README.md`, `templates/project-brief.md`, `templates/evaluation-report.md`, `templates/demo-script.md`, `tests/self_test_api_docker.py`.
- **Owner:** Agent AI; pemilik repo melengkapi screenshot UI/monitoring untuk demo.
- **Dependency:** WBS-19-P0, WBS-20-P1, WBS-21-P1, WBS-22-P2.
- **Status:** DONE

## Batasan Scope (Wajib Dipatuhi Agent)

- **Boleh diedit:** `src/api.py`, `src/repository.py`, `README.md`, `templates/project-brief.md`, `templates/evaluation-report.md`, `templates/demo-script.md`, `tests/self_test_api_docker.py`.
- **DILARANG diedit:** `app.py`, `ui_contract.py`, `demo_personas.json`, `tests/test_api.py`.
- Perhatikan bahwa `app.py` (dan test di `assessment.md`) membaca `response.json().get("detail")` saat terjadi error HTTP. Karena `ProblemDetail` (`src/contracts.py`) memiliki field `detail: str`, mengembalikan `ProblemDetail(...).model_dump()` pada `HTTPException` tetap 100% kompatibel dengan `response.json()["detail"]` sekaligus memenuhi kontrak RFC-7807 `ProblemDetail`!

---

## Pekerjaan

### Task 1: Gunakan `ProblemDetail` Secara Konsisten untuk `HTTPException` dan Unhandled Exception di `src/api.py`

Di `src/api.py` (sekitar baris 64), tambahkan exception handler untuk `HTTPException` dan `Exception` tepat di bawah `validation_error_handler`:

```python
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        titles = {
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not found",
            409: "Conflict",
        }
        return JSONResponse(
            status_code=exc.status_code,
            content=ProblemDetail(
                title=titles.get(exc.status_code, "Request error"),
                status=exc.status_code,
                detail=redact(str(exc.detail)),
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content=ProblemDetail(
                title="Internal server error",
                status=500,
                detail="An unexpected error occurred.",
            ).model_dump(),
        )
```

### Task 2: Periksa Kesiapan Tabel & Policy Index pada `PostgresRepository.health()`

`brief.md` meminta `/readyz` memverifikasi kesiapan database dan index. Di `PostgresRepository.health(self) -> bool` (`src/repository.py` sekitar baris 247), pastikan tabel `policy_chunks` sudah ada dan memiliki minimal 1 baris (sudah di-seed):

```python
    def health(self) -> bool:
        try:
            with self.pool.connection() as connection:
                row = connection.execute(
                    "SELECT COUNT(*) AS chunk_count FROM policy_chunks"
                ).fetchone()
            return bool(row and int(row["chunk_count"]) > 0)
        except Exception:
            return False
```

*(Catatan: `MemoryRepository.health()` tetap mengembalikan `True` agar seluruh unit test in-memory tetap berjalan tanpa perubahan).*

### Task 3: Tambahkan Metrik `abstain_count`, `abstain_rate`, dan `blocked_count` pada `monitoring_summary()`

Di `src/repository.py`:
1. Pada `MemoryRepository.monitoring_summary()` (sekitar baris 197), tambahkan perhitungan:
   ```python
        abstains = sum(trace.get("outcome") == "abstained" for trace in traces)
        blocked = sum(bool(trace.get("blocked_reason")) for trace in traces)
   ```
   Lalu sertakan `"abstain_count": abstains`, `"abstain_rate": abstains / total if total else 0.0`, dan `"blocked_count": blocked` pada dictionary yang dikembalikan (pertahankan seluruh key lama: `run_count`, `total_traces`, `error_count`, `error_rate`, `p95_latency_ms`, `tool_calls`).
2. Pada `PostgresRepository.monitoring_summary()` (sekitar baris 491), tambahkan di query SQL:
   ```sql
   COUNT(*) FILTER (WHERE payload->>'outcome' = 'abstained') AS abstain_count,
   COUNT(*) FILTER (WHERE COALESCE(payload->>'blocked_reason', '') <> '') AS blocked_count,
   ```
   Lalu sertakan `"abstain_count"`, `"abstain_rate"`, dan `"blocked_count"` pada dictionary return-nya.

### Task 4: Perbaiki Tabel Persona di `README.md`

Di `README.md` bagian `## 👥 Persona & Matriks Otorisasi`:
- Hapus baris **Citra Dewi (`EMP-003`)** karena tidak ada di `data/employees.json` maupun `demo_personas.json`.
- Ubah nama **Bima Satria** menjadi **Bima Santoso** (`EMP-002`).
- Ubah ID **HR Admin** dari `ADMIN` menjadi `ADM-001` (`Monitoring Admin`) sesuai `data/employees.json`.
- Di bagian `## 🌐 Akses Aplikasi & Dokumentasi`, ubah teks `(Pilih persona di sidebar kiri: Alya Pratama, Bima Satria, atau Citra Dewi)` menjadi `(Pilih persona di sidebar kiri: Alya — pegawai, Bima — pegawai, atau Monitoring admin)`.

### Task 5: Isi Dokumen Template di Folder `templates/`

Lengkapi ketiga file template yang saat ini masih kosong berdasarkan data dari `architecture.md`, `outputs/evaluation_report.json`, dan `README.md`:

1. **`templates/project-brief.md`**:
   - **Target User:** Pegawai tetap/probation Nusantara Digital (`EMP-001`, `EMP-002`) dan Monitoring Admin (`ADM-001`).
   - **Current Workflow and Pain Point:** Pertanyaan kebijakan HR berulang secara manual dan pengajuan cuti rawan salah hitung hari kerja/saldo.
   - **In Scope:** RAG kebijakan HR ber-sitasi, cek saldo pribadi (`AuthContext`), proposal cuti 2-fase (`pending_manager_review`), tiket eskalasi HR, redaksi PII/medis, telemetry & monitoring.
   - **Out of Scope:** Persetujuan/penolakan cuti otomatis oleh AI, akses data lintas pegawai, penyimpanan diagnosis medis rinci, fine-tuning model.
   - **Success Criteria:** Hard gates 100% lulus, pass rate ≥ 80%, recall@3 ≥ 80%, citation validity 100%, p95 latency < 8000 ms, Docker non-root berjalan dari checkout bersih.
   - **Production Gaps:** Integrasi kalender libur nasional, SSO/OIDC enterprise, workflow approval manajer dua arah, ontologi medis ICD-10.

2. **`templates/evaluation-report.md`**:
   - Isi tabel metrik dengan hasil evaluasi (`15/15` atau hasil terbaru dari `outputs/evaluation_report.json`, Hard gates `100%`, Retrieval recall@3 `100%`, Citation validity `100%`, p50/p95 latency, serta token usage).
   - Isi bagian **Failure Analysis**, **Release Decision** (`GO / release`), dan **Regression Cases Added** (kasus overlap cuti dan idempotent replay).

3. **`templates/demo-script.md`**:
   - Lengkapi langkah 1 s/d 7 dengan contoh input prompt nyata, token persona yang dipakai (`token-alya`, `token-bima`, `token-admin`), respons yang diharapkan, serta daftar backup artifact (`outputs/evaluation_report.json`, `architecture.md`, `risk-register.csv`).

### Task 6: Tambahkan Unit Test untuk `ProblemDetail` pada 401/403/404/409 di `tests/self_test_api_docker.py`

Di `tests/self_test_api_docker.py`, tambahkan test `test_api_errors_return_rfc7807_problem_detail(api_client: TestClient)` yang memverifikasi:
- Response 401 memiliki key `"type"`, `"title"`, `"status" == 401`, dan `"detail"`.
- Response 403 pada `/api/v1/monitoring/summary` dengan `AUTH_ALYA` memiliki `"title" == "Forbidden"`, `"status" == 403`, dan `"detail"`.
- Response 404 pada `/api/v1/traces/tr-unknown` memiliki `"title" == "Not found"`, `"status" == 404`, dan `"detail"`.

---

## Langkah Verifikasi

```bash
pytest tests/test_api.py tests/self_test_api_docker.py -v
pytest -m "not live"
```

## Acceptance Criteria

- [x] Seluruh error HTTP (401, 403, 404, 409, 422, 500) mengembalikan struktur JSON `ProblemDetail` tanpa membocorkan stack trace atau secret.
- [x] `PostgresRepository.health()` memverifikasi bahwa `policy_chunks` sudah ter-seed (`COUNT(*) > 0`).
- [x] `monitoring_summary()` menyertakan `abstain_count`, `abstain_rate`, dan `blocked_count`.
- [x] `README.md` mencantumkan persona yang akurat sesuai `data/employees.json` dan `demo_personas.json`.
- [x] `templates/project-brief.md`, `templates/evaluation-report.md`, dan `templates/demo-script.md` terisi lengkap.
- [x] Seluruh test non-live (`pytest -m "not live"`) lulus 100%.

---

## Checkpoint & Catatan Implementasi

- **RFC-7807 ProblemDetail Exception Handlers (`src/api.py`):**
  - Ditambahkan handler untuk `HTTPException` yang memetakan kode status (401 Unauthorized, 403 Forbidden, 404 Not found, 409 Conflict) ke struktur JSON standar `ProblemDetail`. Field `detail` tetap tersedia untuk kompatibilitas penuh dengan Streamlit UI (`app.py`).
  - Ditambahkan handler untuk `Exception` tak terduga (500 Internal server error) yang menyamarkan error tanpa membocorkan stack trace mentah atau kredensial internal.
- **Readiness Policy Index Check (`src/repository.py`):**
  - `PostgresRepository.health()` kini memverifikasi bahwa tabel `policy_chunks` ada dan memiliki data hasil seed (`SELECT COUNT(*) AS chunk_count FROM policy_chunks`, memastikan `chunk_count > 0`), sehingga endpoint `/readyz` benar-benar mencerminkan kesiapan hybrid retrieval.
- **Metrik Monitoring Tambahan (`src/repository.py`):**
  - `MemoryRepository.monitoring_summary()` dan `PostgresRepository.monitoring_summary()` diperkaya dengan `abstain_count`, `abstain_rate`, dan `blocked_count` tanpa merusak field metrik yang sudah ada (`total_traces`, `error_count`, `p95_latency_ms`, dll).
- **Pembersihan Dokumentasi & Persona (`README.md`):**
  - Persona Citra Dewi (`EMP-003`) dihapus dari tabel matriks otorisasi dan teks petunjuk UI.
  - Nama persona Bima disesuaikan menjadi Bima Santoso (`EMP-002`) dan Admin disesuaikan menjadi Monitoring Admin (`ADM-001`) sesuai katalog `data/employees.json`.
- **Pengisian Template Deliverables:**
  - `templates/project-brief.md`: Terisi lengkap dengan target user, pain point, in/out of scope, success criteria, dan production gaps.
  - `templates/evaluation-report.md`: Terisi lengkap dengan metrik evaluasi aktual (15/15 passed, recall@3 100%, p50/p95 latency, zero critical failures, GO/release decision, dan regression cases).
  - `templates/demo-script.md`: Terisi panduan presentasi 5–7 menit (langkah 1 s/d 7 dengan prompt nyata dan ekspektasi per persona) serta daftar backup artifact.
- **Unit Tests:**
  - Ditambahkan test `test_api_errors_return_rfc7807_problem_detail` di `tests/self_test_api_docker.py` untuk memvalidasi error 401, 403, dan 404 menghasilkan kontrak RFC-7807.
  - Seluruh test di `self_test_api_docker.py`, `test_api.py`, `self_test_setup_and_retrieval.py`, `test_retrieval_security.py`, `test_agent_reliability.py`, `test_tools.py`, dan `self_test_tools_agent.py` lulus 100%.
