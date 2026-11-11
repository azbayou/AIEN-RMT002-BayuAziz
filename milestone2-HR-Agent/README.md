# Milestone P2M2 — Asisten Kebijakan HR dan Cuti

Anda membangun backend FastAPI untuk UI Streamlit yang sudah disediakan. Sistem harus menjawab kebijakan dengan sitasi, membaca saldo cuti milik pengguna terautentikasi, menyiapkan proposal cuti, dan membuat permintaan `pending_manager_review` hanya sesudah konfirmasi. Semua persona dan data adalah sintetis.

**Level:** Intermediate · **Waktu:** tiga sesi mentoring × 180 menit + demo 5–7 menit · **Hasil akhir:** API, test, evaluasi, risk register, dan catatan arsitektur.

Mulai dari [brief.md](brief.md), ikuti [lab.md](lab.md), lalu gunakan [assessment.md](assessment.md), [rubric.md](rubric.md), dan [submission-checklist.md](submission-checklist.md). Instruktur menyimpan kunci dan implementasi referensi di folder `solution/` terpisah.

## Yang Anda bangun

- `src/`: indexing dan hybrid retrieval, repository PostgreSQL, agent empat tool, aturan cuti, FastAPI, telemetry, serta evaluator. Cari marker `TODO(M2)` sebagai titik implementasi.
- `Dockerfile`: image non-root untuk API dan UI. `docker-compose.yml` menyediakan wiring empat service; lihat [kontrak pengiriman Docker](docker-delivery.md).
- Test tambahan, laporan evaluasi 15 kasus, diagram arsitektur, risk register, dan demo.

`app.py`, `ui_contract.py`, `demo_personas.json`, `data/`, dan model Pydantic pada `src/contracts.py` adalah artefak yang disediakan. UI hanya memanggil API. Identitas pegawai ditentukan backend dari bearer token, bukan dari teks pertanyaan atau pilihan model.

## Menjalankan starter

