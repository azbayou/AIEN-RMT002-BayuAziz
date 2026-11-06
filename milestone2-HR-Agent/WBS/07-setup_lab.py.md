# WBS-07 — Implementasi `src/setup_lab.py`

- **Target:** `chunk_policy` dan `reset_and_seed`.
- **Owner:** Agent AI; schema dan seed data direview pemilik repo.
- **Dependency:** WBS-02, WBS-04, WBS-06.
- **Status:** TODO

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
