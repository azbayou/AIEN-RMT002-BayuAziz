# WBS-06 — Implementasi `src/providers.py`

- **Target:** `OpenAIProvider` dan `DeterministicProvider`.
- **Owner:** Agent AI; kredensial/model diputuskan pemilik repo.
- **Dependency:** WBS-02, WBS-03.
- **Status:** TODO

## Pekerjaan

1. Implement Responses API dengan `store=False`.
2. Kirim strict tool schemas dan safety identifier yang sudah di-hash.
3. Implement batch embeddings, timeout, bounded retry transient, dan token usage.
4. Buat fake provider deterministic untuk policy, balance, action, dan failure scenarios.

## Acceptance criteria

- Test tidak membutuhkan network atau API key.
- Provider failure menghasilkan exception yang dapat ditangani agent.
- Retry tidak menggandakan side effect.
