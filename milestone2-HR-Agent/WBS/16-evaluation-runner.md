# WBS-16 — Implementasi evaluator

- **Target:** `src/run_evaluation.py`, `data/evaluation_cases.json`,
  `templates/evaluation-report.md`.
- **Owner:** Agent AI; release decision oleh pemilik repo.
- **Dependency:** WBS-11, WBS-15.
- **Status:** DONE

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

## Checkpoint 2026-11-07 — FINAL

- Status: **DONE**
- Evaluasi komprehensif dijalankan secara live terhadap container Compose (`http://localhost:8000`) dengan model `gpt-6-luna`.
- Hasil evaluasi (`outputs/evaluation_report.json`):
  - Total kasus: **15 dari 15 tercatat**
  - Kasus lulus: **15 passed (100% pass rate / 1.0)**
  - Hard gate: **6 dari 6 passed (100%)**
  - Latensi: p50 = 3736.7 ms, p95 = 5030.78 ms
  - Keputusan rilis: **`release_decision: release`**
- Seluruh 6 hard gate (identity isolation, pending-only proposal, confirmation & idempotency, redaction & PII, lead time/domain checks, valid citations) terpenuhi secara sempurna tanpa celah.
