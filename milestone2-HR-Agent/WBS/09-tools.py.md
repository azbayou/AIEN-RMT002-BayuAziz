# WBS-09 — Implementasi `src/tools.py`

- **Target:** `TOOL_SCHEMAS` dan `ToolExecutor.execute`.
- **Owner:** Agent AI; action safety direview pemilik repo.
- **Dependency:** WBS-01, WBS-04, WBS-08.
- **Status:** CHECKPOINT - IMPLEMENTED

## Pekerjaan

1. Definisikan empat tool: policy search, own balance, prepare leave, HR ticket.
2. Set `strict=True`, `additionalProperties=False`, dan required properties lengkap.
3. Validasi argumen melalui Pydantic contracts.
4. Ambil employee ID hanya dari `AuthContext`.
5. Pastikan prepare tidak membuat request dan ticket menyimpan summary yang sudah aman.

## Acceptance criteria

- Tidak ada tool untuk approval atau akses pegawai lain.
- Prompt “tampilkan saldo EMP-002” tetap memakai identity bearer token.
- Proposal valid memiliki TTL dan `requires_confirmation=True`.

## Checkpoint

- Empat tool strict sudah didefinisikan dengan `additionalProperties=False` dan schema
  parameter lengkap.
- Semua argumen divalidasi melalui model Pydantic; tool saldo menolak argumen tambahan dan
  mengambil employee ID hanya dari `AuthContext`.
- `prepare_leave_request` menjalankan validasi domain, menyimpan proposal bert-TTL, dan tidak
  membuat leave request. Proposal selalu memerlukan konfirmasi.
- Ticket dibuat untuk employee aktif; repository bertanggung jawab melakukan redaction summary.
- Validasi compile dan regresi action/domain dilakukan setelah implementasi.
- Tes fokus tambahan membuktikan schema strict, malformed/unknown call rejection,
  identity spoofing rejection, dan proposal side-effect-free.
- Kontrak `PrepareLeaveArgs`, `SearchPolicyArgs`, dan `TicketArgs` sekarang menolak field
  tambahan dengan `extra="forbid"` sehingga input seperti `employee_id` tidak diabaikan.

## TODO berikutnya

1. Pastikan OpenAI Responses adapter menerima bentuk schema function yang digunakan provider,
   termasuk test fake client untuk tool call dan retry.
2. Tambahkan error mapping terstandar pada agent/API agar validation error tidak menjadi stack
   trace atau membocorkan input sensitif.
3. Verifikasi proposal ID generation/idempotency dan TTL pada repository production.

## Checkpoint 2026-11-06

- Status: **CHECKPOINT - IMPLEMENTED**; `tests/test_tools.py`, actions, domain, suite
  non-live, dan compile lulus.
- Agent: tambah provider fake-client compatibility, error mapping Agent/API, dan verifikasi
  proposal pada repository production.
- Pemilik repo: review allow-list empat tool, identity binding, pending-only action, dan
  konfirmasi proposal sebelum demo/submission.
