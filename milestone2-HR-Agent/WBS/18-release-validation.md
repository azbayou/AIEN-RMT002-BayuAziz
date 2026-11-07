# WBS-18 — Release validation

- **Target:** seluruh repository dan acceptance flow `docker-delivery.md`.
- **Owner:** Pemilik repo; agent AI membantu diagnosis non-destructive.
- **Dependency:** seluruh WBS sebelumnya.
- **Status:** DONE

## Checklist

- [x] `git diff --check`.
- [x] `pytest -m "not live"` lulus (38 passed).
- [x] Docker image build tanpa API key.
- [x] Container berjalan sebagai non-root (`appuser`, UID 10001).
- [x] Seed berhasil dan `/healthz` mengembalikan `ok`.
- [x] `/readyz` mengembalikan `ready` setelah dependency siap (`ready: true`).
- [x] OpenAPI (`http://localhost:8000/docs`) dan Streamlit (`http://localhost:8501`) dapat dibuka.
- [x] Policy citation valid (`[HR-LEAVE-001]` verified).
- [x] Cross-employee access ditolak (IDOR blocked, trace isolation verified).
- [x] Proposal belum membuat request sebelum confirm.
- [x] Confirm menghasilkan pending-only (`pending_manager_review`) dan replay idempotent.
- [x] Live evaluation 15 kasus menghasilkan release decision (`release_decision: release`, 15/15 passed).
- [x] Tidak ada secret/PII pada Git diff, image, output, atau trace.

## Output

- Test log: `pytest -m "not live"` (38 passed), PostgreSQL integration (2 passed), Self-tests (44 passed), Live test (1 passed).
- Evaluation report: `outputs/evaluation_report.json` (15/15 passed, 100% pass rate, 6/6 hard gates).
- Risk register: `templates/risk-register.csv` & `risk-register.csv` (9 mitigasi dengan rujukan test konkret).
- Architecture & Trust Boundaries: `architecture.md` (6 ADR, diagram Mermaid TB0-TB4).
- Keputusan release: **`READY`** 🚀
