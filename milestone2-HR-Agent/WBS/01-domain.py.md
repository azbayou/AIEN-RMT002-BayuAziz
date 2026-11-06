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

## Checkpoint 2026-11-06

- Status: **DONE** untuk implementasi domain.
- `tests/test_domain.py` lulus dan suite non-live terbaru mencatat 25 passed.
- Agent: tidak ada TODO implementasi wajib pada WBS-01.
- Pemilik repo: lakukan review aturan lead time dan pesan error terhadap kebijakan final sebelum submission.
