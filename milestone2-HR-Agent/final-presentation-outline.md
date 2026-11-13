# Final Presentation Outline — Miyo HR Assistant (PT Nusantara Digital)

---

## Slide 1: User Problem and Measurable Success Criteria
- **User Problem:**
  - Karyawan kesulitan menavigasi puluhan halaman dokumen regulasi ketenagakerjaan dan SOP internal HR untuk mengetahui hak cuti, tunjangan, dan aturan kerja fleksibel (WFH).
  - Proses manual membebani tim HR dengan pertanyaan berulang dan risiko ketidaksesuaian interpretasi hukum.
  - Risiko over-automation: Agen AI tanpa batas dapat secara tidak sah menyetujui pengajuan cuti atau membocorkan data pribadi/medis karyawan lain.
- **Measurable Success Criteria:**
  - **Retrieval Recall@3 $\ge 80\%$** dan **Citation Validity $= 100\%$** (tanpa halusinasi).
  - **Zero Unauthorized Approval:** 100% permohonan cuti berstatus `pending_manager_review` dengan konfirmasi 2 fase.
  - **Zero Cross-Employee Access (IDOR Prevention):** 100% pemblokiran terhadap percobaan pembacaan data antar pegawai.
  - **Data Privacy & Redaction:** 100% penyensoran terhadap informasi medis sensitif dan PII.
  - **Performance:** Latensi p95 $< 8$ detik, ketersediaan sistem $> 99.5\%$.

---

## Slide 2: Why RAG + Bounded Agent
- **Kelemahan Model Konvensional:**
  - *Context Stuffing (Prompt Engineering):* Biaya token mahal, atensi terdegradasi (*lost in the middle*).
  - *Fine-Tuning:* Statis, mahal untuk diperbarui, dan tidak memiliki jejak sitasi dokumen hukum yang dapat diaudit.
- **Pendekatan Miyo (RAG + Bounded Agent):**
  - **Grounded RAG:** Mengambil kutipan dokumen Markdown resmi dari PostgreSQL via pgvector & pencarian leksikal RRF (*Reciprocal Rank Fusion*).
  - **Bounded Agent Turns:** Dibatasi maksimal 4 putaran dan 6 pemanggilan tool untuk mencegah loop tak terbatas (*runaway cost*).
  - **Strict Evidence Requirement:** Model wajib melakukan *abstain* jika dokumen kebijakan tidak ditemukan atau sitasi tidak valid.

---

## Slide 3: Architecture and Trust Boundaries
- **Komponen Sistem:**
  - **Presentation Layer:** Dual-Frontends — Modern Client-Side Web SPA (HTML5 + Tailwind + Vue 3 di port 8000) dan Streamlit Portal di port 8502.
  - **Application Layer:** FastAPI Orchestrator (port 8000) non-root UID 10001 dengan stateless Bearer Token.
  - **Data Layer:** PostgreSQL 16 (pgvector) untuk embedding 1536-d dan ACID transactions; Redis 7 untuk caching resilien.
- **Trust Boundaries (TB):**
  - **TB 1 (Client):** Input pengguna dan audio mikrofon diperlakukan tidak tepercaya (*untrusted*).
  - **TB 2 (API Gateway):** Otentikasi identitas strictly via SHA-256 Bearer Token `AuthContext`.
  - **TB 3 (Repository & DB):** Query database selalu difilter berdasarkan `auth.employee_id` (predikat kepemilikan mutlak).
  - **TB 4 (External LLM Provider):** Dokumen kebijakan disuntikkan sebagai data eksternal, bukan instruksi sistem.

---

## Slide 4: Retrieval and Citation Design
- **Hybrid Search Architecture:**
  - Pencarian leksikal (*tsvector/tsquery* Bahasa Indonesia) digabungkan dengan pencarian semantik vektor (*HNSW cosine distance*).
  - Penggabungan peringkat menggunakan *Reciprocal Rank Fusion (RRF)* dengan konstanta $k=60$.
- **Citation Guardrail & Verification:**
  - Format sitasi baku: `[DOCUMENT_ID]` (misal: `[HR-LEAVE-001]`).
  - Pipeline memvalidasi bahwa `cited_ids.issubset(retrieved_ids)`. Jika model mengutip ID fiktif atau dokumen yang tidak ada dalam chunk hasil pencarian, output otomatis dibatalkan menjadi `Outcome.abstained`.

---

## Slide 5: Tool and Confirmation Design
- **Katalog Tool yang Diizinkan (Allow-listed Tools):**
  1. `search_hr_policy(query, top_k)`: Pencarian regulasi perusahaan.
  2. `get_my_leave_balance()`: Membaca saldo pribadi tanpa parameter input (`additionalProperties: false`).
  3. `prepare_leave_request(leave_type, start_date, end_date, reason)`: Membuat draft proposal.
  4. `create_hr_ticket(category, summary)`: Pembuatan tiket eskalasi kasus khusus.
