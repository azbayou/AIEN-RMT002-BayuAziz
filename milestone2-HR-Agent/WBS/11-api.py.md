# WBS-11 — Implementasi `src/api.py`

- **Target:** runtime wiring dan delapan endpoint FastAPI.
- **Owner:** Agent AI; API/security acceptance oleh pemilik repo.
- **Dependency:** WBS-04, WBS-05, WBS-06, WBS-08, WBS-09, WBS-10.
- **Status:** CHECKPOINT - IMPLEMENTED

## Endpoint

`/healthz`, `/readyz`, `/api/v1/chat`,
`/api/v1/action-proposals/{proposal_id}/confirm`,
`/api/v1/leave-requests/me`, `/api/v1/traces/{trace_id}`,
`/api/v1/monitoring/summary`, dan `/api/v1/monitoring/alerts`.

## Acceptance criteria

- `tests/test_api.py` lulus.
- Auth invalid menghasilkan 401; employee monitoring menghasilkan 403.
- Trace employee lain menghasilkan 403; proposal employee lain menghasilkan 404.
- Problem detail tidak berisi stack trace, token, atau secret.
- `create_app` dapat menerima dependency override untuk test.

## Checkpoint

- `create_app` sekarang menyediakan delapan endpoint, dependency injection untuk test,
  bearer authentication, owner checks, admin-only monitoring, dan proposal conflict mapping.
- `/readyz` memeriksa database, cache, dan configuration readiness; cache degraded tidak
  mengubah cache menjadi source of truth.
- Request validation dikembalikan sebagai problem detail aman tanpa stack trace.
- Runtime wiring menghubungkan repository, cache, provider, retrieval, tools, dan agent.
- `tests/test_api.py` lulus setelah deterministic provider diperbaiki untuk menyelesaikan
  tool result menjadi jawaban final dengan citation valid.

## TODO berikutnya

1. Perbarui fixture test agar memakai bearer token sintetis yang berbeda untuk setiap persona;
   token literal yang sama tidak dapat membuktikan employee-vs-admin authorization.
2. Tambahkan test seluruh endpoint, invalid token, invalid body, proposal owner/expiry,
   admin trace access, readiness degraded, dan alerts rules.
3. Implementasikan `PostgresRepository` sebelum memakai `build_runtime` production.
4. Integrasikan evaluasi monitoring rules dan problem-detail trace ID setelah telemetry/API
   contracts final.
