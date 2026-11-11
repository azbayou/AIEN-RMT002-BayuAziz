# WBS-28-extra — Lampiran Surat Dokter (PDF/Gambar) untuk Cuti Sakit & Review UI Manager

- **Target:** `src/contracts.py`, `src/setup_lab.py`, `src/repository.py`, `src/api.py`, `app2.py`, `tests/self_test_api_docker.py`.
- **Owner:** Agent AI.
- **Dependency:** WBS-25-extra, WBS-27-extra.
- **Status:** DONE

## Batasan Scope & Guardrail Penilaian (Wajib Dipatuhi Agent)

- **Boleh diedit:** `src/contracts.py`, `src/setup_lab.py`, `src/repository.py`, `src/api.py`, `app2.py`, `tests/self_test_api_docker.py`, `WBS/28-extra-sick-leave-attachment-review.md`, `WBS/00-baseline-dan-definition-of-done.md`.
- **DILARANG KERAS diedit:** `requirements.txt`, `Dockerfile`, `app.py`, `ui_contract.py`, `demo_personas.json`, `src/tools.py`, `src/agent.py`, `tests/test_*.py` (test bawaan instruktur).
- **Kepatuhan Kebijakan Privasi Medis (`HR-LEAVE-002` / `data/policies/sick-leave.md`):**
  1. Kebijakan `HR-LEAVE-002` menetapkan: *"Cuti sakit lebih dari dua hari kerja berturut-turut memerlukan dokumen pendukung yang diserahkan langsung melalui sistem HR, bukan melalui percakapan asisten. Asisten tidak boleh meminta atau menyimpan diagnosis."*
  2. Oleh karena itu, file surat dokter (PDF/PNG/JPG) **DILARANG dikirim ke model LLM (`OpenAIProvider`) atau disimpan di dalam `traces`**.
  3. Unggah dokumen dilakukan melalui endpoint REST khusus sistem HR (`POST /api/v1/leave-requests/{request_id}/attachment` dengan JSON Base64 agar tidak membutuhkan `python-multipart`), disimpan secara aman menggunakan tipe native PostgreSQL/Neon **`BYTEA`** di tabel `leave_attachments`, dan **hanya** dapat dilihat oleh pemilik permohonan, Manajer langsung dari pegawai tersebut, atau HR Admin (`GET /api/v1/leave-requests/{request_id}/attachment`).

---

## Pekerjaan

### Task 1: Perbarui `LeaveRequestView` dan Tambahkan Kontrak Lampiran di `src/contracts.py`

1. Di `src/contracts.py`, tambahkan metadata lampiran opsional (ber-default `False` / `None` agar 100% *backward-compatible* dengan seluruh test lama) pada `LeaveRequestView`:

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
    has_attachment: bool = False
    attachment_filename: str | None = None
    attachment_content_type: str | None = None
    attachment_size_bytes: int | None = None
    attachment_uploaded_at: datetime | None = None
```

2. Di bagian bawah `src/contracts.py`, tambahkan kontrak request dan response untuk lampiran dokumen cuti sakit:

```python
class LeaveAttachmentUploadRequest(BaseModel):
    filename: str = Field(min_length=3, max_length=120)
    content_type: Literal["application/pdf", "image/png", "image/jpeg"]
    content_base64: str = Field(min_length=8, max_length=7_500_000)


class LeaveAttachmentView(BaseModel):
    request_id: str
    employee_id: str
    filename: str
    content_type: Literal["application/pdf", "image/png", "image/jpeg"]
    file_size_bytes: int = Field(ge=1, le=5_242_880)
    content_base64: str
    uploaded_at: datetime
