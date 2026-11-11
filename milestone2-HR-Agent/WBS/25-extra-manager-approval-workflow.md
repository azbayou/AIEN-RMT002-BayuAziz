# WBS-25-extra — Role Manager & Workflow Human-in-the-Loop Leave Approval

- **Target:** `src/contracts.py`, `src/setup_lab.py`, `src/repository.py`, `src/api.py`, `app2.py`, `tests/self_test_api_docker.py`.
- **Owner:** Agent AI.
- **Dependency:** WBS-20-P1, WBS-24-extra.
- **Status:** DONE

## Batasan Scope & Guardrail Penilaian (Wajib Dipatuhi Agent)

- **Boleh diedit:** `src/contracts.py`, `src/setup_lab.py`, `src/repository.py`, `src/api.py`, `app2.py`, `tests/self_test_api_docker.py`.
- **DILARANG KERAS diedit:** `src/tools.py`, `src/agent.py`, `app.py`, `tests/test_actions.py`, `tests/test_tools.py`.
- **ATURAN EMAS HARD GATE (WAJIB DIPATUHI):**
  1. **DILARANG membuat tool LLM untuk menyetujui cuti** (tidak boleh ada tool `approve_leave` di `src/tools.py`).
  2. **Endpoint konfirmasi pegawai (`POST /api/v1/action-proposals/{proposal_id}/confirm`) WAJIB tetap selalu menghasilkan `status = "pending_manager_review"`.**
  3. Perubahan status dari `pending_manager_review` menjadi `approved` atau `rejected` **HANYA** boleh terjadi melalui endpoint REST khusus manusia (Manager): `POST /api/v1/manager/leave-requests/{request_id}/review`.

---

## Pekerjaan

### Task 1: Tambahkan Kontrak Review Cuti Manager di `src/contracts.py`

1. Perbarui `LeaveRequestView` di `src/contracts.py` (sekitar baris 81) dengan field opsional ber-default agar 100% backward-compatible dengan test lama:

```python
class LeaveRequestView(BaseModel):
    request_id: str
    leave_type: str
    start_date: date
    end_date: date
    business_days: int
    status: str
    created_at: datetime
    employee_id: str | None = None
    employee_name: str | None = None
    reviewed_by: str | None = None
    review_note: str | None = None
    reviewed_at: datetime | None = None
```

2. Tambahkan kontrak request/response untuk review Manager di bagian bawah `src/contracts.py`:

```python
class ManagerReviewRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    review_note: str = Field(default="Reviewed by manager", min_length=3, max_length=300)


class ManagerReviewResult(BaseModel):
    request_id: str
    employee_id: str
    status: Literal["approved", "rejected"]
    reviewed_by: str
    review_note: str
    reviewed_at: datetime
    audit_reference: str
```

### Task 2: Perbarui Schema Tabel `leave_requests` dan Buat Tabel `approval_audit_logs` di `src/setup_lab.py`

Pada fungsi `reset_and_seed` di `src/setup_lab.py` (sekitar baris 141):
1. Jika `reset=True`, tambahkan `approval_audit_logs` ke daftar `DROP TABLE IF EXISTS`.
2. Ubah definisi `leave_requests` dan tambahkan migrasi idempotent serta tabel `approval_audit_logs`:

