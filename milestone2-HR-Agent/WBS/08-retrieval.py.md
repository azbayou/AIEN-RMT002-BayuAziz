# WBS-08 — Implementasi `src/retrieval.py`

- **Target:** `RetrievalService.search`.
- **Owner:** Agent AI.
- **Dependency:** WBS-04, WBS-05, WBS-06, WBS-07.
- **Status:** CHECKPOINT - IMPLEMENTED

## Pekerjaan

1. Buat version-aware cache key.
2. Jalankan lexical search dan vector search.
3. Gabungkan kandidat dengan reciprocal rank fusion.
4. Terapkan keyword rerank dan top-k deterministic.
5. Pertahankan metadata untuk citation.
6. Tangani embedding/database/cache failure secara eksplisit.

## Acceptance criteria

- Query “jatah cuti tahunan” memprioritaskan `HR-LEAVE-001`.
- Citation hanya berasal dari chunk yang dikembalikan pada run tersebut.
- Redis mati hanya menurunkan performa, bukan correctness.

## Checkpoint

- Retrieval sekarang membuat cache key berisi index version, top-k, dan hash query yang
  dinormalisasi; raw prompt tidak dimasukkan ke key.
- Lexical dan vector candidates digabungkan memakai reciprocal rank fusion, lalu keyword
  overlap dan chunk ID dipakai sebagai tie-break deterministic.
- Cache payload divalidasi kembali sebagai `PolicyChunk`, sehingga metadata citation tetap
  dipertahankan dan payload invalid diperlakukan sebagai cache miss.
- Kegagalan embedding/vector diturunkan menjadi lexical-only retrieval; Redis failure
  tetap menjadi miss/no-op sesuai kontrak cache.

## TODO berikutnya

1. Tambahkan test cache hit, invalid payload, version isolation, embedding failure, dan
   Redis unavailable.
2. Hubungkan `policy_index_version` dari `Settings` pada wiring API/retrieval.
3. Implementasikan vector/lexical search production di `PostgresRepository` dan verifikasi
   dimensi embedding terhadap schema pgvector.
4. Tambahkan test citation metadata dan query multilingual/normalisasi whitespace.

## Checkpoint 2026-11-06

- Status: **CHECKPOINT - IMPLEMENTED**; retrieval acceptance, normalization smoke test,
  suite non-live, dan Docker image tests lulus.
- Agent: tambah cache/failure/version/citation edge tests dan implementasikan search production
  melalui PostgresRepository.
- Pemilik repo: validasi query “jatah cuti tahunan” dan citation pada database seed serta
  uji Redis outage di Compose.
