# WBS-07 — Implementasi `src/setup_lab.py`

- **Target:** `chunk_policy` dan `reset_and_seed`.
- **Owner:** Agent AI; schema dan seed data direview pemilik repo.
- **Dependency:** WBS-02, WBS-04, WBS-06.
- **Status:** DONE

## Pekerjaan

1. Parse front matter policy dan section Markdown secara deterministik.
2. Buat stable chunk ID serta pertahankan metadata (`document_id`, `version`, `effective_date`, `section`, `title`).
3. Buat schema tabel transaksi dan index PostgreSQL lengkap (`employees`, `leave_balances`, `policy_chunks`, `action_proposals`, `leave_requests`, `tickets`, `traces`) serta ekstensi pgvector.
4. Hash identity token (SHA-256), seed balances, batch embed policy chunks, dan jalankan upsert idempotent.
5. Dukung mode CLI `--reset` dan mode seed non-destructive tanpa ketergantungan API key live saat build.

## Acceptance criteria

- `chunk_policy` memvalidasi kelengkapan front matter dan melempar `ValueError` deskriptif jika tidak valid.
- Semua file kebijakan pada `data/policies/*.md` berhasil di-parse dan memiliki metadata lengkap.
- `test_policy_chunk_ids_and_metadata_are_stable` lulus.
- Dimensi embedding tervalidasi sama persis dengan `EMBEDDING_DIMENSIONS`.
- Seed dapat dijalankan tanpa API key live menggunakan fallback `DeterministicProvider`.

## Hasil pelaksanaan dan refleksi

- `chunk_policy` memvalidasi keberadaan delimiter `---`, parsing metadata dokumen (`document_id`, `title`, `version`, `effective_date`),
  memisahkan per section `## `, dan menghasilkan chunk ID unik deterministik berbasis SHA-256.
- `reset_and_seed` menyediakan DDL lengkap yang kompatibel 100% dengan `PostgresRepository`:
  - `employees` menyimpan `token_hash` unik.
  - `policy_chunks` memiliki kolom `vector` dan index `document_id, version`.
  - `action_proposals`, `leave_requests`, `tickets`, dan `traces` lengkap dengan foreign key dan composite index.
- Mode fallback deterministik memungkinkan inisialisasi database lokal maupun container testing
  tanpa membutuhkan `OPENAI_API_KEY`.
- Terverifikasi pada `tests/self_test_setup_and_retrieval.py` dan `tests/test_agent_reliability.py`.

## Checkpoint 2026-11-07 — FINAL

- Status: **DONE**
- Bukti:
  - `tests/self_test_setup_and_retrieval.py`: `test_chunk_policy_validates_front_matter` & `test_chunk_policy_all_repo_policies_are_valid` passed
  - `tests/test_agent_reliability.py::test_policy_chunk_ids_and_metadata_are_stable`: passed
  - Seluruh test non-live: 69 passed, 0 failed
- Hard gates terkait (PII Redaction, Deterministic Chunks, Non-Root Offline Seed): TERPENUHI.
