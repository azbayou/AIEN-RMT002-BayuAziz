# WBS-15 — Test agent dan API

- **Target:** `tests/test_agent_reliability.py`, `tests/test_api.py`, `tests/test_live_api.py`,
  `tests/test_supplied_ui.py`.
- **Owner:** Agent AI; live test dan acceptance dilakukan pemilik repo.
- **Dependency:** WBS-10, WBS-11, WBS-12.
- **Status:** DONE

## Pekerjaan

1. Jalankan deterministic provider tests untuk policy, balance, action, failure, dan citation.
2. Tambahkan malformed tool call, tool budget, model timeout, Redis outage, dan DB outage.
3. Jalankan API auth/authorization/trace tests.
4. Jalankan UI contract tests.
5. Jalankan live tests hanya dengan `RUN_LIVE_TESTS=1`.

## Acceptance criteria

- Non-live suite lulus tanpa network.
- Live policy response memiliki citation valid dan outcome `answered`.
- Failure path aman dan tidak membuat side effect.

## Checkpoint 2026-11-07 — FINAL

- Status: **DONE**
- Non-live deterministic suite: 38 passed tanpa network (`tests/test_agent_reliability.py`, `tests/test_api.py`, `tests/test_supplied_ui.py`, `tests/test_tools.py`).
- Live policy test (`tests/test_live_api.py`): **PASSED** dengan `RUN_LIVE_TESTS=1` against running Docker API (`http://localhost:8000`). Respon memiliki outcome `answered` dan sitasi valid `[HR-LEAVE-001]`.
- Failure paths (malformed tool, turn budget, provider failure, invalid citation) terbukti side-effect free dan trace diredaksi dengan aman.
- UI contract dan auth matrix (admin vs employee vs unauthenticated) terverifikasi 100%.
- Hard gates terkait: TERPENUHI 100%.