- **Action Safety Dua Fase (Two-Phase Commitment):**
  - Fase 1: Pembuatan proposal cuti berbatas waktu (TTL 15 menit) tanpa menulis ke tabel `leave_requests`.
  - Fase 2: Konfirmasi eksplisit pengguna via `POST /api/v1/action-proposals/{id}/confirm` dengan kunci idempotensi unik (`idempotency_key`) untuk mencegah duplikasi data.
  - Seluruh permohonan terkunci pada status `pending_manager_review`.

---

## Slide 6: FastAPI and Deployment
- **Docker Delivery Contract:**
  - Multi-container orchestration: `api`, `postgres`, `redis`, `streamlit`.
  - Image hardening: Berjalan sebagai user non-root `appuser:10001`, build tanpa ketergantungan pada runtime API key.
- **Health & Readiness Probes:**
  - `/healthz`: Memeriksa ketersediaan proses aplikasi (HTTP 200).
  - `/readyz`: Memverifikasi konektivitas database, redis, dan kesiapan konfigurasi model embedding.
- **Dual Presentation Deployment:**
  - Modern Web SPA disajikan langsung dari static route FastAPI di `http://localhost:8000/`.
  - Streamlit service tetap berjalan di `http://localhost:8502` untuk menjamin kepatuhan grading otomatis.

---

## Slide 7: Evaluation Results and Failure Analysis
- **Hasil Evaluasi Live (15 Skenario Uji):**
  - **Overall Pass Rate:** $100\%$ ($15/15$ kasus lulus).
  - **Hard Gates:** $6/6$ terpenuhi ($100\%$).
  - **Retrieval Recall@3:** $1.0$ ($100\%$).
  - **Citation Validity:** $1.0$ ($100\%$).
  - **Tool Selection Accuracy:** $1.0$ ($100\%$).
- **Failure Analysis & Edge Cases Tested:**
  - *Prompt Injection:* Berhasil dinetralisir, model menolak membocorkan token sistem.
  - *PII & Medical Redaction:* Gejala medis spesifik otomatis tersensor menjadi `[REDACTED_MEDICAL]`, sementara nama cuti administratif `Cuti Sakit` tetap terjaga utuh.
  - *Leave Overlap:* Permohonan yang bertumpang tindih dengan jadwal aktif otomatis diblokir oleh domain validator.

---

## Slide 8: Monitoring Evidence
- **Observabilitas Real-Time (`/api/v1/monitoring/summary`):**
  - Metrik latensi: p50 $= 3.7$ detik, p95 $= 5.0$ detik.
  - Telemetri token: Rata-rata 1.687 token input dan 142 token output per interaksi.
  - Audit Jejak: Setiap interaksi tercatat dengan `trace_id` unik, status outcome, tool calls, dan rincian penggunaan token.
- **Active Guardrail Alerts:**
  - Pemantauan otomatis terhadap ambang batas latensi, *abstain rate*, dan *error rate* berbasis `data/monitoring_rules.json`.

---

## Slide 9: Governance Controls and Residual Risks
- **Governance Controls (Risk Register):**
  - Mengelola 9 risiko terpetakan dalam `risk-register.csv` dengan status 100% *Mitigated*.
  - Pemisahan peran (*RBAC*): Regular Employee, Manager, dan Monitoring Admin.
- **Residual Risks & Batasan Sistem:**
  - *Kalender Libur Nasional:* Saat ini baru memperhitungkan akhir pekan, belum tersambung ke API SKB 3 Menteri resmi.
  - *Kamus Medis Statis:* Masih mengandalkan regex lokal `data/medical_terms.json`, belum terhubung ke ontologi ICD-10 terenkripsi.
  - *Persetujuan Bersyarat:* Logika persetujuan manajer bertingkat (*multi-tier approval*) untuk cuti panjang ($> 14$ hari) masih memerlukan pengembangan lanjut.

---

## Slide 10: Demo, Limitations, and Next Steps
- **Live Demo Flow (5–7 Menit):**
  1. Login & Tanya Jawab Regulasi (Cuti Tahunan & WFH) dengan Sitasi Terverifikasi.
  2. Percobaan Akses Lintas Pegawai (Pembuktian Isolasi Data & IDOR Prevention).
  3. Alur Pengajuan Cuti Interaktif: Formulir Modal $\to$ Proposal Chat $\to$ Konfirmasi 1-Klik $\to$ Status `pending_manager_review`.
  4. Penyensoran Data Medis & Audit Jejak Telemetri.
  5. Antarmuka Modern Web SPA (Perekaman Suara Asli & Tema Gelap/Terang).
- **Next Steps:**
  - Integrasi API Kalender Libur Nasional Kementerian Ketenagakerjaan.
  - Implementasi *Slack / Microsoft Teams webhook* untuk notifikasi persetujuan manajer secara real-time.
  - Audit sertifikasi kepatuhan UU Perlindungan Data Pribadi (UU PDP).