Dari folder `participant/`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
docker compose up -d postgres redis
python -m pytest -m "not live"
```
*(Pastikan parameter `OPENAI_API_KEY` dan `AGENT_MODEL` telah terkonfigurasi di `.env`)*.

Isi `.env` dengan kredensial dan model yang ditetapkan instruktur. Di macOS/Linux, gunakan `source .venv/bin/activate` dan `cp .env.example .env`. Sebagian public tests memang gagal sampai TODO backend selesai. Setelah implementasi, jalankan `python -m src.setup_lab --reset`, API dengan `python -m uvicorn src.api:create_app --factory --reload`, lalu UI dengan `python -m streamlit run app.py` pada terminal kedua.

Alur host-Python di atas untuk pengembangan lokal. **Submission dinilai melalui Docker saja**, tanpa instalasi Python pada host grader; ikuti [urutan build, seed, startup, dan test](docker-delivery.md).

## Batas sistem

- Tidak ada tool atau endpoint yang menyetujui cuti. Konfirmasi membuat satu permintaan `pending_manager_review`.
- Saldo, request, dan trace pegawai lain tidak boleh diakses.
- Jawaban kebijakan harus menyertakan sitasi dari dokumen yang ditemukan pada run yang sama; bila bukti tidak cukup, abstain atau eskalasi.
- Jangan mengunggah `.env`, API key, database, atau data pegawai nyata.

Lihat [brief.md](brief.md) untuk kontrak endpoint dan kategori kasus, dan [lab.md](lab.md) untuk langkah, checkpoint, serta troubleshooting.

## 🌐 Akses Aplikasi & Dokumentasi

- **Streamlit Web UI:** [http://localhost:8501](http://localhost:8501)
  *(Pilih persona di sidebar kiri: Alya — pegawai, Bima — pegawai, atau Monitoring admin).*
- **FastAPI Swagger Interactive Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **FastAPI OpenAPI JSON Specification:** [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

---

## 🧪 Menjalankan Pengujian (Testing Suite)

### A. Pengujian Deterministik Non-Live (Dalam Container)
Semua 38 unit & contract tests berjalan 100% tanpa akses jaringan luar:
```bash
docker compose exec -T api pytest -m "not live"
```

### B. Pengujian Integrasi PostgreSQL & pgvector
```bash
docker compose exec -T -e RUN_POSTGRES_TESTS=1 api pytest tests/test_repository_postgres.py
```

### C. Pengujian Live API
```bash
docker compose exec -T -e RUN_LIVE_TESTS=1 api pytest tests/test_live_api.py
```

### D. Pengujian WBS Self-Tests
Verifikasi kepatuhan seluruh acceptance criteria WBS:
```bash
docker compose exec -T api pytest tests/self_test_*.py
```

### E. Menjalankan Evaluator Komprehensif (15 Skenario)
Runner mengevaluasi seluruh skenario pengujian enterprise (grounded policy, cross-employee security, prompt injection, invalid past-date rejection, confirmation hard-gates):
```bash
docker compose exec -T api python -m src.run_evaluation --base-url http://localhost:8000 --token token-alya
```

Laporan evaluasi tersimpan di `outputs/evaluation_report.json` dengan hasil:
- **Total Kasus:** 15 / 15 Passed (100% Pass Rate)
- **Hard Gates:** 6 / 6 Passed
- **Keputusan Rilis:** `release_decision: release`

---

## 👥 Persona & Matriks Otorisasi

| Persona | ID Pegawai | Bearer Token | Hak Akses |
|---|---|---|---|
| **Alya Pratama** | `EMP-001` | `Bearer token-alya` | Akses kebijakan, saldo cuti pribadi, proposal cuti pribadi. |
| **Bima Santoso** | `EMP-002` | `Bearer token-bima` | Akses kebijakan, saldo cuti pribadi, terisolasi dari Alya. |
| **Monitoring Admin** | `ADM-001` | `Bearer token-admin` | Mengakses ringkasan monitoring operasional (`/api/v1/monitoring/summary`). |

---

## 🛡️ Ringkasan 6 Hard Gates Kepatuhan

| # | Hard Gate | Status | Mekanisme Pencegahan |
|---|---|:---:|---|
| 1 | **Identity Binding** | ✅ PASSED | `employee_id` hanya diambil dari token bearer di `AuthContext`. Argumen model diabaikan. |
| 2 | **Pending-only Action** | ✅ PASSED | Status cuti di database terkunci pada `pending_manager_review`; persetujuan otomatis diblokir. |
| 3 | **Confirmation & Idempotency** | ✅ PASSED | Proposal memerlukan token konfirmasi ber-TTL; replay token menghasilkan respon konsisten tanpa data ganda. |
| 4 | **Valid Citation & Abstain** | ✅ PASSED | Jawaban memvalidasi sitasi `[HR-XXX-XXX]` terhadap chunk retrieval aktif; wajib abstain jika bukti tidak valid. |
| 5 | **Redacted Trace & PII** | ✅ PASSED | Sanitasi in-memory untuk nomor telepon, email, Bearer token, dan istilah medis (`data/medical_terms.json`). |
| 6 | **Non-Root Docker Image** | ✅ PASSED | Dockerfile mengonfigurasi user `appuser` (UID 10001) dan build tidak memerlukan secret API key. |

---

## 📊 Monitoring Operasional & Rules

Aturan monitoring dinilai secara dinamis melalui file konfigurasi [data/monitoring_rules.json](data/monitoring_rules.json):
- `agent-error-spike`: Ambang batas `error_rate > 0.20` (minimum 5 sampel) &rarr; Owner: AI Platform.
- `agent-latency-p95`: Ambang batas `p95_latency_ms > 8000 ms` (minimum 5 sampel) &rarr; Owner: AI Platform.

Akses monitoring summary dapat dilihat melalui:
```bash
curl -H "Authorization: Bearer token-admin" http://localhost:8000/api/v1/monitoring/summary
```
