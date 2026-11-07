# WBS-10 — Implementasi `src/agent.py`

- **Target:** `SYSTEM_INSTRUCTIONS` dan `AgentService.run`.
- **Owner:** Agent AI; prompt policy dan release behavior direview pemilik repo.
- **Dependency:** WBS-02, WBS-06, WBS-08, WBS-09.
- **Status:** DONE

## Pekerjaan

1. Tulis instruksi sistem Bahasa Indonesia tentang grounding, validasi sitasi, penanganan data tidak tepercaya, identitas pegawai, larangan chain-of-thought, dan pending-only actions.
2. Implementasikan bounded turn loop (`max_agent_turns`) dan tool call budget (`max_tool_calls`).
3. Validasi sitasi secara ketat terhadap chunks hasil retrieval; wajib abstain jika ada sitasi invalid atau tidak berdasar.
4. Terapkan fallback provider/tool failure yang bebas efek samping (side-effect free).
5. Hitung token usage serta estimasi biaya (*cost*), dan simpan telemetry trace yang telah ter-redact.

## Acceptance criteria

- Sitasi invalid atau halusinasi menghasilkan `Outcome.abstained` dan list sitasi kosong.
- Kegagalan provider atau tool bersifat side-effect free dan trace tidak membocorkan credential/token/PII.
- Turn agent dan pemanggilan tool tidak melebihi batasan yang telah dikonfigurasi di `Settings`.
- Pengajuan cuti menghasilkan `Outcome.action_proposed` dengan proposal ber-TTL.

## Hasil pelaksanaan dan refleksi

- `SYSTEM_INSTRUCTIONS` menegakkan persona "Miyo", asisten HR berbahasa Indonesia yang terikat pada bukti retrieval,
  mengunci identitas ke `AuthContext`, menolak instruksi di dalam dokumen kebijakan (prompt injection defence),
  dan melarang pembocoran chain-of-thought.
- `_citations_from_text` memastikan seluruh dokumen yang dikutip adalah subset dari hasil retrieval run aktif (`cited_ids.issubset(available_ids)`).
  Jika model mengutip ID palsu atau tidak ada sitasi untuk pertanyaan yang memerlukan bukti, agen otomatis beralih ke `Outcome.abstained`.
- Penanganan proposal cuti (`prepare_leave_request`) menetapkan `Outcome.action_proposed` dan mengembalikan objek proposal valid bert-TTL.
- Kegagalan runtime / provider timeout ditangkap dengan aman, mengembalikan pesan penolakan sopan tanpa membuat proposal atau leave request,
  dan error trace diredaksi sebelum disimpan ke database/memori.
- Terverifikasi pada `tests/test_agent_reliability.py` dan `tests/self_test_tools_agent.py`.

## Checkpoint 2026-11-07 — FINAL

- Status: **DONE**
- Bukti:
  - `tests/test_agent_reliability.py`: 7 tests passed (provider failure, invalid citation, mixed citation, malformed tool call, turn budget bounded, stable metadata)
  - `tests/self_test_tools_agent.py`: 3 agent tests passed (multi-turn with valid citation, proposal outcome, tool budget exceeded)
  - Seluruh test non-live lulus 100%
- Hard gates terkait (Valid Citation & Abstain, Pending-only Actions, Redacted Trace & PII): TERPENUHI.
