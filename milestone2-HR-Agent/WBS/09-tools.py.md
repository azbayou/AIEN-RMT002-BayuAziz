# WBS-09 — Implementasi `src/tools.py`

- **Target:** `TOOL_SCHEMAS` dan `ToolExecutor.execute`.
- **Owner:** Agent AI; action safety direview pemilik repo.
- **Dependency:** WBS-01, WBS-04, WBS-08.
- **Status:** DONE

## Pekerjaan

1. Definisikan empat tool ketat: `search_hr_policy`, `get_my_leave_balance`, `prepare_leave_request`, `create_hr_ticket`.
2. Terapkan `strict=True`, `additionalProperties=False`, dan properti wajib lengkap pada seluruh skema tool.
3. Validasi seluruh argumen melalui Pydantic contracts (`extra="forbid"`).
4. Ambil `employee_id` hanya dari `AuthContext`, tolak semua percobaan spoofing atau argumen ID eksternal.
5. Pastikan `prepare_leave_request` tidak membuat request final dan tiket menyimpan ringkasan yang aman.

## Acceptance criteria

- Tidak ada tool untuk approval cuti ataupun akses data pegawai lain.
- Prompt atau argumen yang meminta saldo pegawai lain ditolak; identitas hanya bersumber dari `AuthContext`.
- Proposal valid memiliki TTL, berstatus pending, dan menegakkan `requires_confirmation=True`.
- Seluruh unit tests tools lulus 100%.

## Hasil pelaksanaan dan refleksi

- Empat skema tool telah didefinisikan dengan parameter `strict: True` dan `additionalProperties: False`.
- Tool `get_my_leave_balance` tidak menerima parameter apa pun dan melempar `ValueError` bila diberikan argumen tambahan.
- `prepare_leave_request` menjalankan validasi domain (`validate_leave_request`), menyimpan proposal bert-TTL di repository,
  dan mengembalikan objek `ActionProposal` dengan `requires_confirmation=True`. Tidak ada entitas `leave_request` yang terbuat pada tahap ini.
- `create_hr_ticket` membuat tiket eskalasi yang terikat pada `auth.employee_id` dan ringkasannya diredaksi sebelum disimpan.
- Terverifikasi pada `tests/test_tools.py` dan `tests/self_test_tools_agent.py`.

## Checkpoint 2026-11-07 — FINAL

- Status: **DONE**
- Bukti:
  - `tests/test_tools.py`: 4 passed (`test_tool_schemas_are_strict_and_have_complete_required_properties`, `test_malformed_and_unknown_tool_calls_are_rejected`, `test_prepare_leave_is_identity_bound_and_does_not_create_request`, `test_prepare_leave_rejects_employee_id_spoofing`)
  - `tests/self_test_tools_agent.py`: 4 tool tests passed
  - Seluruh test non-live lulus 100%
- Hard gates terkait (Identity Binding, Pending-only Actions, Explicit Confirmation): TERPENUHI.
