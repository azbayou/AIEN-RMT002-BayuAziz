# WBS-06 — Implementasi `src/providers.py`

- **Target:** `OpenAIProvider` dan `DeterministicProvider`.
- **Owner:** Agent AI; kredensial/model diputuskan pemilik repo.
- **Dependency:** WBS-02, WBS-03.
- **Status:** CHECKPOINT - IMPLEMENTED

## Pekerjaan

1. Implement Responses API dengan `store=False`.
2. Kirim strict tool schemas dan safety identifier yang sudah di-hash.
3. Implement batch embeddings, timeout, bounded retry transient, dan token usage.
4. Buat fake provider deterministic untuk policy, balance, action, dan failure scenarios.

## Acceptance criteria

- Test tidak membutuhkan network atau API key.
- Provider failure menghasilkan exception yang dapat ditangani agent.
- Retry tidak menggandakan side effect.

## Checkpoint

- `OpenAIProvider` sudah menyediakan Responses API dan batch embeddings.
- Responses request memakai `store=False`, safety identifier di-hash, tool schema
  diteruskan apa adanya, serta usage token dipetakan ke `ModelTurn`.
- Retry dibatasi dan hanya diterapkan pada error transient; kegagalan terakhir diteruskan
  ke agent sehingga tidak menjadi success-shaped fallback.
- `DeterministicProvider` tidak memakai network/API key, menghasilkan embedding deterministik,
  dan memicu tool call sederhana untuk skenario policy/saldo.
- Validasi smoke test dilakukan dengan provider fake dan kompilasi modul.

## TODO berikutnya

1. Tambahkan unit test dengan fake OpenAI client untuk memverifikasi `store=False`, hashed
   safety identifier, parsing function call, usage, batch embedding, dan retry count.
2. Pastikan WBS-09 menghasilkan schema tool strict yang kompatibel dengan `responses.create`.
3. Hubungkan timeout dari `Settings.model_timeout_seconds` ke client/provider secara eksplisit.
4. Verifikasi compatibility terhadap versi SDK OpenAI yang digunakan di environment live tanpa
   mengirim credential atau data sensitif ke test.
