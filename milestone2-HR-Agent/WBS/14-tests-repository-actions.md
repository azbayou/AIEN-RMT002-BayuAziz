# WBS-14 — Test repository dan action safety

- **Target:** `tests/test_actions.py` serta test repository baru.
- **Owner:** Agent AI; concurrency scenario direview pemilik repo.
- **Dependency:** WBS-04, WBS-09.
- **Status:** TODO

## Pekerjaan

1. Pertahankan test pending-only, replay key, conflict key, expiry, dan wrong identity.
2. Tambahkan test proposal overlap dan tidak ada request sebelum confirm.
3. Tambahkan test concurrent confirmation pada PostgreSQL.
4. Tambahkan test owner scoping untuk balance, requests, trace, dan proposal.

## Acceptance criteria

- Tidak ada duplicate request.
- Wrong identity tidak mengubah state.
- Semua request yang tersimpan `pending_manager_review`.