```sql
                CREATE TABLE IF NOT EXISTS leave_requests (
                    request_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL UNIQUE REFERENCES action_proposals(proposal_id),
                    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
                    leave_type TEXT NOT NULL,
                    start_date DATE NOT NULL,
                    end_date DATE NOT NULL,
                    business_days INTEGER NOT NULL CHECK (business_days > 0),
                    status TEXT NOT NULL DEFAULT 'pending_manager_review'
                        CHECK (status IN ('pending_manager_review', 'approved', 'rejected', 'cancelled')),
                    idempotency_key TEXT NOT NULL,
                    reviewed_by TEXT REFERENCES employees(employee_id),
                    review_note TEXT,
                    reviewed_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (employee_id, idempotency_key)
                );
                ALTER TABLE leave_requests ADD COLUMN IF NOT EXISTS reviewed_by TEXT;
                ALTER TABLE leave_requests ADD COLUMN IF NOT EXISTS review_note TEXT;
                ALTER TABLE leave_requests ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;
                ALTER TABLE leave_requests DROP CONSTRAINT IF EXISTS leave_requests_status_check;
                ALTER TABLE leave_requests ADD CONSTRAINT leave_requests_status_check
                    CHECK (status IN ('pending_manager_review', 'approved', 'rejected', 'cancelled'));

                CREATE TABLE IF NOT EXISTS approval_audit_logs (
                    audit_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL REFERENCES leave_requests(request_id),
                    reviewer_id TEXT NOT NULL REFERENCES employees(employee_id),
                    previous_status TEXT NOT NULL,
                    new_status TEXT NOT NULL CHECK (new_status IN ('approved', 'rejected')),
                    review_note TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
```

### Task 3: Implementasikan Logika Hierarki Manager, Potong Saldo Permanen Saat `approved`, dan Audit Log di `src/repository.py`

1. Impor `ManagerReviewResult` dari `.contracts` di `src/repository.py`.
2. Tambahkan 2 method ke `class Repository(Protocol)`:
   ```python
   def list_team_leave_requests(self, manager_id: str, include_all_departments: bool = False) -> list[LeaveRequestView]: ...
   def review_leave_request(
       self,
       reviewer_id: str,
       request_id: str,
       decision: str,
       review_note: str,
       is_admin: bool = False,
   ) -> ManagerReviewResult: ...
   ```

3. **Pada `MemoryRepository`:**
   - Tambahkan `self.approval_audits: list[dict[str, Any]] = []` di `__init__`.
   - Saat membuat `LeaveRequestView` di `confirm_proposal`, isi juga `employee_id=owner` dan `employee_name=self.identities[owner][0].display_name`.
   - Implementasikan `list_team_leave_requests`:
     ```python
    def list_team_leave_requests(self, manager_id: str, include_all_departments: bool = False) -> list[LeaveRequestView]:
        items: list[LeaveRequestView] = []
        for emp_id, req_list in self.requests.items():
            ctx = self.identities.get(emp_id, (None, None))[0]
            if ctx is None:
                continue
            if include_all_departments or ctx.manager_id == manager_id:
                for req in req_list:
                    items.append(
                        req.model_copy(
                            update={"employee_id": emp_id, "employee_name": ctx.display_name},
                            deep=True,
                        )
                    )
        items.sort(key=lambda r: (r.created_at, r.request_id), reverse=True)
        return items
     ```
   - Implementasikan `review_leave_request`:
     - Cari `request` dengan `request_id` di seluruh `self.requests`. Jika tidak ditemukan, `raise KeyError("leave request not found")`.
     - **Guardrail 1 (No Self-Approval):** Jika `owner_id == reviewer_id`, `raise ConflictError("manager cannot review own leave request")`.
     - **Guardrail 2 (Subordinate Isolation):** Ambil `owner_ctx = self.identities[owner_id][0]`. Jika `not is_admin and owner_ctx.manager_id != reviewer_id`, `raise KeyError("leave request not found in manager team")`.
     - **Guardrail 3 (State Transition):** Jika `target_req.status != "pending_manager_review"`, `raise ConflictError(f"leave request already finalized as {target_req.status}")`.
     - **Guardrail 4 (Balance Deduction saat `approved`):**
       - Jika `decision == "approved"`: kurangi saldo dasar `self.balances[owner_id]` untuk `leave_type` tersebut sebesar `target_req.business_days` (pastikan `available_days >= target_req.business_days`, jika tidak `raise ConflictError("insufficient balance")`).
       - *(Catatan penting: karena di WBS-20 `get_balances` hanya mengurangi request yang berstatus `pending_manager_review`, maka begitu status berubah menjadi `approved` dan saldo dasar dikurangi `business_days`, saldo efektif tetap konsisten dan tidak terpotong dua kali! Sedangkan jika `decision == "rejected"`, saldo dasar tidak dikurangi dan karena status bukan lagi `pending_manager_review`, kuota yang tadinya di-reserve otomatis kembali ke pegawai!)*
     - Update `target_req.status = decision`, `target_req.reviewed_by = reviewer_id`, `target_req.review_note = redact(review_note)`, `target_req.reviewed_at = datetime.now(timezone.utc)`.
     - Simpan entri ke `self.approval_audits` dan kembalikan `ManagerReviewResult(...)`.

