# WBS-11 — Implementasi `src/api.py`

- **Target:** runtime wiring dan delapan endpoint FastAPI.
- **Owner:** Agent AI; API/security acceptance oleh pemilik repo.
- **Dependency:** WBS-04, WBS-05, WBS-06, WBS-08, WBS-09, WBS-10.
- **Status:** TODO

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