```

---

### Task 2: Tambahkan Tabel `leave_attachments` (Native PostgreSQL/Neon `BYTEA`) di `src/setup_lab.py`

Pada fungsi `reset_and_seed` di `src/setup_lab.py`:
1. Jika `reset=True`, tambahkan `leave_attachments` ke statement `DROP TABLE IF EXISTS`.
2. Tambahkan DDL pembuatan tabel `leave_attachments` tepat setelah `approval_audit_logs`:

```sql
                CREATE TABLE IF NOT EXISTS leave_attachments (
                    request_id TEXT PRIMARY KEY REFERENCES leave_requests(request_id) ON DELETE CASCADE,
                    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL CHECK (content_type IN ('application/pdf', 'image/png', 'image/jpeg')),
                    file_size_bytes INTEGER NOT NULL CHECK (file_size_bytes > 0 AND file_size_bytes <= 5242880),
                    file_bytes BYTEA NOT NULL,
                    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
```

---

### Task 3: Implementasikan Penyimpanan & Isolasi Akses Lampiran di `src/repository.py`

1. Impor `base64` dan `LeaveAttachmentView` dari `.contracts` di `src/repository.py`.
2. Tambahkan 2 method ke `class Repository(Protocol)`:

```python
    def save_leave_attachment(
        self,
        employee_id: str,
        request_id: str,
        filename: str,
        content_type: str,
        file_bytes: bytes,
    ) -> LeaveAttachmentView: ...

    def get_leave_attachment(
        self,
        requester: AuthContext,
        request_id: str,
    ) -> LeaveAttachmentView: ...
```

3. **Pada `MemoryRepository`:**
   - Tambahkan `self.attachments: dict[str, dict[str, Any]] = {}` di `__init__`.
   - Buat helper internal `_enrich_with_attachment_meta(self, req: LeaveRequestView) -> LeaveRequestView` yang mengecek apakah `req.request_id` ada di `self.attachments`. Jika ada, salin metadata `has_attachment=True`, `attachment_filename`, `attachment_content_type`, `attachment_size_bytes`, dan `attachment_uploaded_at` ke `LeaveRequestView`. Gunakan helper ini di `list_leave_requests` dan `list_team_leave_requests`.
   - Implementasikan `save_leave_attachment`:
     - Cari `target_req` milik `employee_id` di `self.requests.get(employee_id, [])`. Jika tidak ditemukan, `raise KeyError("leave request not found")`.
     - **Guardrail 1 (Khusus Cuti Sakit):** Jika `target_req.leave_type != "sick"`, `raise ConflictError("attachment is only supported for sick leave requests")`.
     - **Guardrail 2 (Hanya Saat Pending):** Jika `target_req.status != "pending_manager_review"`, `raise ConflictError("cannot attach document to finalized leave request")`.
     - Simpan di `self.attachments[request_id]` dan kembalikan `LeaveAttachmentView(...)` dengan `content_base64=base64.b64encode(file_bytes).decode("ascii")`.
   - Implementasikan `get_leave_attachment`:
     - Cari permohonan `request_id` beserta `owner_id`-nya di `self.requests`. Jika tidak ada atau belum punya lampiran di `self.attachments`, `raise KeyError("attachment not found")`.
     - **Guardrail 3 (Isolasi Otorisasi Pemilik / Manager Tim / Admin):**
       - Ambil `owner_ctx = self.identities.get(owner_id, (None, None))[0]`.
       - Izinkan akses **HANYA** jika:
         - `requester.employee_id == owner_id` (pemilik cuti sendiri), ATAU
         - `requester.role == "monitoring_admin"`, ATAU
         - `requester.role == "manager"` dan `owner_ctx is not None` dan `owner_ctx.manager_id == requester.employee_id`.
       - Jika tidak memenuhi salah satu syarat di atas, `raise PermissionError("not authorized to view this attachment")`.
     - Kembalikan `LeaveAttachmentView(...)`.

4. **Pada `PostgresRepository`:**
   - Perbarui query `SELECT` di `list_leave_requests` dan `list_team_leave_requests` dengan `LEFT JOIN leave_attachments a ON a.request_id = r.request_id` untuk mengambil:
     ```sql
     (a.request_id IS NOT NULL) AS has_attachment,
     a.filename AS attachment_filename,
     a.content_type AS attachment_content_type,
     a.file_size_bytes AS attachment_size_bytes,
     a.uploaded_at AS attachment_uploaded_at
     ```
   - Implementasikan `save_leave_attachment` di dalam transaksi (`SELECT leave_type, status FROM leave_requests WHERE request_id = %s AND employee_id = %s FOR UPDATE`), validasi `leave_type == 'sick'` dan `status == 'pending_manager_review'`, lalu lakukan `INSERT INTO leave_attachments ... ON CONFLICT (request_id) DO UPDATE ...` dengan kolom `file_bytes` bertipe `bytes` (`BYTEA`).
   - Implementasikan `get_leave_attachment` dengan `JOIN employees e ON e.employee_id = r.employee_id`, validasi otorisasi (`requester.employee_id == owner_id`, `monitoring_admin`, atau `manager` dengan `e.manager_id == requester.employee_id`), lalu konversi ` bytes(row["file_bytes"])` menjadi Base64 string pada `LeaveAttachmentView`.

---

### Task 4: Tambahkan Endpoint Upload & Preview Lampiran beserta Validasi Magic Bytes di `src/api.py`

1. Impor `LeaveAttachmentUploadRequest, LeaveAttachmentView` dari `.contracts` di `src/api.py`.
2. Buat helper validasi ukuran dan *magic bytes* file agar pengguna tidak bisa mengunggah file berbahaya yang disamarkan sebagai PDF/gambar:

```python
def _validate_attachment_bytes(content_type: str, data: bytes) -> None:
    if len(data) < 4 or len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="Attachment size must be between 4 bytes and 5 MB")
    if content_type == "application/pdf" and not data.startswith(b"%PDF-"):
        raise HTTPException(status_code=422, detail="File payload is not a valid PDF document")
    if content_type == "image/png" and not data.startswith(b"\x89PNG"):
        raise HTTPException(status_code=422, detail="File payload is not a valid PNG image")
    if content_type == "image/jpeg" and not data.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=422, detail="File payload is not a valid JPEG image")
