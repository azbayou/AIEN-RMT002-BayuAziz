# Work Breakdown Structure — Milestone 2 HR Agent

Folder ini memecah pekerjaan implementasi menjadi unit yang bisa dikerjakan oleh pemilik repo
atau agent AI. Setiap file WBS memetakan satu file/komponen kode utama.

## Urutan eksekusi

1. [00-baseline-dan-definition-of-done.md](./00-baseline-dan-definition-of-done.md)
2. [01-domain.py.md](./01-domain.py.md)
3. [02-security.py.md](./02-security.py.md)
4. [03-contracts-dan-config.md](./03-contracts-dan-config.md)
5. [04-repository.py.md](./04-repository.py.md)
6. [05-cache.py.md](./05-cache.py.md)
7. [06-providers.py.md](./06-providers.py.md)
8. [07-setup_lab.py.md](./07-setup_lab.py.md)
9. [08-retrieval.py.md](./08-retrieval.py.md)
10. [09-tools.py.md](./09-tools.py.md)
11. [10-agent.py.md](./10-agent.py.md)
12. [11-api.py.md](./11-api.py.md)
13. [12-Dockerfile.md](./12-Dockerfile.md)
14. [13-tests-unit-domain-security.md](./13-tests-unit-domain-security.md)
15. [14-tests-repository-actions.md](./14-tests-repository-actions.md)
16. [15-tests-agent-api.md](./15-tests-agent-api.md)
17. [16-evaluation-runner.md](./16-evaluation-runner.md)
18. [17-monitoring-dokumentasi.md](./17-monitoring-dokumentasi.md)
19. [18-release-validation.md](./18-release-validation.md)

## Fase Penyempurnaan Kualitas & Logika Bisnis (Post-Audit)

Kerjakan secara berurutan dari P0 sampai P3. Setiap file sudah dilengkapi snippet kode siap pakai, batasan file yang boleh diedit, dan perintah `pytest` untuk model agent berukuran kecil:

20. [19-P0-delivery-dan-evaluator.md](./19-P0-delivery-dan-evaluator.md) — Buat `.env.example`, perbaiki false-pass evaluator, dan lengkapi metrik `recall@3` & `citation_validity`.
21. [20-P1-konfirmasi-dan-saldo.md](./20-P1-konfirmasi-dan-saldo.md) — Reservasi saldo cuti pending, re-validasi overlap & saldo saat konfirmasi, prioritas replay atas expiry, dan pencegahan reuse idempotency key.
22. [21-P1-agent-error-dan-sitasi.md](./21-P1-agent-error-dan-sitasi.md) — Pisahkan `DomainError` (`blocked`) dari `error_rate` sistem, perketat gate sitasi, lengkapi `retrieved_document_ids` di trace, dan deduplikasi tiket HR.
23. [22-P2-hybrid-rag-dan-seed.md](./22-P2-hybrid-rag-dan-seed.md) — Ubah lexical search PostgreSQL menjadi `OR` dengan filter stopword & `effective_date`, aktifkan bobot keyword reranking, cegah cache saat embedding degraded, dan bersihkan chunk versi lama.
24. [23-P3-api-monitoring-dan-docs.md](./23-P3-api-monitoring-dan-docs.md) — Konsistensi `ProblemDetail` RFC-7807, pengecekan `policy_chunks` pada `/readyz`, metrik monitoring tambahan, perbaikan persona `README.md`, dan pengisian dokumen `templates/`.

## Fase Fitur Tambahan Enterprise (Extra Features — Aman terhadap Parameter Penilaian)

Seluruh fitur tambahan di bawah ini dirancang dengan arsitektur *non-breaking* (tidak menyentuh `demo_personas.json`, `app.py`, `TOOL_SCHEMAS` default, atau `requirements.txt`, serta menjaga Hard Gate `pending_manager_review` pada konfirmasi pegawai):

