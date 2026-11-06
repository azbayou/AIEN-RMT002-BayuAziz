# WBS-01 — Implementasi `src/domain.py`

- **Target:** `business_days`, `validate_leave_request`, `estimate_cost`.
- **Owner:** Agent AI; aturan ambigu direview pemilik repo.
- **Dependency:** WBS-00.
- **Status:** DONE

## Pekerjaan

1. Validasi tanggal terbalik dan rentang tanpa hari kerja.
2. Hitung hari Senin–Jumat, tidak menghitung Sabtu/Minggu.
3. Tolak tanggal lampau, overlap aktif, leave type yang tidak didukung, dan saldo kurang.
4. Evaluasi aturan lead time tiga hari kerja dari `data/policies/annual-leave.md`.
5. Kembalikan biaya hanya jika kedua rate tersedia.

## Acceptance criteria

- Test `tests/test_domain.py` lulus.
- Error memakai `DomainError` dengan pesan yang dapat diuji.
- Modul tidak memanggil model, database, atau network.
