# WBS-11 — Implementasi `src/api.py`

- **Target:** runtime wiring dan delapan endpoint FastAPI.
- **Owner:** Agent AI; API/security acceptance oleh pemilik repo.
- **Dependency:** WBS-04, WBS-05, WBS-06, WBS-08, WBS-09, WBS-10.
- **Status:** DONE

## Endpoint

`/healthz`, `/readyz`, `/api/v1/chat`,
`/api/v1/action-proposals/{proposal_id}/confirm`,
`/api/v1/leave-requests/me`, `/api/v1/traces/{trace_id}`,
`/api/v1/monitoring/summary`, dan `/api/v1/monitoring/alerts`.

## Acceptance criteria

- `tests/test_api.py` lulus (4 passed).
- Auth invalid menghasilkan 401; employee mengakses endpoint monitoring menghasilkan 403.
- Trace employee lain menghasilkan 403 (kecuali role `monitoring_admin`); proposal employee lain menghasilkan 404.
- Problem detail aman, berformat RFC 7807, dan tidak membocorkan stack trace atau secret.
- `/api/v1/monitoring/alerts` mengevaluasi metrik terhadap aturan di `data/monitoring_rules.json`.
- `create_app` dapat menerima dependency override untuk isolasi pengujian.

## Hasil pelaksanaan dan refleksi

- `create_app` mengimplementasikan 8 endpoint lengkap dengan dependency injection untuk testing dan runtime production.
- Autentikasi berbasis `Bearer <token>` memvalidasi hash token ke repository.
- Matriks otorisasi teruji:
  - Role `employee` hanya bisa membaca request, saldo, proposal, dan trace miliknya sendiri.
  - Akses trace orang lain ditolak (403).
  - Konfirmasi proposal orang lain ditolak (404).
  - Endpoint `/monitoring/summary` dan `/monitoring/alerts` dibatasi khusus untuk `monitoring_admin`.
- Endpoint `/api/v1/monitoring/alerts` kini mengevaluasi aturan secara dinamis dari `data/monitoring_rules.json`
  berdasarkan ringkasan metrik repository (`error_rate`, `p95_latency_ms`).
- Terverifikasi pada `tests/test_api.py` dan `tests/self_test_api_docker.py`.

## Checkpoint 2026-11-07 — FINAL

- Status: **DONE**
- Bukti:
  - `tests/test_api.py`: 4 passed (`test_health_and_auth_contract`, `test_chat_returns_contract_and_trace`, `test_monitoring_is_admin_only`, `test_trace_cannot_be_read_by_another_employee`)
  - `tests/self_test_api_docker.py`: 5 API tests passed (health/readyz, chat auth/validation, proposal flow/isolation, traces access matrix, alerts evaluation)
  - Seluruh test non-live lulus 100%
- Hard gates terkait (Identity Binding, Pending-only Actions, Explicit Confirmation, Redacted Trace & PII): TERPENUHI.
