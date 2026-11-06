# WBS-18 — Release validation

- **Target:** seluruh repository dan acceptance flow `docker-delivery.md`.
- **Owner:** Pemilik repo; agent AI membantu diagnosis non-destructive.
- **Dependency:** seluruh WBS sebelumnya.
- **Status:** TODO

## Checklist

- [ ] `git diff --check`.
- [ ] `pytest -m "not live"` lulus.
- [ ] Docker image build tanpa API key.
- [ ] Container berjalan sebagai non-root.
- [ ] Seed berhasil dan `/healthz` mengembalikan `ok`.
- [ ] `/readyz` mengembalikan `ready` setelah dependency siap.
- [ ] OpenAPI dan Streamlit dapat dibuka.
- [ ] Policy citation valid.
- [ ] Cross-employee access ditolak.
- [ ] Proposal belum membuat request sebelum confirm.
- [ ] Confirm menghasilkan pending-only dan replay idempotent.
- [ ] Live evaluation 15 kasus menghasilkan release decision.
- [ ] Tidak ada secret/PII pada Git diff, image, output, atau trace.

## Output

- Test log.
- Evaluation report.
- Risk register.
- Screenshot/demo evidence.
- Keputusan release: `READY`, `READY WITH RISKS`, atau `BLOCKED`.
