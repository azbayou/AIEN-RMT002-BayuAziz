# Panduan Deployment: Backend Only ke Vercel Serverless

Dokumen ini adalah panduan langkah demi langkah (*step-by-step*) untuk melakukan deployment **Backend FastAPI** ke cloud **Vercel** secara **100% Gratis dan Tanpa Kartu Kredit (Zero CC)**.

---

## 1. Arsitektur Decoupled (Terpisah)

* **Frontend:** Berjalan di **GitHub Pages** (atau web statis).
* **Backend:** Berjalan di **Vercel Serverless Functions** (`api/index.py` & `vercel.json`).
* **Database:** **NeonDB Cloud Serverless PostgreSQL** (dengan `pgvector` & `pg_trgm`).
* **AI & Observabilitas:** **OpenAI API** & **Comet Opik Cloud**.

---

## 2. Struktur File Vercel di Repository

```text
milestone2-HR-Agent/
├── api/
│   └── index.py            # Entrypoint Serverless ASGI untuk Vercel
├── vercel.json             # Konfigurasi routing rewrite & CORS headers
├── requirements.txt        # Dependensi Python untuk runtime Vercel
└── src/                    # Seluruh logika FastAPI, Agent, Tools, Repository
```

---

## 3. Langkah-Langkah Deployment ke Vercel

### Langkah 1: Push Perubahan ke GitHub
Buka terminal pada root repositori Anda dan jalankan perintah:
```bash
git add .
git commit -m "feat: add vercel serverless backend-only deployment configuration"
git push origin main
```

---

### Langkah 2: Import Proyek di Vercel Dashboard
1. Buka [vercel.com](https://vercel.com) dan login menggunakan akun **GitHub** Anda.
2. Pada halaman dashboard Vercel, klik tombol **Add New...** di pojok kanan atas, lalu pilih **Project**.
3. Cari repository Anda (misal: `AIEN-RMT002-BayuAziz`) lalu klik **Import**.
4. **Penting — Pengaturan Root Directory:**
   - Pada bagian **Root Directory**, klik **Edit**.
   - Pilih direktori: `milestone2-HR-Agent` (atau sub-folder milestone 2 Anda).
   - Klik **Continue**.
5. Pada bagian **Framework Preset**, biarkan **Other**.

---

### Langkah 3: Konfigurasi Environment Variables di Vercel
Sebelum menekan tombol Deploy, scroll ke bagian **Environment Variables** dan masukkan variabel-variabel berikut:

| Key (Nama Variabel) | Contoh Nilai | Keterangan |
| :--- | :--- | :--- |
| `DATABASE_URL` | `postgresql://neondb_owner:...@...neon.tech/neondb?sslmode=require` | Connection string NeonDB Anda |
| `OPENAI_API_KEY` | `sk-proj-...` | API Key OpenAI Anda |
| `AGENT_MODEL` | `gpt-4o-mini` *(atau `gpt-6-luna`)* | Model LLM untuk Agent |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Model vektor embedding |
| `EMBEDDING_DIMENSIONS` | `1536` | Dimensi vektor pgvector |
| `POLICY_INDEX_VERSION` | `policies-2026-01` | Versi index kebijakan |
| `MODEL_MODE` | `live` | Mode operasional live |
| `OPIK_API_KEY` | `8cBiKd...` | API Key Opik |
| `OPIK_WORKSPACE` | `azbayou` | Workspace Opik |
| `OPIK_PROJECT_NAME` | `Milestone 2 - HR Agent` | Nama project di Opik |
| `OPIK_ENABLED` | `true` | Aktifkan tracing telemetri |

> [!TIP]
> **Biarkan `REDIS_URL` kosong!**  
> Sistem akan otomatis menggunakan `NullCache` ($0, tanpa Redis serverless tambahan) sehingga backend berjalan cepat tanpa dependensi eksternal.

---

### Langkah 4: Klik Deploy!
1. Klik tombol **Deploy** berwarna biru.
2. Tunggu proses build selesai (~1 menit). Vercel akan meng-install dependensi dan mempublikasikan endpoint serverless Anda.
3. Setelah selesai, Vercel akan memberikan domain publik Anda, misalnya:  
   `https://hr-agent-backend.vercel.app` (atau nama unik proyek Anda).

---

## 4. Verifikasi Backend Vercel Anda

Setelah deployment berhasil (*Status: Ready*), Anda dapat memverifikasi API melalui browser atau curl:

1. **Info Status API (Root Endpoint):**
   Buka `https://<nama-proyek>.vercel.app/`
   *Respons yang diharapkan (JSON):*
   ```json
   {
     "status": "online",
     "service": "PT Nusantara Digital - HR Agent Assistant API",
     "environment": "vercel_serverless",
     "documentation": "/docs",
     "version": "policies-2026-01"
   }
   ```
2. **Dokumentasi Interaktif Swagger UI:**
   Buka `https://<nama-proyek>.vercel.app/docs` untuk mencoba endpoint secara langsung.
3. **Health Check:**
   Buka `https://<nama-proyek>.vercel.app/healthz` &rarr; `{"status": "ok"}`.
4. **Daftar Persona dari NeonDB:**
   Buka `https://<nama-proyek>.vercel.app/api/v1/auth/personas` &rarr; Menampilkan profil aktif dinamis dari database.

---

## 5. Menghubungkan Frontend GitHub Pages ke Backend Vercel

Pada aplikasi Frontend (misalnya di GitHub Pages `https://<username>.github.io/...`):
1. Buka antarmuka web di browser.
2. Klik tombol **Roda Gerigi (Pengaturan)** di pojok kanan atas.
3. Masukkan URL Vercel Anda pada kolom **Backend API URL**:
   ```text
   https://<nama-proyek>.vercel.app
   ```
4. Klik tombol **Uji & Simpan Pengaturan**.
5. Indikator di sidebar akan berubah menjadi hijau: **Sistem & DB Siap**.
6. Frontend kini terhubung langsung ke Backend serverless Vercel Anda!
