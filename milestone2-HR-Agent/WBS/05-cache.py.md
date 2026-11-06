# WBS-05 — Implementasi `src/cache.py`

- **Target:** `ResilientCache` dan `NullCache`.
- **Owner:** Agent AI.
- **Dependency:** WBS-03.
- **Status:** CHECKPOINT - IMPLEMENTED

## Pekerjaan

1. Inisialisasi Redis dengan socket timeout pendek.
2. Implementasikan JSON-only get/set dengan TTL.
3. Ubah seluruh kegagalan Redis menjadi cache miss/no-op setelah logging aman.
4. Pastikan cache tidak menjadi sumber kebenaran.

## Acceptance criteria

- Retrieval tetap benar saat Redis unavailable.
- Cache key dapat memasukkan policy index version.
- Tidak ada raw prompt atau PII di cache.

## Checkpoint

- `ResilientCache` membuat client Redis dengan connect/read timeout pendek dan health check.
- `get` melakukan JSON decode; miss, payload invalid, dan kegagalan Redis tidak memblokir
  aplikasi. `set` hanya menulis JSON dengan TTL positif dan gagal secara aman.
- `NullCache` tidak melakukan network call dan selalu berperilaku sebagai cache miss/no-op.
- Logging kegagalan tidak memuat key, payload, prompt, atau PII.
- Versioned cache key belum dibuat di file ini karena pembentukan key merupakan tanggung jawab
  `RetrievalService` pada WBS-08.

## TODO berikutnya

1. Pada WBS-08, buat cache key deterministik yang menyertakan `policy_index_version`,
   query yang sudah dinormalisasi, dan parameter retrieval tanpa menyimpan raw prompt/PII.
2. Tambahkan test Redis unavailable, invalid JSON, TTL, JSON-only payload, dan NullCache.
3. Integrasikan `health()` cache ke endpoint `/readyz` tanpa menjadikan cache sebagai sumber
   kebenaran; Redis down harus tetap mengizinkan retrieval dari repository.

## Checkpoint 2026-11-06

- Status: **CHECKPOINT - IMPLEMENTED**; resilience smoke test, suite non-live, dan Docker
  image validation lulus.
- Agent: tambah test Redis unavailable/invalid JSON/TTL/cache hit dan pastikan versioned key
  terhubung dari Settings ke retrieval/API.
- Pemilik repo: validasi Redis runtime pada Compose dan pastikan outage Redis hanya
  menurunkan performa, bukan correctness.
