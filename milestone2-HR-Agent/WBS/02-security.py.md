# WBS-02 — Implementasi `src/security.py`

- **Target:** `token_hash`, `stable_safety_id`, `redact`.
- **Owner:** Agent AI; security review oleh pemilik repo.
- **Dependency:** WBS-00.
- **Status:** DONE

## Pekerjaan

1. Gunakan SHA-256 deterministik untuk token dan safety identifier.
2. Redact email, nomor telepon Indonesia, token-like strings, dan diagnosis/medical detail.
3. Pastikan fungsi idempotent dan tidak mengembalikan secret asli.
4. Definisikan penggunaan helper pada error, trace, ticket, dan provider call.
5. Pindahkan daftar istilah medis ke file eksternal yang dapat diaudit (`data/medical_terms.json`).

## Acceptance criteria

- `tests/test_retrieval_security.py` lulus (6 passed).
- Edge tests pada `tests/self_test_contracts_config.py` lulus (7 security tests passed).
- Raw token, PII, dan medical detail tidak muncul di trace atau logging.
- Redaksi bersifat strictly idempotent (`redact(redact(x)) == redact(x)`).
- "cuti sakit" dipertahankan sedangkan diagnosa/keluhan medis lainnya di-redact.

## Hasil pelaksanaan dan refleksi

- `token_hash` menggunakan SHA-256 sehingga hasilnya deterministik, berbentuk digest
  heksadesimal 64 karakter, dan tidak menyimpan token asli.
- `stable_safety_id` menggunakan helper hash yang sama untuk menghasilkan identifier stabil
  tanpa mengekspos employee ID kepada provider model.
- Istilah medis eksternal telah dipindahkan seluruhnya ke file reviewable `data/medical_terms.json`
  sebagai satu-satunya Single Source of Truth (SSOT), persis seperti data catalog lainnya di folder data/.
  Pola regex diurutkan berdasarkan panjang karakter (descending) untuk memastikan prefix multi-kata
  (e.g. `covid-19` sebelum `covid`) cocok terlebih dahulu.
- Pola negatif lookbehind `(?<!cuti\s)\bsakit\b` berhasil mempertahankan terminologi kebijakan
  "cuti sakit" sambil tetap meredaksi diagnosa sakit/gejala medis lainnya.
- `redact` idempotent terverifikasi pada multi-pass, multiline, variasi nomor telepon (+62, 08, spasi,
  titik, strip), serta token-like strings (Bearer token, sk-, secret-, api-key-).
- Seluruh jalur persistence dan error handling telah memanggil `redact` atau `redact_trace`:
  - `src/api.py`: exception conflict error di-redact sebelum dikembalikan ke client.
  - `src/repository.py`: `save_ticket` meredaksi summary tiket; `save_trace` menjalankan
    `redact_trace` rekursif sebelum disimpan ke memory maupun PostgreSQL JSONB.
  - `src/agent.py`: tool call output dan runtime error di-redact sebelum dimasukkan ke riwayat percakapan.

## Checkpoint 2026-11-07 — FINAL

- Status: **DONE**
- Bukti:
  - `tests/test_retrieval_security.py`: 6 passed
  - `tests/self_test_contracts_config.py`: 7 security tests passed
  - Seluruh test suite non-live: 55 passed, 0 failed
- Hard gates terkait (Redacted Trace & PII, Identity Binding): TERPENUHI.
