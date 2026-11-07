# WBS-17 — Monitoring, arsitektur, dan dokumentasi

- **Target:** `architecture.md`, `templates/architecture.md`,
  `templates/risk-register.csv`, `risk-register.csv`, `data/monitoring_rules.json`, `README.md`.
- **Owner:** Pemilik repo; agent AI membantu draft dan consistency check.
- **Dependency:** WBS-11, WBS-16.
- **Status:** DONE

## Pekerjaan

1. Finalkan diagram trust boundary, cache degradation, tool loop, confirmation, telemetry,
   evaluator, dan human review.
2. Isi ADR decision/context/alternatives/trade-offs/follow-up.
3. Buat risk register dengan owner, mitigation, evidence, dan severity.
4. Implementasikan/ dokumentasikan alert error-rate dan p95 latency.
5. Update README hanya dengan command yang sudah diverifikasi.

## Acceptance criteria

- Dokumentasi tidak mengklaim fitur yang belum berjalan.
- Monitoring menyediakan metric, threshold, owner, dan response.
- Risk register merujuk ke test atau evidence yang dapat dijalankan.

## Checkpoint 2026-11-07 — FINAL

- Status: **DONE**
- **Arsitektur & Trust Boundaries (`architecture.md` & `templates/architecture.md`):**
  - Diagram Mermaid lengkap: Komponen End-to-End, Trust Boundaries (TB0 s/d TB4), Hybrid RAG RRF $k=60$ flow, Two-Phase Pending-Only Action flow, Circuit-breaking Cache Degradation flow, dan Telemetry Redaction pipeline.
  - 6 Architecture Decision Records (ADR-001 s/d ADR-006) didokumentasikan lengkap dengan Context, Decision, Alternatives Considered, Trade-offs, dan Production Follow-up.
- **Risk Register (`templates/risk-register.csv` & `risk-register.csv`):**
  - 9 risiko enterprise (R-001 s/d R-009) dilengkapi mitigasi konkret, owner penanggung jawab, dan **rujukan test/evidence yang dapat dijalankan** (`test_actions.py`, `test_agent_reliability.py`, `test_retrieval_security.py`, `test_repository_postgres.py`, serta evaluation cases).
  - Status seluruh risiko: **Mitigated**.
- **Monitoring Operasional (`data/monitoring_rules.json`):**
  - Rule dinamis `agent-error-spike` dan `agent-latency-p95` dengan metrik, threshold, operator, minimum samples, owner (AI Platform), dan response actionable.
  - Endpoint `/api/v1/monitoring/summary` terverifikasi mengevaluasi rule secara dinamis dari database trace PostgreSQL.
- **Dokumentasi README (`README.md`):**
  - Panduan Docker delivery tervalidasi 100% dari checkout bersih tanpa Python host.
  - Dokumentasi URL akses Streamlit (`:8501`), FastAPI docs (`:8000/docs`), health/readiness, perintah testing, dan ringkasan 6 hard gates.
  - Tidak ada klaim fitur yang belum berjalan; seluruh perintah telah diverifikasi di container live.
