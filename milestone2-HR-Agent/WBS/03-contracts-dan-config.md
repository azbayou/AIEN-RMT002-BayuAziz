# WBS-03 — Review `src/contracts.py` dan `src/config.py`

- **Target:** kontrak Pydantic dan konfigurasi runtime.
- **Owner:** Agent AI; perubahan kontrak direview pemilik repo.
- **Dependency:** WBS-00.
- **Status:** DONE

## Pekerjaan

1. Verifikasi semua request/response cocok dengan `brief.md` dan UI (`app.py`, `ui_contract.py`).
2. Tambahkan validator keamanan: penolakan whitespace blank, batas panjang payload, pencegahan parameter injection (`extra="forbid"`).
3. Validasi runtime setting: database URL, Redis URL, dimensi embedding, batas token, timeout, dan budget.
4. Pastikan pembedaan tegas antara fake mode untuk pengujian dan live mode untuk runtime production.
5. Hubungkan evaluasi kesiapan (`configuration_ready`) dengan dependensi operasional (`database`, `cache`, `configuration`).

## Acceptance criteria

- Tidak ada perubahan breaking pada `ui_contract.py` dan `app.py`.
- Input invalid menghasilkan validation error yang aman (`ProblemDetail` status 422 tanpa bocor stack trace/secret).
- `live_model_ready` tidak menjadi satu-satunya readiness check; terhubung dengan health database dan Redis pada `/readyz`.
- Pengujian unit contracts dan config lulus 100%.

## Hasil pelaksanaan dan refleksi

- Kontrak Pydantic sepenuhnya selaras dengan kebutuhan client UI Streamlit dan evaluasi:
  - `ChatRequest` menolak teks kosong atau spasi murni dan membatasi ukuran input.
  - `ConfirmActionRequest` menegakkan panjang idempotency key minimal 8 karakter.
  - Seluruh skema tool (`PrepareLeaveArgs`, `SearchPolicyArgs`, `TicketArgs`) menerapkan `extra="forbid"`
    untuk memblokir injeksi argumen atau percobaan spoofing employee ID.
  - `ProblemDetail` sesuai spesifikasi RFC 7807 untuk standarisasi format galat API.
- Konfigurasi `Settings`:
  - Menolak URL service tanpa scheme (misal `localhost:5432`).
  - Menolak nilai kosong untuk metadata penting (`app_name`, `environment`, `policy_index_version`).
  - Menormalisasi string kosong menjadi `None` untuk secret dan URL opsional.
  - Membatasi `model_mode` hanya ke `"live"` atau `"fake"`.
  - Menentukan status `configuration_ready` secara modular: pada mode `fake` cukup dependensi storage,
    sedangkan mode `live` mewajibkan `OPENAI_API_KEY`, `AGENT_MODEL`, dan `EMBEDDING_MODEL`.
- Endpoint `/readyz` pada `src/api.py` telah memetakan `repository.health()`, `cache.health()`, dan
  `settings.configuration_ready` ke dalam status readiness agregat dan rincian dependensi.

## Checkpoint 2026-11-07 — FINAL

- Status: **DONE**
- Bukti:
  - `tests/self_test_contracts_config.py`: 10 contract & config tests passed
  - `tests/test_domain.py`: validasi tipe cuti dan lead time passed
  - `tests/test_supplied_ui.py`: persona contract dan UI routing passed
  - Total non-live test suite: 55 passed, 0 failed
- Hard gates terkait (Identity Binding, Pending-only Action, Explicit Confirmation): TERPENUHI pada level kontrak schema.
