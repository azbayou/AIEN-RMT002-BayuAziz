# WBS-15 — Test agent dan API

- **Target:** `tests/test_agent_reliability.py`, `tests/test_api.py`, `tests/test_live_api.py`,
  `tests/test_supplied_ui.py`.
- **Owner:** Agent AI; live test dan acceptance dilakukan pemilik repo.
- **Dependency:** WBS-10, WBS-11, WBS-12.
- **Status:** TODO

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
