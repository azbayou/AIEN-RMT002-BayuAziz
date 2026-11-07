# WBS-05 — Implementasi `src/cache.py`

- **Target:** `ResilientCache` dan `NullCache`.
- **Owner:** Agent AI.
- **Dependency:** WBS-03.
- **Status:** DONE

## Pekerjaan

1. Inisialisasi Redis dengan socket connect dan read timeout pendek (0.5s).
2. Implementasikan JSON-only get/set dengan TTL.
3. Ubah seluruh kegagalan Redis (timeout, connection refused, corrupt JSON) menjadi cache miss/no-op secara aman.
4. Pastikan cache bukan sumber kebenaran (source of truth); outage Redis hanya mendegradasi performa retrieval ke miss, bukan correctness.
5. Sediakan `NullCache` sebagai fallback network-free.

## Acceptance criteria

- Retrieval tetap benar saat Redis unavailable (terdegradasi ke cache miss tanpa crash).
- Cache get/set aman terhadap corrupt bytes atau invalid JSON.
- `NullCache` tidak melakukan panggilan network dan berperilaku sebagai cache miss/no-op.
- Logging kegagalan tidak memuat key, payload, prompt, atau PII.
- Unit tests cache lulus 100%.

## Hasil pelaksanaan dan refleksi

- `ResilientCache` menggunakan socket timeout 0.5s dan health check interval 30s.
- Method `get()` menangani `RedisError`, `OSError`, `UnicodeDecodeError`, dan `ValueError`
  dengan mencatat safe warning dan mengembalikan `None` (cache miss).
- Method `set()` menolak TTL non-positif, menolak serialisasi non-JSON, dan mengabaikan
  kegagalan Redis tanpa melempar exception ke pemanggil.
- `NullCache` selalu mengembalikan `None` untuk `get()`, `health() == False`, dan `set()` no-op,
  digunakan untuk pengujian terisolasi bebas jaringan.
- Terverifikasi pada `tests/self_test_cache_providers.py` dan `tests/test_agent_reliability.py`.

## Checkpoint 2026-11-07 — FINAL

- Status: **DONE**
- Bukti:
  - `tests/self_test_cache_providers.py`: 3 cache tests passed (`test_null_cache_behavior`, `test_resilient_cache_health`, `test_resilient_cache_get_and_set`)
  - `tests/test_agent_reliability.py::test_redis_outage_degrades_to_cache_miss`: passed
  - Non-live regression suite: 63 passed, 0 failed
- Hard gates terkait: Terpenuhi (kegagalan cache tidak membocorkan PII atau mengubah correctness hasil).
