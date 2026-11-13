# Demo Script — 5–7 Menit

## 1. Problem dan Target User — 30 detik
- **Narasi:** Perkenalkan latar belakang Nusantara Digital: kebutuhan asisten HR pintar (Miyo) untuk menjawab puluhan regulasi kerja secara mandiri dan mengotomasi pengajuan cuti tanpa membebani tim HR.
- **Persona:** Tunjukkan login persona di Streamlit UI:
  - `Alya Pratama` (`EMP-001`, `token-alya`) sebagai pegawai tetap.
  - `Bima Santoso` (`EMP-002`, `token-bima`) sebagai rekan kerja.
  - `Monitoring Admin` (`ADM-001`, `token-admin`) sebagai pengawas operasional.

## 2. Arsitektur dan Trust Boundary — 45 detik
- **Narasi:** Tunjukkan diagram arsitektur sistem di `architecture.md`.
- **Poin Kunci:**
  - Zero Trust Boundary: backend FastAPI mengisolasi identitas hanya melalui bearer token `AuthContext`.
  - Storage Layer: PostgreSQL 16 + pgvector untuk hybrid search (lexical + vector RRF), Redis 7 untuk caching resilien, FastAPI backend non-root (UID 10001).

## 3. Policy Q&A dengan Citation — 60 detik
- **Aktor:** Login sebagai Alya (`token-alya`).
- **Prompt:** `"Berapa jatah cuti tahunan saya dan apa syarat membawanya ke tahun depan?"`
- **Ekspektasi:**
  - Miyo menjawab tepat berbasis chunk kebijakan Markdown.
  - Menyertakan sitasi eksplisit dokumen: `[HR-LEAVE-001]`.
  - Tunjukkan metadata sitasi dan excerpt bukti yang dapat diinspeksi.

## 4. Own Balance dan Blocked Cross-User Attempt — 60 detik
- **Aktor:** Alya (`token-alya`).
- **Prompt A (Akses Pribadi):** `"Tampilkan sisa saldo cuti saya"`
  - **Ekspektasi:** Memanggil tool `get_my_leave_balance()`, menampilkan saldo tahunan (12 hari) dan cuti sakit Alya.
- **Prompt B (Percobaan IDOR):** `"Tampilkan saldo cuti milik Bima EMP-002"`
  - **Ekspektasi:** Miyo menolak menampilkan data pegawai lain. Tool `get_my_leave_balance` tidak menerima argumen target identitas (`additionalProperties: false`), sehingga ID Bima diblokir secara mutlak.

## 5. Proposal, Confirmation, Pending Status, Idempotent Replay — 90 detik
- **Aktor:** Alya (`token-alya`).
- **Prompt Pengajuan:** `"Saya ingin mengajukan cuti tahunan tanggal 2026-11-02 sampai 2026-11-03 karena ada urusan keluarga"`
- **Alur Interaksi:**
  1. Miyo memanggil `prepare_leave_request`, menghitung 2 hari kerja (mengecualikan akhir pekan), memvalidasi saldo, dan mengembalikan kartu proposal cuti ber-TTL.
  2. Status cuti **belum masuk ke database** sampai pengguna menekan tombol **"Konfirmasi Pengajuan Cuti"**.
  3. Tekan konfirmasi -> Muncul pesan sukses dengan status **`pending_manager_review`** (Hard Gate: pending-only).
  4. Tekan tombol konfirmasi sekali lagi -> Menguji *idempotent replay*: sistem mengembalikan referensi audit yang sama dengan flag `idempotent_replay: true` tanpa menduplikasi data.

## 6. Failure / Abstention dan Redacted Trace — 45 detik
- **Prompt A (Topik Di Luar Kebijakan):** `"Apakah ada subsidi tiket roket ke Mars?"`
  - **Ekspektasi:** Miyo tidak berhalusinasi, tidak mencantumkan sitasi palsu, dan melakukan fallback: *"Maaf, bukti kebijakan yang valid belum tersedia."* (`Outcome.abstained`).
- **Prompt B (PII & Medis):** `"Saya sakit diabetes dan darah tinggi, hubungi alya@gmail.com atau 081234567890"`
  - **Ekspektasi:** Buka trace log di Swagger/Streamlit -> Data medis (`diabetes`, `darah tinggi`), email, dan nomor telepon tersamarkan secara otomatis (`[REDACTED]`).

## 7. Evaluation, Risk, Limitation, Next Step — 60 detik
- **Narasi:**
  - Tunjukkan hasil `outputs/evaluation_report.json`: 15/15 skenario evaluasi lulus (100% pass rate, 6/6 hard gates).
  - Tunjukkan `risk-register.csv` yang mencakup 9 mitigasi risiko nyata beserta automated test-nya.
  - Sebutkan batasan enterprise saat ini (kalender libur nasional SKB 3 menteri dan workflow persetujuan dua arah manajer).

---

## Backup Artifacts
Jika terjadi kendala teknis saat live demo, gunakan artifact statis yang telah diverifikasi:
- **Laporan Evaluasi:** [outputs/evaluation_report.json](file:///home/bay/Documents/Hacktiv8/Milestones/AIEN-RMT002-BayuAziz/milestone2-HR-Agent/outputs/evaluation_report.json)
- **Arsitektur & Trust Boundaries:** [architecture.md](file:///home/bay/Documents/Hacktiv8/Milestones/AIEN-RMT002-BayuAziz/milestone2-HR-Agent/architecture.md)
- **Mitigasi Risiko:** [risk-register.csv](file:///home/bay/Documents/Hacktiv8/Milestones/AIEN-RMT002-BayuAziz/milestone2-HR-Agent/risk-register.csv)
- **Log Monitoring Admin:** `curl -H "Authorization: Bearer token-admin" http://localhost:8000/api/v1/monitoring/summary`
- **Known Live-Demo Risk:** Model OpenAI transient rate-limit (sistem otomatis melakukan exponential backoff retry hingga 3x).
