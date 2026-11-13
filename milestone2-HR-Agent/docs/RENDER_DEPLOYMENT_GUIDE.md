# Panduan Lengkap Deployment ke Render via Docker Image
**HR Policy and Leave Assistant — Unified FastAPI & Web SPA**

Dokumen ini adalah panduan teknis resmi langkah demi langkah (*step-by-step*) untuk mempublikasikan dan mendeploy aplikasi **HR Policy and Leave Assistant** ke platform cloud **Render** menggunakan arsitektur **Docker Web Service**.

---

## 1. Arsitektur Deployment di Render

Aplikasi ini telah dioptimalkan secara khusus untuk berjalan di atas infrastruktur container cloud Render:

```
                  +----------------------------------------------+
                  |               Render Cloud                   |
                  |                                              |
  User Web UI --->|   [Unified Docker Container Service]         |
  & REST Client   |   - Port dinamis: $PORT (10000 di Render)   |
                  |   - Static Web SPA: /                        |
                  |   - REST API: /api/v1/...                    |
                  |   - Health & Readiness: /healthz, /readyz    |
                  |   - Entrypoint: Auto-migration on boot       |
                  |   - Cache: NullCache ($0 Free Tier) / Upstash|
                  +----------------------+-----------------------+
                                         |
                       +-----------------+-----------------+
                       |                                   |
                       v                                   v
             [NeonDB PostgreSQL]                    [Opik Cloud]
        - Serverless + pgvector 1536-dim      - Hierarchical LLM Tracing
        - AWS ap-southeast-1 (Singapore)       - Metrics, Spans & Redaction
        - Latensi container ~1–3 ms            - Project: Milestone 2 - HR Agent
```

### Keunggulan Desain Ini:
1. **Unified Service (1 Service Saja):** FastAPI menyajikan REST API backend sekaligus antarmuka modern Web SPA di root URL (`/`). Menghemat kuota Render Free Tier (hanya memakan 1 slot Web Service gratis) dan menghilangkan isu CORS.
2. **Zero-Cost Redis Fallback:** Menggunakan implementasi `NullCache` jika `REDIS_URL` tidak diisi di Render. Sistem tetap berjalan 100% fungsional tanpa perlu membayar add-on Redis ($7/bulan).
3. **Database Cloud NeonDB (Singapore):** Database serverless PostgreSQL dengan dukungan `pgvector` berdimensi 1536. Menempatkan region Render di **Singapore** memastikan latensi kueri container-ke-database hanya ~1–3 ms.
4. **Idempotent Boot Migration:** Script entrypoint otomatis menjalankan migrasi skema tabel dan sinkronisasi kebijakan (`python -m src.setup_lab`) saat container booting, memastikan database selalu dalam status siap tanpa intervensi manual.
5. **Observabilitas Penuh (Opik Cloud):** Setiap interaksi chat, tool call, latency, dan token cost otomatis terkirim ke dashboard Opik di workspace `azbayou`.

---

## 2. File Konfigurasi yang Telah Disiapkan

Repository ini telah dilengkapi dengan artefak deployment:

| File | Deskripsi |
| :--- | :--- |
| [`Dockerfile`](../Dockerfile) | Image container berbasis `python:3.11-slim`, non-root user `appuser:10001`, multi-stage ready. |
| [`scripts/entrypoint.sh`](../scripts/entrypoint.sh) | Skrip startup fleksibel: menangani `$PORT` dinamis, menjalankan auto-migration aman, dan signal handling. |
| [`render.yaml`](../render.yaml) | Render Blueprint (Infrastructure-as-Code) untuk deployment otomatis 1-klik di Render. |
| [`src/config.py`](../src/config.py) | Konfigurasi runtime yang mendukung `REDIS_URL` opsional dengan fallback aman ke `NullCache`. |

---

## 3. Langkah-Langkah Deployment ke Render

### Metode A: Menggunakan Render Blueprint (`render.yaml`) — *Direkomendasikan*

Metode ini adalah cara paling cepat, konsisten, dan minim kesalahan konfigurasi:

