# WBS-13 — Test domain dan security

- **Target:** `tests/test_domain.py`, `tests/test_retrieval_security.py`.
- **Owner:** Agent AI.
- **Dependency:** WBS-01, WBS-02.
- **Status:** DONE

## Pekerjaan

1. Jalankan test business day, tanggal invalid, overlap, saldo, dan unsupported type.
2. Tambahkan test lead time tiga hari kerja.
3. Tambahkan test redaction untuk email, telepon, token, diagnosis, dan error multiline.
4. Tambahkan property/edge test untuk weekend-only dan boundary date.

## Acceptance criteria

- Semua test unit lulus deterministic.
- Tidak ada assertion yang hanya memeriksa status HTTP tanpa memeriksa data side effect.

## Checkpoint 2026-11-07 — FINAL

- Status: **DONE**
- Seluruh 8 test di `tests/test_domain.py` lulus 100% (inclusive business days calculation, weekend-only rejection, past dates, overlap validation, insufficient balance, unsupported leave type, lead time bounds).
- Seluruh 6 test di `tests/test_retrieval_security.py` lulus 100% (email, multiple phone formats, Bearer/token prefixes, multiline medical diagnoses, negative lookbehind preservation of `cuti sakit`, idempotency).
- Suite kontrak dan konfigurasi `tests/self_test_contracts_config.py` (17 tests) lulus deterministic tanpa network.
- Hard gates terkait (Redaction & PII, Domain Lead Time & Business Days): TERPENUHI 100%.
