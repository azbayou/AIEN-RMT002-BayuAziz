# WBS-16 — Implementasi evaluator

- **Target:** `src/run_evaluation.py`, `data/evaluation_cases.json`,
  `templates/evaluation-report.md`.
- **Owner:** Agent AI; release decision oleh pemilik repo.
- **Dependency:** WBS-11, WBS-15.
- **Status:** TODO

## Pekerjaan

1. Tambahkan CLI `--base-url` dan `--token`.
2. Jalankan semua 15 cases.
3. Validasi expected documents, tools, outcomes, forbidden facts, dan hard gates.
4. Simpan actual outcome, trace ID, latency, usage, dan error.
5. Tulis `outputs/evaluation_report.json` dan release decision.

## Acceptance criteria

- Minimal 15 case tercatat.
- Hard gate failure memblokir release.
- Report dapat disalin dari container dengan command di `docker-delivery.md`.