1. **Push Perubahan ke GitHub / GitLab:**
   Pastikan seluruh file project sudah di-commit dan di-push ke remote repository Git Anda:
   ```bash
   git add .
   git commit -m "feat: prepare project for Render Docker deployment"
   git push origin main
   ```

2. **Buka Render Dashboard:**
   * Login ke [dashboard.render.com](https://dashboard.render.com).
   * Klik tombol **New +** di pojok kanan atas, lalu pilih **Blueprint**.

3. **Hubungkan Repository:**
   * Pilih repository GitHub Anda yang berisi project ini.
   * Render akan secara otomatis mendeteksi keberadaan file `render.yaml`.
   * Beri nama Blueprint instance (misal: `hr-agent-blueprint`).

4. **Isi Secret Environment Variables:**
   Render akan menampilkan daftar variabel yang ditandai `sync: false` untuk diisi:
   * **`DATABASE_URL`**: Masukkan connection string NeonDB Anda:
     ```text
     postgresql://neondb_owner:npg_TPLO5hfjSB3z@ep-bold-paper-b3vr8inl-pooler.c-4.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require
     ```
   * **`OPENAI_API_KEY`**: Masukkan API key OpenAI Anda (`sk-...`).
   * **`OPIK_API_KEY`**: Masukkan API key Opik Anda.
   * **`REDIS_URL`**: Biarkan **kosong** (sistem otomatis fallback ke `NullCache`), atau isi URL Upstash Redis jika Anda memilikinya.

5. **Klik "Apply":**
   * Render akan membuat Web Service, mem-build Docker image langsung di server Render, dan meluncurkan container secara otomatis.

---

### Metode B: Membuat Web Service Manual via Dashboard Render

Jika Anda lebih memilih konfigurasi manual tanpa Blueprint:

1. Di Render Dashboard, klik **New +** &rarr; **Web Service**.
2. Pilih opsi **"Build and deploy from a Git repository"** dan pilih repo Anda.
3. Masukkan konfigurasi dasar:
   * **Name**: `hr-agent-assistant` (atau nama pilihan Anda).
   * **Region**: **Singapore (Southeast Asia)** *(Sangat penting agar latensi ke NeonDB minimal!)*.
   * **Branch**: `main`.
   * **Runtime**: **Docker**.
   * **Dockerfile Path**: `./Dockerfile`.
   * **Instance Type**: **Free** (0.1 CPU, 512 MB RAM).
4. Klik **Advanced** dan isi pengaturan berikut:
   * **Health Check Path**: `/readyz`
   * **Auto-Deploy**: `Yes`
5. Tambahkan **Environment Variables** (lihat tabel di Bagian 4).
6. Klik **Create Web Service**.

---

## 4. Daftar Lengkap Environment Variables di Render

| Nama Variabel | Wajib/Opsional | Nilai Rekomendasi / Keterangan |
| :--- | :---: | :--- |
| `DATABASE_URL` | **Wajib** | Connection string NeonDB (`postgresql://neondb_owner:...@...neon.tech/neondb?sslmode=require&channel_binding=require`) |
| `OPENAI_API_KEY` | **Wajib** | OpenAI API Key Anda (`sk-...`) |
| `OPENAI_BASE_URL` | Opsional | URL base API (kosongkan jika menggunakan standar OpenAI `https://api.openai.com/v1`) |
| `AGENT_MODEL` | **Wajib** | `gpt-4o-mini` |
| `EMBEDDING_MODEL` | **Wajib** | `text-embedding-3-small` |
| `EMBEDDING_DIMENSIONS` | **Wajib** | `1536` |
| `POLICY_INDEX_VERSION` | **Wajib** | `policies-2026-01` |
| `MODEL_MODE` | **Wajib** | `live` |
| `REDIS_URL` | Opsional | Kosongkan untuk Free Tier (otomatis fallback ke `NullCache` tanpa biaya) |
| `OPIK_API_KEY` | Opsional | API key akun Opik Cloud Anda |
| `OPIK_WORKSPACE` | Opsional | `azbayou` |
| `OPIK_PROJECT_NAME` | Opsional | `Milestone 2 - HR Agent` |
| `OPIK_ENABLED` | Opsional | `true` |
| `SKIP_SETUP` | Opsional | `false` (membiarkan entrypoint mengecek/migrasi DDL secara aman saat boot) |

> [!NOTE]
> Variabel `PORT` **tidak perlu disetel secara manual** di tabel environment variables Render. Render secara otomatis menginjeksi variabel `$PORT` (umumnya port `10000`), dan skrip [`entrypoint.sh`](../scripts/entrypoint.sh) sudah dikonfigurasi untuk membaca `${PORT:-8000}` secara dinamis.

---

## 5. Verifikasi Pasca-Deployment

Setelah status deployment di Render berubah menjadi **`Live`** (hijau), lakukan pengujian verifikasi menyeluruh:

### 1. Uji Health Check Endpoint
Gunakan terminal lokal atau browser Anda:
```bash
# Liveness Check (Harus 200 OK)
curl -i https://<app-name>.onrender.com/healthz

# Readiness Check (Harus 200 OK dengan dependencies.database = true)
curl -i https://<app-name>.onrender.com/readyz
```
Contoh respon `/readyz` yang berhasil:
```json
{
  "status": "ready",
  "ready": true,
  "dependencies": {
    "database": true,
    "cache": false,
    "configuration": true
  }
}
```
*(Catatan: `cache: false` adalah normal dan diharapkan ketika menggunakan `NullCache`, status service tetap `ready: true`).*

### 2. Uji Antarmuka Modern Web SPA
* Buka browser dan arahkan ke: `https://<app-name>.onrender.com/`
* Pastikan halaman login/portal muncul dengan mulus.
* Pilih salah satu persona demo (misal: **Alya Pratama** atau **Monitoring Admin**).
* Coba ajukan pertanyaan kebijakan cuti di form chat:
  > *"Berapa sisa cuti tahunan saya dan bagaimana aturan cuti sakit jika lebih dari 2 hari?"*
* Pastikan jawaban LLM muncul lengkap beserta kartu sitasi (*citations*) dokumen kebijakan yang relevan.

### 3. Uji Observabilitas Opik Cloud
* Buka dashboard Opik di [https://www.comet.com/opik/azbayou/](https://www.comet.com/opik/azbayou/).
* Pilih project **`Milestone 2 - HR Agent`** &rarr; tab **`Traces`**.
* Verifikasi bahwa percakapan yang baru saja Anda lakukan di Render telah tercatat sebagai trace baru dengan metadata `environment: production` dan span hierarki LLM/Tool yang lengkap.

---

## 6. Tips & Troubleshooting (FAQ)

### Q1: Mengapa request pertama setelah beberapa saat terasa lambat (Cold Start)?
> **Penjelasan:** Pada Render Free Tier, instance web service akan masuk mode *sleep* (*hibernasi*) jika tidak menerima traffic selama 15 menit. Request pertama setelah tidur membutuhkan waktu ~30–50 detik untuk *spin up* container kembali. Ini adalah perilaku bawaan paket gratis Render. Setelah aktif, request berikutnya akan cepat.

### Q2: Build gagal dengan pesan "out of memory" saat `pip install`?
> **Solusi:** Di [`Dockerfile`](../Dockerfile), perintah `pip install` telah dilengkapi flag `--no-cache-dir` untuk mencegah pembengkakan memori dan ukuran image container.

### Q3: Database connection timeout ke NeonDB?
> **Solusi:** Pastikan parameter `sslmode=require&channel_binding=require` disertakan pada `DATABASE_URL`. NeonDB mewajibkan enkripsi TLS/SSL untuk seluruh koneksi pooler.

### Q4: Apakah data cuti dan riwayat chat akan hilang jika container Render restart?
> **Penjelasan:** **Tidak hilang.** Karena database yang digunakan adalah cloud managed database **NeonDB**, seluruh data tersimpan permanen di cloud storage NeonDB. Container Render bersifat *stateless*, sehingga aman untuk restart, rebuild, atau auto-scale kapan saja.
