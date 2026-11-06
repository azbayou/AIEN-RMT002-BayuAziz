# WBS-09 — Implementasi `src/tools.py`

- **Target:** `TOOL_SCHEMAS` dan `ToolExecutor.execute`.
- **Owner:** Agent AI; action safety direview pemilik repo.
- **Dependency:** WBS-01, WBS-04, WBS-08.
- **Status:** TODO

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
