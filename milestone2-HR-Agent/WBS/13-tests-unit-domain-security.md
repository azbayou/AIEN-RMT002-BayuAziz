# WBS-13 — Test domain dan security

- **Target:** `tests/test_domain.py`, `tests/test_retrieval_security.py`.
- **Owner:** Agent AI.
- **Dependency:** WBS-01, WBS-02.
- **Status:** TODO

## Pekerjaan

1. Jalankan test business day, tanggal invalid, overlap, saldo, dan unsupported type.
2. Tambahkan test lead time tiga hari kerja.
3. Tambahkan test redaction untuk email, telepon, token, diagnosis, dan error multiline.
4. Tambahkan property/edge test untuk weekend-only dan boundary date.

## Acceptance criteria

- Semua test unit lulus deterministic.
- Tidak ada assertion yang hanya memeriksa status HTTP tanpa memeriksa data side effect.