```

3. Tambahkan 2 endpoint di `create_app`:

```python
    @app.post("/api/v1/leave-requests/{request_id}/attachment", response_model=LeaveAttachmentView)
    def upload_leave_attachment(
        request_id: str,
        payload: LeaveAttachmentUploadRequest,
        auth: AuthContext = Depends(current_auth),
    ) -> LeaveAttachmentView:
        try:
            raw_b64 = payload.content_base64.split(",")[-1].strip()
            file_bytes = base64.b64decode(raw_b64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=422, detail="Invalid base64 attachment payload")

        _validate_attachment_bytes(payload.content_type, file_bytes)
        safe_filename = re.sub(r"[^A-Za-z0-9._-]", "_", payload.filename.strip()) or "attachment"

        try:
            return repository.save_leave_attachment(
                employee_id=auth.employee_id,
                request_id=request_id,
                filename=safe_filename,
                content_type=payload.content_type,
                file_bytes=file_bytes,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Leave request not found")
        except ConflictError as error:
            raise HTTPException(status_code=409, detail=redact(str(error)))

    @app.get("/api/v1/leave-requests/{request_id}/attachment", response_model=LeaveAttachmentView)
    def get_leave_attachment(
        request_id: str,
        auth: AuthContext = Depends(current_auth),
    ) -> LeaveAttachmentView:
        try:
            return repository.get_leave_attachment(auth, request_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Attachment not found")
        except PermissionError:
            raise HTTPException(status_code=403, detail="Not authorized to view this attachment")
```

---

### Task 5: Integrasikan Upload Surat Dokter & Preview Manager di `app2.py`

1. **Pada Modal Formulir Pengajuan Cuti (`render_leave_form` di `app2.py`) & Kartu Konfirmasi Proposal (`proposal['leave_type'] == 'sick'`):**
   - Ketika `leave_type == "sick"`, tampilkan komponen `st.file_uploader("📎 Lampirkan Surat Dokter / Dokumen Pendukung (PDF, PNG, JPG — Maks 5 MB)", type=["pdf", "png", "jpg", "jpeg"])`.
   - Simpan file yang dipilih ke `st.session_state["pending_sick_attachment"] = {"filename": uploaded.name, "content_type": uploaded.type, "content_base64": base64.b64encode(uploaded.getvalue()).decode("ascii")}`.
   - Saat pegawai menekan **`✅ Konfirmasi Pengajuan`** pada proposal cuti sakit dan konfirmasi berhasil menghasilkan `confirmed["request_id"]`, jika `st.session_state.get("pending_sick_attachment")` tersedia, langsung panggil `POST /api/v1/leave-requests/{confirmed['request_id']}/attachment` dan tampilkan pesan sukses bahwa surat dokter berhasil dilampirkan!

2. **Pada Tab "📋 Permintaan Cuti Saya" (`tab_requests` di `app2.py`):**
   - Untuk setiap item cuti dengan `leave_type == "sick"`:
     - Tampilkan badge status lampiran: `📎 Lampiran: {attachment_filename}` jika `has_attachment == True`, atau `⚠️ Belum ada lampiran surat dokter` jika `has_attachment == False`.
     - Jika status masih `pending_manager_review`, sediakan `st.expander("📎 Unggah / Perbarui Surat Dokter (PDF / Gambar)")` dengan `st.file_uploader` dan tombol **"⬆️ Simpan Lampiran"** agar pegawai tetap bisa menyusulkan surat dokter kapan saja sebelum di-review manajer.

3. **Pada Tab "✅ Persetujuan Cuti Tim" (`tab_team_approval` khusus Manager & Admin di `app2.py`):**
   - Pada setiap kartu permohonan cuti yang sedang `pending_manager_review` (maupun di riwayat):
     - Jika `leave_type == "sick"`, tampilkan indikator apakah surat dokter sudah dilampirkan (`📎 Lampiran Surat Dokter: {attachment_filename}` atau peringatan `⚠️ Pegawai belum melampirkan surat dokter`).
     - Jika `req.get("has_attachment")` bernilai `True`, tampilkan `st.expander(f"📄 Tinjau Lampiran Surat Dokter: {req.get('attachment_filename')}")`:
       - Di dalam expander, panggil `GET /api/v1/leave-requests/{req_id}/attachment`.
       - Jika `content_type` adalah `image/png` atau `image/jpeg`: tampilkan pratinjau gambar langsung menggunakan `st.image(raw_bytes, caption=...)` beserta `st.download_button(...)`.
       - Jika `content_type` adalah `application/pdf`: tampilkan *embedded PDF viewer* menggunakan `<iframe src="data:application/pdf;base64,{b64_data}" width="100%" height="450px" style="border: 1px solid #334155; border-radius: 8px;"></iframe>` serta tombol `st.download_button("📥 Unduh PDF Surat Dokter", data=raw_bytes, file_name=..., mime="application/pdf")`.

---

### Task 6: Tambahkan Unit & Integration Test di `tests/self_test_api_docker.py`

Tambahkan test `test_sick_leave_attachment_upload_and_manager_review_isolation(api_client: TestClient)` di `tests/self_test_api_docker.py`:
1. Buat dan konfirmasi proposal cuti `sick` (`AP-SICK-01`) dan cuti `annual` (`AP-ANN-01`) untuk Alya (`EMP-001`).
2. **Guardrail Jenis Cuti:** Alya mencoba mengunggah PDF ke cuti `annual` (`AP-ANN-01`) → ditolak `409 Conflict`.
3. **Guardrail Magic Bytes:** Alya mencoba mengunggah file teks biasa yang diklaim sebagai `application/pdf` ke `AP-SICK-01` → ditolak `422`.
4. **Upload Valid (PDF & PNG):** Alya mengunggah PDF valid (`b"%PDF-1.4 surat keterangan sakit dokter..."`) ke `AP-SICK-01` → berhasil `200 OK`, dan `GET /api/v1/leave-requests/me` menampilkan `has_attachment == True` dan `attachment_filename`.
5. **Guardrail Isolasi Privasi Medis:** Pegawai lain (`AUTH_BIMA` / `EMP-002`) mencoba mengakses `GET /api/v1/leave-requests/AP-SICK-01/attachment` → ditolak `403 Forbidden`.
6. **Review oleh Manajer Tim:** Manajer Alya (`Authorization: Bearer token-manager` / `MGR-001`) memanggil `GET /api/v1/manager/leave-requests` (melihat `has_attachment == True`), mengambil dokumen via `GET /api/v1/leave-requests/AP-SICK-01/attachment` (`200 OK`, isi PDF sesuai), lalu menyetujui cuti sakit tersebut (`POST /api/v1/manager/leave-requests/AP-SICK-01/review`).
7. **Guardrail Immutability Pasca-Finalisasi:** Setelah berstatus `approved`, percobaan mengunggah ulang lampiran pada `AP-SICK-01` ditolak dengan `409 Conflict`.

---

## Langkah Verifikasi

```bash
/home/bay/miniconda3/envs/hr-agent/bin/pytest tests/self_test_api_docker.py -v
/home/bay/miniconda3/envs/hr-agent/bin/pytest -m "not live"
```

## Acceptance Criteria

- [x] Tidak ada tambahan dependency baru di `requirements.txt`.
- [x] Hanya permohonan cuti sakit (`leave_type == "sick"`) berstatus `pending_manager_review` yang dapat dilampiri file PDF/PNG/JPG.
- [x] Validasi *magic bytes* (`%PDF-`, `\x89PNG`, `\xff\xd8\xff`) dan ukuran maksimum (≤ 5 MB) berjalan ketat.
- [x] Dokumen tersimpan di kolom `BYTEA` PostgreSQL/Neon (`leave_attachments`) dan **tidak pernah** dikirim ke LLM atau disimpan di `traces` (100% patuh kebijakan `HR-LEAVE-002`).
- [x] Hanya pemilik cuti, Manajer langsung dari pegawai tersebut, dan Monitoring Admin yang dapat melihat/mengunduh lampiran (`403 Forbidden` untuk pegawai lain).
- [x] Manajer dapat meninjau pratinjau Gambar/PDF langsung di Tab **"✅ Persetujuan Cuti Tim"** pada `app2.py` sebelum menekan tombol Setujui/Tolak.
- [x] Seluruh test instruktur (`pytest -m "not live"`) dan `self_test_*.py` lulus 100%.
