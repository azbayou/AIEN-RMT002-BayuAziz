# Project Brief

## Target User
- **Pegawai Tetap & Masa Probation Nusantara Digital** (`EMP-001`, `EMP-002`): Mengakses informasi kebijakan HR, mengecek saldo cuti pribadi, dan menyiapkan proposal pengajuan cuti secara mandiri.
- **Monitoring Admin** (`ADM-001`): Mengawasi performa operasional, latensi p95, spike error rate, dan log audit sistem tanpa mengakses data pribadi pegawai.

## Current Workflow and Pain Point
- **Pertanyaan HR Berulang:** Tim HR manual melayani puluhan pertanyaan kebijakan serupa (cuti, tunjangan, reimbursement, aturan kerja hybrid) setiap hari.
- **Keterlambatan & Salah Hitung Cuti:** Pengajuan cuti manual rentan salah hitung hari kerja (mengabaikan akhir pekan), bentrok tanggal (overlap), atau melewati kuota jatah tahunan.
- **Risiko Privasi & Regulasi (UU PDP):** Kebocoran riwayat cuti, data medis pegawai, dan identitas token otorisasi saat proses konsultasi informal.

## In Scope
- RAG kebijakan HR berbasis Markdown dengan sitasi eksplisit dokumen (`[DOCUMENT_ID]`) dan mekanisme fallback/abstain bila bukti tidak valid.
- Akses saldo cuti dan pengajuan proposal cuti yang terikat ketat pada identitas bearer token (`AuthContext`).
- Alur 2-fase pengajuan cuti (*prepare proposal* -> *explicit confirm*) berstatus `pending_manager_review` dengan jaminan idempotency key.
- Eskalasi otomatis pembuatan tiket HR (`create_hr_ticket`) saat kebijakan tidak ditemukan.
- Redaksi PII otomatis in-memory (email, nomor telepon Indonesia, Bearer token, dan istilah medis) sebelum data disimpan ke telemetry trace.
- Telemetry dan alert monitoring dinamis (`agent-error-spike`, `agent-latency-p95`) untuk admin.

## Out of Scope
- Persetujuan/penolakan cuti otomatis oleh model AI (kebijakan *pending-only*, persetujuan final tetap menjadi kewenangan manajer manusia).
- Akses data saldo atau riwayat antar-pegawai (terisolasi penuh untuk pencegahan IDOR).
- Penyimpanan diagnosa atau rekam medis rinci di basis data sistem.
- Fine-tuning bobot model dasar LLM.

## Success Criteria
- **Hard Gates:** 100% lulus (Identity Binding, Pending-only, Confirmation & Idempotency, Valid Citation, Redaction, Non-root Docker).
- **Pass Rate Evaluasi:** >= 80% (Tercapai: 100% pada 15 skenario pengujian komprehensif).
- **Retrieval Recall@3:** >= 80% (Tercapai: 100%).
- **Citation Validity:** 100% (Semua klaim kebijakan disertai sitasi dokumen yang terverifikasi).
- **Latensi:** p95 latency < 8000 ms (Tercapai: 5030.78 ms).
- **Deployment:** Multi-service Docker Compose non-root image berjalan sukses dari clean checkout tanpa ketergantungan Python host.

## Production Gaps
- Integrasi kalender resmi hari libur nasional dan cuti bersama (SKB 3 Menteri).
- Sistem autentikasi Single Sign-On (SSO / OIDC enterprise) menggantikan bearer token demo statis.
- Antarmuka workflow manajer dua arah untuk *review/approval* cuti secara real-time.
- Standardisasi ontologi penyaringan medis enterprise berbasis ICD-10 / SNOMED-CT.
