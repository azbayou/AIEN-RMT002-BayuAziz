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

## Checkpoint

- Instruksi sistem Bahasa Indonesia mencakup grounding, untrusted text, identity binding,
  pending-only action, abstention, dan larangan chain-of-thought.
- Agent menjalankan bounded turn/tool loop, memvalidasi citation terhadap chunk retrieval,
  menghitung usage/cost, serta mengembalikan response terstruktur.
- Provider/tool failure menghasilkan abstention dan trace ter-redact tanpa membuat approval
  atau leave request tambahan.
- Tes reliability agent dan compile sudah dijalankan.

## TODO berikutnya

1. Tambahkan test tool-loop multi-turn, tool budget, model timeout, proposal outcome, dan
   citation valid yang menghasilkan `Citation`.
2. Perbaiki state format input/output provider agar kompatibel penuh dengan Responses API
   conversation items.
3. Pastikan error trace tidak tersimpan dua kali dan tambahkan status error pada ringkasan
   tool ketika tool gagal.
4. Integrasikan error mapping dan authorization endpoint pada WBS-11.