4. **Pada `PostgresRepository`:**
   - Implementasikan `list_team_leave_requests`:
     ```python
    def list_team_leave_requests(self, manager_id: str, include_all_departments: bool = False) -> list[LeaveRequestView]:
        with self.pool.connection() as connection:
            if include_all_departments:
                rows = connection.execute(
                    """
                    SELECT r.request_id, r.employee_id, e.display_name AS employee_name,
                           r.leave_type, r.start_date, r.end_date, r.business_days,
                           r.status, r.reviewed_by, r.review_note, r.reviewed_at, r.created_at
                    FROM leave_requests r
                    JOIN employees e ON e.employee_id = r.employee_id
                    ORDER BY r.created_at DESC, r.request_id
                    """
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT r.request_id, r.employee_id, e.display_name AS employee_name,
                           r.leave_type, r.start_date, r.end_date, r.business_days,
                           r.status, r.reviewed_by, r.review_note, r.reviewed_at, r.created_at
                    FROM leave_requests r
                    JOIN employees e ON e.employee_id = r.employee_id
                    WHERE e.manager_id = %s
                    ORDER BY r.created_at DESC, r.request_id
                    """,
                    (manager_id,),
                ).fetchall()
        return [LeaveRequestView(**row) for row in rows]
     ```
   - Implementasikan `review_leave_request` di dalam blok `with connection.transaction():` dengan `FOR UPDATE`:
     - Lock row `leave_requests` JOIN `employees` untuk memeriksa `employee_id`, `manager_id`, `status`, `leave_type`, dan `business_days`.
     - Terapkan 4 guardrail yang sama persis dengan `MemoryRepository` (No Self-Approval, Subordinate Isolation, `status == 'pending_manager_review'`, dan pemotongan `leave_balances.available_days = available_days - %s` saat `decision == 'approved'`).
     - Update `leave_requests` dan `INSERT INTO approval_audit_logs`.

### Task 4: Tambahkan Endpoint Manager Review di `src/api.py`

1. Impor `ManagerReviewRequest, ManagerReviewResult` dari `.contracts` di `src/api.py`.
2. Buat dependency `manager_auth`:
   ```python
    def manager_auth(auth: AuthContext = Depends(current_auth)) -> AuthContext:
        if auth.role not in ("manager", "monitoring_admin"):
            raise HTTPException(status_code=403, detail="Manager access required")
        return auth
   ```
3. Tambahkan 2 endpoint baru di `create_app`:
   ```python
    @app.get("/api/v1/manager/leave-requests", response_model=list[LeaveRequestView])
    def team_leave_requests(auth: AuthContext = Depends(manager_auth)) -> list[LeaveRequestView]:
        return repository.list_team_leave_requests(
            auth.employee_id,
            include_all_departments=(auth.role == "monitoring_admin"),
        )

    @app.post("/api/v1/manager/leave-requests/{request_id}/review", response_model=ManagerReviewResult)
    def review_leave_request(
        request_id: str,
        payload: ManagerReviewRequest,
        auth: AuthContext = Depends(manager_auth),
    ) -> ManagerReviewResult:
        try:
            return repository.review_leave_request(
                reviewer_id=auth.employee_id,
                request_id=request_id,
                decision=payload.decision,
                review_note=payload.review_note,
                is_admin=(auth.role == "monitoring_admin"),
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Leave request not found in your team")
        except ConflictError as error:
            raise HTTPException(status_code=409, detail=redact(str(error)))
   ```

### Task 5: Tambahkan Tab "✅ Persetujuan Cuti Tim" Khusus Manager di `app2.py`

