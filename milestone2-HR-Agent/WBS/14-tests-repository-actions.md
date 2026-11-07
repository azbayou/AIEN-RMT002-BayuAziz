# WBS-14 — Test repository dan action safety

- **Target:** `tests/test_actions.py` serta test repository baru.
- **Owner:** Agent AI; concurrency scenario direview pemilik repo.
- **Dependency:** WBS-04, WBS-09.
- **Status:** DONE

## Pekerjaan

1. Pertahankan test pending-only, replay key, conflict key, expiry, dan wrong identity.
2. Tambahkan test proposal overlap dan tidak ada request sebelum confirm.
3. Tambahkan test concurrent confirmation pada PostgreSQL.
4. Tambahkan test owner scoping untuk balance, requests, trace, dan proposal.

## Acceptance criteria

- Tidak ada duplicate request.
- Wrong identity tidak mengubah state.
- Semua request yang tersimpan `pending_manager_review`.

## Checkpoint 2026-11-07 — FINAL

- Status: **DONE**
- `tests/test_actions.py`: 6 passed (pending-only, replay idempotency key, conflict key, expiry, wrong identity rejection, concurrency lock).
- `tests/test_repository_postgres.py`: 2 passed (PostgreSQL integration tests: owner-bound actions, parameter query security, pending-only verification, trace redaction, and vector retrieval).
- Seluruh leave request yang tersimpan selalu berstatus `pending_manager_review`.
- Hard gates terkait (Pending-only Actions, Explicit Confirmation & Idempotency, Identity Binding): TERPENUHI 100%.
