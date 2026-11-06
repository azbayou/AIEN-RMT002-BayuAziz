# WBS-02 — Implementasi `src/security.py`

- **Target:** `token_hash`, `stable_safety_id`, `redact`.
- **Owner:** Agent AI; security review oleh pemilik repo.
- **Dependency:** WBS-00.
- **Status:** BELUM FINAL

## Pekerjaan

1. Gunakan SHA-256 deterministik untuk token dan safety identifier.
2. Redact email, nomor telepon Indonesia, token-like strings, dan diagnosis/medical detail.
3. Pastikan fungsi idempotent dan tidak mengembalikan secret asli.
4. Definisikan penggunaan helper pada error, trace, ticket, dan provider call.

## Acceptance criteria

- `tests/test_retrieval_security.py` lulus.
- Raw token, PII, dan medical detail tidak muncul di trace.
- Tidak ada logging sebelum redaction.

## Hasil pelaksanaan dan refleksi

- `token_hash` menggunakan SHA-256 sehingga hasilnya deterministik, berbentuk digest
  heksadesimal, dan tidak menyimpan token asli.
- `stable_safety_id` menggunakan helper hash yang sama untuk menghasilkan identifier stabil
  tanpa mengekspos employee ID kepada provider.
- `redact` menutup email, nomor telepon Indonesia, token-like string, serta detail medis
  berlabel atau istilah medis umum. Placeholder tidak cocok dengan pola input sehingga
  redaksi bersifat idempotent.
- Validasi helper: pengujian redaksi pada `tests/test_retrieval_security.py` berhasil.
  Eksekusi penuh file tersebut belum lulus karena `RetrievalService.search` dan
  `create_app` masih `NotImplementedError` dari pekerjaan WBS lain.
- Catatan: redaksi harus tetap dipanggil sebelum error, trace, ticket, atau payload provider
  ditulis; helper ini tidak boleh dianggap sebagai pengganti pembatasan akses/otorisasi.

===

`_MEDICAL_TERM_RE = re.compile(
    r"(?i)\b(?:diabetes|hipertensi|asma|kanker|depresi|covid(?:-19)?|"
    r"flu|demam|migrain|cedera|sakit)\b"`

ini masih di harcode. cek lagi nanti

### TODO checkpoint

- Pindahkan daftar istilah medis dari source code ke konfigurasi/data yang dapat direview,
  atau batasi helper pada pola berlabel bila daftar istilah tidak memiliki sumber tepercaya.
- Tambahkan pengujian idempotency, multiline error, variasi nomor telepon, dan token yang
  belum tercakup.
- Verifikasi semua jalur trace, ticket, error, dan provider memanggil `redact` sebelum
  logging atau persistence.

## Checkpoint 2026-11-06

- Status: **BELUM FINAL**; suite non-live lulus, tetapi daftar medical term masih hardcode
  dan coverage call-site production belum lengkap.
- Agent: pindahkan aturan medis ke konfigurasi/data yang direview atau batasi redaksi pada
  label medis eksplisit, tambah edge tests, dan audit semua jalur logging/persistence.
- Pemilik repo: review apakah pendekatan redaction memenuhi hard gate privasi dan setujui
  daftar pola/konfigurasi medis sebelum submission.