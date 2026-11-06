# WBS-07 — Implementasi `src/setup_lab.py`

- **Target:** `chunk_policy` dan `reset_and_seed`.
- **Owner:** Agent AI; schema dan seed data direview pemilik repo.
- **Dependency:** WBS-02, WBS-04, WBS-06.
- **Status:** CHECKPOINT - IMPLEMENTED

## Pekerjaan

1. Parse front matter policy dan section Markdown secara deterministik.
2. Buat stable chunk ID serta pertahankan document/version/effective-date metadata.
3. Buat schema/index PostgreSQL dan pgvector.
4. Hash identity token, seed balances/history, batch embed, dan upsert chunks.
5. Dukung mode reset dan mode seed non-destructive sesuai `docker-delivery.md`.

## Acceptance criteria

- `test_policy_chunk_ids_and_metadata_are_stable` lulus.
- Dimensi embedding sama dengan `EMBEDDING_DIMENSIONS`.
- Seed dapat dijalankan dari container tanpa API key saat build.

## Checkpoint

- `chunk_policy` memvalidasi front matter, mempertahankan metadata dokumen, dan membuat
  chunk ID deterministik berdasarkan document/version/section/content.
- `reset_and_seed` membaca fixture employees dan policy secara terurut, membuat extension
  vector serta tabel dasar PostgreSQL, menyimpan token hanya sebagai SHA-256 hash, dan
  melakukan upsert idempotent untuk employee, saldo, serta policy chunks.
- Embedding dijalankan batch; provider live dipakai hanya jika konfigurasi live siap,
  sedangkan deterministic fallback menjaga seed lokal tidak membutuhkan API key.
- CLI mendukung `python -m src.setup_lab --reset` maupun mode seed non-destructive.

## TODO berikutnya

1. Tambahkan schema/tabel lengkap untuk historical requests, proposals, tickets, dan traces
   sesuai kontrak `PostgresRepository`.
2. Implementasikan test seed dengan PostgreSQL/fixture terisolasi, termasuk validasi dimensi,
   idempotency, reset, dan token raw tidak tersimpan.
3. Hubungkan schema ini dengan `PostgresRepository` dan retrieval pgvector; jangan membuat
   setup lab menjadi sumber kebenaran terpisah.
4. Verifikasi seed container end-to-end setelah service PostgreSQL tersedia.