Di `app2.py`:
1. Deteksi role pengguna yang sedang login:
   ```python
   user_role = persona.get("role") or ("monitoring_admin" if "ADM" in persona["employee_id"] else ("manager" if "MGR" in persona["employee_id"] else "employee"))
   is_manager = user_role in ("manager", "monitoring_admin")
   ```
2. Jika `is_manager` bernilai `True`, tambahkan tab **"✅ Persetujuan Cuti Tim"**:
   - Panggil `GET /api/v1/manager/leave-requests`.
   - Tampilkan metrik ringkas: **Menunggu Persetujuan**, **Disetujui**, **Ditolak**.
   - Untuk setiap request berstatus `pending_manager_review`, tampilkan kartu berisi nama bawahan (`employee_name`), ID pegawai, jenis cuti, rentang tanggal, jumlah hari kerja, input teks `Catatan Review Manajer`, serta 2 tombol berdampingan:
     - **✅ Setujui Permohonan** (`decision: "approved"`)
     - **❌ Tolak Permohonan** (`decision: "rejected"`)
   - Saat diklik, panggil `POST /api/v1/manager/leave-requests/{request_id}/review`, tampilkan notifikasi sukses beserta nomor referensi audit (`audit_reference`), lalu `st.rerun()`.

### Task 6: Tambahkan Unit Test di `tests/self_test_api_docker.py`

Tambahkan test `test_manager_leave_review_lifecycle_and_balance_deduction(api_client: TestClient)`:
- Simpan proposal cuti `annual` 2 hari untuk Alya (`EMP-001`, saldo awal 8) dan konfirmasi menggunakan `AUTH_ALYA` → status `pending_manager_review`, saldo efektif Alya menjadi `6`.
- Pegawai biasa (`AUTH_BIMA`) mencoba memanggil `POST /api/v1/manager/leave-requests/AP-1/review` → ditolak dengan `403`.
- Manager (`Authorization: Bearer token-manager`) memanggil `GET /api/v1/manager/leave-requests` → melihat request milik Alya.
- Manager menyetujui (`decision: "approved"`) → status berubah menjadi `"approved"`, saldo Alya tetap `6` (dipotong permanen), dan percobaan review ulang menghasilkan `409 Conflict`.
- Buat proposal kedua 2 hari untuk Bima (`EMP-002`, saldo awal 3), konfirmasi (saldo efektif Bima menjadi `1`), lalu Manager menolak (`decision: "rejected"`) → kuota Bima kembali pulih menjadi `3`.

---

## Langkah Verifikasi

```bash
pytest tests/test_actions.py tests/self_test_api_docker.py -v
pytest -m "not live"
```

## Acceptance Criteria

- [x] AI Agent dan endpoint `/confirm` tetap 100% hanya membuat status `pending_manager_review` (tidak melanggar Hard Gate).
- [x] Pegawai biasa (`role == "employee"`) mendapat 403 jika mencoba mengakses endpoint `/api/v1/manager/*`.
- [x] Manager tidak dapat me-review permohonan cuti miliknya sendiri (409 Conflict) atau pegawai di luar timnya (404 Not Found).
- [x] Saat Manager meng-approve, saldo cuti dipotong permanen secara atomik dan tercatat di audit log; saat me-reject, saldo yang di-reserve otomatis kembali.
- [x] Seluruh test non-live lulus 100%.

## Catatan Eksekusi & Hasil Pengujian
- `pytest tests/test_actions.py tests/self_test_api_docker.py -v`: 15 passed, 1 skipped (0.75s).
- `RUN_POSTGRES_TESTS=1 pytest tests/self_test_api_docker.py -v`: 10 passed (5.87s).
- `pytest -m "not live"`: 38 passed, 2 skipped, 1 deselected (1.47s).
- Seluruh 4 guardrail (No Self-Approval, Subordinate Isolation, State Transition, dan Balance Deduction / Restoration) terverifikasi berjalan sempurna pada MemoryRepository dan PostgresRepository.
