# WBS-04 — Implementasi `src/repository.py`

- **Target:** `MemoryRepository` dan `PostgresRepository`.
- **Owner:** Agent AI untuk MemoryRepository; pemilik repo memimpin schema/transaksi PostgreSQL.
- **Dependency:** WBS-01, WBS-02, WBS-03.
- **Status:** BELUM FINAL

## Pekerjaan

1. Implementasikan identity, balances, policy chunks, proposals, requests, tickets, traces.
2. Pastikan setiap query private-data memiliki owner predicate.
3. Gunakan parameterized SQL dan connection pool.
4. Implementasikan lexical search dan pgvector search.
5. Buat confirmation transaction dengan expiry, owner check, idempotency, dan conflict handling.
6. Sediakan health/readiness serta aggregate monitoring.

## Acceptance criteria

- `tests/test_actions.py` lulus.
- Wrong employee tidak pernah mendapat proposal/request/trace milik orang lain.
- Replay key sama tidak membuat duplicate.
- Semua request baru berstatus `pending_manager_review`.

## Hasil pelaksanaan dan refleksi

- `MemoryRepository` sekarang menyediakan identity sintetis, autentikasi berbasis hash token,
  saldo, policy chunks, proposal, leave request, ticket, trace, health, dan ringkasan
  monitoring.
- Data private dibaca berdasarkan `employee_id`; proposal hanya dapat dikonfirmasi oleh
  owner, dan daftar leave request dipisahkan per employee.
- Konfirmasi dilindungi lock in-memory, memeriksa expiry, mengembalikan request yang sama
  untuk idempotency key yang sama, serta menolak key berbeda sebagai conflict. Semua request
  baru berstatus `pending_manager_review`.
- Penyimpanan trace dan ticket melewati redaction sebelum disimpan. Implementasi
  `PostgresRepository` belum diubah karena schema/transaksi PostgreSQL secara eksplisit
  menjadi tanggung jawab pemilik repo pada WBS ini.

## User Note

- `def __init__(self)` masih di harcode.

### TODO checkpoint

- Ganti identity hardcode di `MemoryRepository` dengan loader fixture dari
  `data/employees.json`; token tetap hanya disimpan sebagai hash.
- Implementasikan `PostgresRepository`, schema, connection pool, parameterized SQL,
  owner predicate, pgvector/lexical query, dan transaksi konfirmasi atomik.
- Tambahkan test isolasi owner untuk proposal, request, trace, dan ticket, termasuk
  replay key sama serta conflict key berbeda.
- Pastikan production path memakai PostgreSQL hasil seed, bukan data in-memory.

## Checkpoint 2026-11-06

- Status: **BELUM FINAL**; MemoryRepository action tests lulus, tetapi PostgresRepository
  masih `NotImplementedError` dan identity MemoryRepository masih fixture hardcode.
- Agent: implementasikan loader `data/employees.json` untuk test, lalu implementasikan
  PostgreSQL pool, schema query parameterized, owner predicates, vector/lexical search,
  transaksi confirmation, dan monitoring aggregation.
- Pemilik repo: review schema/transaksi PostgreSQL, migration/reset policy, dan acceptance
  data production sebelum seed dijalankan.