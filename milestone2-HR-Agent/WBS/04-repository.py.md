# WBS-04 — Implementasi `src/repository.py`

- **Target:** `MemoryRepository` dan `PostgresRepository`.
- **Owner:** Agent AI; pemilik repo melakukan review schema, migration, dan acceptance production.
- **Dependency:** WBS-01, WBS-02, WBS-03.
- **Status:** DONE

## Pekerjaan

1. Implementasikan identity, balances, policy chunks, proposals, requests, tickets, traces.
2. Muat identitas dan saldo dari `data/employees.json` secara dinamis (tanpa hardcode di Python).
3. Pastikan setiap query private-data memiliki owner predicate.
4. Gunakan parameterized SQL dan connection pool pada `PostgresRepository`.
5. Implementasikan lexical search dan pgvector search.
6. Buat confirmation transaction dengan expiry, owner check, idempotency, dan conflict handling.
7. Sediakan health/readiness serta aggregate monitoring.

## Acceptance criteria

- `tests/test_actions.py` lulus (6 passed).
- Wrong employee tidak pernah mendapat proposal/request/trace milik orang lain.
- Replay key sama tidak membuat duplicate (`idempotent_replay=True`).
- Semua request baru berstatus `pending_manager_review`.
- Inisialisasi `MemoryRepository` mengambil data dari `data/employees.json` dengan token ber-hash SHA-256.

## Hasil pelaksanaan dan refleksi

- `MemoryRepository` sekarang memuat data dari `data/employees.json` secara dinamis menggunakan
  helper `_load_employees()`, menghilangkan seluruh hardcode identitas dan saldo dari kode sumber.
  Token autentikasi langsung di-hash menggunakan `token_hash` dan raw token tidak pernah disimpan.
- Data private dibaca secara ketat berdasarkan `employee_id`; proposal hanya dapat dikonfirmasi oleh
  owner, dan daftar leave request dipisahkan per employee.
- Konfirmasi proposal dilindungi lock in-memory, memeriksa expiry waktu, mengembalikan request yang sama
  untuk idempotency key yang sama, serta melempar `ConflictError` untuk key berbeda pada proposal yang sudah dikonfirmasi.
  Semua status request baru terkunci pada `pending_manager_review`.
- Penyimpanan trace dan ticket melewati redaction sebelum disimpan (`redact_trace` rekursif).
- `PostgresRepository` memakai `psycopg_pool.ConnectionPool`, query terparameterisasi,
  owner predicate, lexical search PostgreSQL `tsvector`/`ts_rank`, pgvector cosine distance search (`<=>`),
  serta transaksi row-level locking `FOR UPDATE` untuk mencegah race condition.

## Checkpoint 2026-11-07 — FINAL

- Status: **DONE**
- Bukti:
  - `tests/test_actions.py`: 6 passed
  - `test_repository_state_is_scoped_by_employee`: passed (IDOR boundary terverifikasi)
  - `test_concurrent_confirmation_creates_one_request`: passed (thread safety terverifikasi)
  - `tests/self_test_contracts_config.py` & regression suite: passed
- Hard gates terkait (Identity Binding, Pending-only Action, Explicit Confirmation & Idempotency): TERPENUHI.
