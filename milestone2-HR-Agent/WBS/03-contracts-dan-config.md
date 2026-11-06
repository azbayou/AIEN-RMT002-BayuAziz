# WBS-03 — Review `src/contracts.py` dan `src/config.py`

- **Target:** kontrak Pydantic dan konfigurasi runtime.
- **Owner:** Agent AI; perubahan kontrak harus direview pemilik repo.
- **Dependency:** WBS-00.
- **Status:** BELUM FINAL

## Pekerjaan

1. Verifikasi semua request/response cocok dengan `brief.md` dan UI.
2. Tambahkan validator hanya jika dibutuhkan oleh implementasi keamanan.
3. Validasi env model, database, Redis, dimensi embedding, timeout, dan budget.
4. Pastikan default development tidak menyamarkan readiness production.

## Acceptance criteria

- Tidak ada perubahan breaking pada `ui_contract.py`.
- Input invalid menghasilkan validation error yang aman.
- `live_model_ready` tidak menjadi satu-satunya readiness check.

## Hasil pelaksanaan dan refleksi

- Kontrak Pydantic yang sudah ada dipertahankan sehingga bentuk request/response tetap
  kompatibel dengan `ui_contract.py`; batas panjang, enum, dan tanggal tetap divalidasi
  sebelum masuk ke service.
- Konfigurasi sekarang menolak nilai teks kosong untuk metadata penting dan URL service
  tanpa scheme. `model_mode` dibatasi ke `live` atau `fake`, sehingga salah konfigurasi
  menghasilkan validation error tanpa membocorkan secret.
- `live_model_ready` hanya bernilai benar ketika mode live dan kredensial/model wajib
  tersedia. `configuration_ready` memeriksa database, Redis, dan kebutuhan model sehingga
  readiness tidak bergantung pada satu flag model saja.
- Validasi perlu dilanjutkan pada endpoint/API ketika WBS terkait selesai: error Pydantic
  harus dipetakan menjadi problem detail tanpa stack trace atau isi secret.

### TODO checkpoint

- Hubungkan `configuration_ready` dengan health database, policy index, Redis, dan provider
  pada endpoint `/readyz`; jangan hanya memeriksa nilai konfigurasi lokal.
- Tambahkan tes request invalid, problem detail, environment live/fake, dan kompatibilitas
  response dengan client UI setelah API selesai.
- Pastikan URL, credential, dan readiness detail tidak pernah dikembalikan dalam response.
