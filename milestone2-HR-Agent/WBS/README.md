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