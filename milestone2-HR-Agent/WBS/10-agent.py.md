# WBS-10 — Implementasi `src/agent.py`

- **Target:** `SYSTEM_INSTRUCTIONS` dan `AgentService.run`.
- **Owner:** Agent AI; prompt policy dan release behavior direview pemilik repo.
- **Dependency:** WBS-02, WBS-06, WBS-08, WBS-09.
- **Status:** TODO

## Pekerjaan

1. Tulis instruksi Bahasa Indonesia tentang grounding, citation, untrusted text, identity,
   abstention, pending-only action, dan larangan chain-of-thought.
2. Implement bounded turn/tool loop.
3. Validasi citation terhadap retrieved chunks.
4. Implement fallback provider/tool failure tanpa side effect.
5. Hitung usage/cost dan simpan trace ter-redact.

## Acceptance criteria

- Invalid citation menghasilkan `abstained` dan citation kosong.
- Provider failure side-effect free dan trace tidak membocorkan token.
- Turn dan tool call tidak melebihi settings.
