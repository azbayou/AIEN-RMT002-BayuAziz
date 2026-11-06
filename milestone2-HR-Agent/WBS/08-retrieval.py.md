# WBS-08 — Implementasi `src/retrieval.py`

- **Target:** `RetrievalService.search`.
- **Owner:** Agent AI.
- **Dependency:** WBS-04, WBS-05, WBS-06, WBS-07.
- **Status:** TODO

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
