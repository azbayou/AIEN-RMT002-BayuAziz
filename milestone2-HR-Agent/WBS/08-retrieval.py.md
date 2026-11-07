# WBS-08 — Implementasi `src/retrieval.py`

- **Target:** `RetrievalService.search`.
- **Owner:** Agent AI.
- **Dependency:** WBS-04, WBS-05, WBS-06, WBS-07.
- **Status:** DONE

## Pekerjaan

1. Buat version-aware cache key yang aman (berisi `policy_index_version`, `top_k`, dan SHA-256 hash query normalisasi).
2. Jalankan hybrid search: lexical search dan dense vector search.
3. Gabungkan kandidat dari kedua metode menggunakan Reciprocal Rank Fusion (RRF dengan parameter $k=60$).
4. Terapkan keyword overlap score dan chunk ID deterministik sebagai tie-breaker.
5. Pertahankan metadata lengkap chunk untuk kebutuhan sitasi valid.
6. Tangani kegagalan embedding, redis, dan data cache korup secara aman (graceful degradation).

## Acceptance criteria

- Query “jatah cuti tahunan” memprioritaskan dokumen `HR-LEAVE-001`.
- Metadata sitasi (`document_id`, `section`, `title`, `excerpt`) lengkap dan utuh.
- Outage Redis atau payload cache korup hanya menurunkan performa, bukan correctness (otomatis beralih ke pencarian repository).
- Kegagalan model embedding otomatis terdegradasi ke lexical search tanpa melempar exception ke pemanggil.
- Query kosong atau spasi murni mengembalikan list kosong secara instan.

## Hasil pelaksanaan dan refleksi

- `RetrievalService` menormalisasi query teks (lowercase dan spasi tunggal) dan menghasilkan cache key
  deterministik `retrieval:{version}:{top_k}:{sha256(normalized)}`. Raw query dan PII tidak disimpan pada cache key.
- Reciprocal Rank Fusion (RRF) menggabungkan peringkat hasil lexical dan semantic:
  $$\text{score} = \sum \frac{1}{60 + \text{rank}}$$
- Reranking sekunder menghitung irisan kata kunci (*keyword overlap*) antara query dengan teks chunk untuk memilih top-k terbaik.
- Uji ketahanan (*resilience*):
  - Kegagalan Redis atau cache payload korup otomatis fallback ke fresh search.
  - Exception saat embedding (timeout, provider error) ditangkap dan didegradasi menjadi pencarian lexical-only.
- Terverifikasi pada `tests/self_test_setup_and_retrieval.py` dan `tests/test_retrieval_security.py`.

## Checkpoint 2026-11-07 — FINAL

- Status: **DONE**
- Bukti:
  - `tests/self_test_setup_and_retrieval.py`: 4 retrieval resilience & cache tests passed
  - `tests/test_retrieval_security.py::test_hybrid_retrieval_prefers_lexical_match`: passed (`HR-LEAVE-001` prioritas pertama)
  - Non-live regression suite: 69 passed, 0 failed
- Hard gates terkait (Valid Citation, Resilient Cache, PII Isolation): TERPENUHI.