25. [24-extra-db-account-dan-password-login.md](./24-extra-db-account-dan-password-login.md) — Rombak skema akun (`username`, `password_hash` PBKDF2-HMAC-SHA256, `department`, `manager_id`), tambah akun Manager (`MGR-001`), endpoint `POST /api/v1/auth/login`, dan UI login password di `app2.py`.
26. [25-extra-manager-approval-workflow.md](./25-extra-manager-approval-workflow.md) — Workflow persetujuan/penolakan cuti khusus manusia (Manager) via `POST /api/v1/manager/leave-requests/{id}/review`, pemotongan saldo atomik saat `approved`, pelepasan kuota saat `rejected`, tabel `approval_audit_logs`, dan panel UI Manager di `app2.py`.
27. [26-extra-chatbot-analytics.md](./26-extra-chatbot-analytics.md) — Injeksi tool dinamis `get_team_hr_analytics` khusus role `manager` & `monitoring_admin` (`get_tools_for_role`), agregasi SQL terisolasi hierarki tim, dan endpoint `GET /api/v1/analytics/overview`.
28. [27-extra-speech-to-text-mic.md](./27-extra-speech-to-text-mic.md) — Tombol mikrofon (`st.audio_input`) di `app2.py`, endpoint `POST /api/v1/audio/transcribe` berbasis JSON Base64 (tanpa dependency tambahan), serta adapter Whisper di `OpenAIProvider` & fallback deterministik di `DeterministicProvider`.
29. [28-extra-sick-leave-attachment-review.md](./28-extra-sick-leave-attachment-review.md) — Unggah lampiran surat dokter (PDF/PNG/JPG) khusus cuti sakit ke PostgreSQL/Neon (`BYTEA`), validasi *magic bytes* & isolasi privasi medis (`HR-LEAVE-002`), serta panel pratinjau Gambar/PDF bagi Manajer di `app2.py` saat proses approval.

## Pembagian kerja

- **Agent AI:** implementasi terisolasi, refactor kecil, test unit, review kontrak, dan
  dokumentasi teknis berdasarkan acceptance criteria di masing-masing WBS.
- **Pemilik repo:** keputusan schema/migration, kredensial provider, aturan HR yang ambigu,
  review keamanan, uji Docker end-to-end, dan keputusan release.
- Jangan mengerjakan WBS yang dependency-nya belum selesai.
- Setelah tiap WBS selesai, jalankan test yang tercantum dan update status pada file tersebut.

## Status

Semua item awal berstatus `TODO`. Status yang disarankan: `TODO`, `IN PROGRESS`, `BLOCKED`,
atau `DONE`.

## Prompt

Tolong kerjakan task dari file @[WBS/<NOMOR>-<NAMA_FILE>.md].

Ikuti instruksi dan batasan ketat berikut:
1. Scope Kerja:
   - Target implementasi HANYA pada file: @[src/<NAMA_FILE>.py]
   - JANGAN mengedit file lain di folder src/ atau tests/ tanpa persetujuan saya.
   
2. Alur Eksekusi:
   - Langkah 1: Baca file WBS terkait dan baca file test pendukungnya di @[tests/<NAMA_TEST>.py].
   - Langkah 2: Pahami Acceptance Criteria dan kontrak data yang ada di @[src/contracts.py].
   - Langkah 3: Implementasikan fungsi/class yang diminta di file target. Pertahankan docstring & typing.
   - Langkah 4: Jalankan pytest khusus untuk modul ini: `pytest tests/<NAMA_TEST>.py -v`.
   
3. Hard Gates & Larangan:
   - Dilarang memodifikasi file test agar tesnya lulus (kode implementasi yang harus menyesuaikan test).
   - Patuhi Hard Gates dari WBS-00 (tidak boleh ada bypass auth, employee_id wajib dari AuthContext, dll).
   - Jangan menambahkan library/dependency baru di luar `requirements.txt`.

4. Output yang Diharapkan:
   - Pastikan semua test di unit test tersebut PASSED.
   - Jika test lulus, perbarui status di file WBS menjadi `DONE` beserta catatan singkatnya.
   - Laporkan ringkasan perubahan dan output terminal hasil pytest.