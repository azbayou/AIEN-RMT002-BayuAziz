# WBS-06 — Implementasi `src/providers.py`

- **Target:** `OpenAIProvider` dan `DeterministicProvider`.
- **Owner:** Agent AI; kredensial/model diputuskan pemilik repo.
- **Dependency:** WBS-02, WBS-03.
- **Status:** DONE

## Pekerjaan

1. Implementasi OpenAI Responses API adapter dengan parameter wajib `store=False`.
2. Kirim `safety_identifier` yang telah di-hash (SHA-256) untuk melindungi identitas pegawai dari provider.
3. Terapkan batch embeddings, timeout, dan bounded transient retry (`max_retries=2`) hanya pada error koneksi/rate-limit.
4. Buat provider tiruan `DeterministicProvider` yang bebas jaringan untuk pengujian policy, balance, dan turn agent.
5. Petakan output fungsi/tool call dan token usage ke kontrak `ModelTurn`.

## Acceptance criteria

- Unit test tidak membutuhkan koneksi jaringan ataupun live API key.
- Provider failure menghasilkan exception yang dapat ditangani oleh agent tanpa efek samping.
- Parameter `store=False` dan `safety_identifier` ter-hash terverifikasi dipanggil pada payload OpenAI.
- Bounded retry hanya mengeksekusi pengulangan pada transient error (misal `APITimeoutError`) dan melempar exception akhir bila melebihi batas.
- `DeterministicProvider` menghasilkan vektor embedding deterministik dan respons mock yang konsisten.

## Hasil pelaksanaan dan refleksi

- `OpenAIProvider`:
  - Menggunakan client Responses API dengan `store=False` untuk mencegah retensi data di sisi server OpenAI.
  - Memastikan `safety_identifier` disamarkan melalui `token_hash`.
  - Melakukan transient retry (maksimal 2 kali pengulangan) pada `APIConnectionError`, `APITimeoutError`,
    `InternalServerError`, dan `RateLimitError` sebelum meneruskan exception ke agent.
  - Parsing output asisten mengenali `function_call` dan memetakan argumen JSON ke list of `ModelToolCall`.
  - Batch embeddings memproses list teks dan menangani list kosong tanpa melakukan panggilan network sia-sia.
- `DeterministicProvider`:
  - Menghasilkan vektor berbasis digest SHA-256 teks tanpa API eksternal.
  - Menyediakan respons percakapan simulasi untuk saldo cuti (`get_my_leave_balance`) dan pencarian kebijakan (`search_hr_policy`).
- Terverifikasi pada unit tests `tests/self_test_cache_providers.py` (5 tests) dan `tests/test_agent_reliability.py`.

## Checkpoint 2026-11-07 — FINAL

- Status: **DONE**
- Bukti:
  - `tests/self_test_cache_providers.py`: 5 provider tests passed (`test_deterministic_provider_embeddings`, `test_deterministic_provider_responses`, `test_openai_provider_calls_responses_api_with_store_false_and_hashed_safety`, `test_openai_provider_transient_retry_and_rethrow`, `test_openai_provider_batch_embed`)
  - `tests/test_agent_reliability.py`: test failure provider & deterministic passed
  - Non-live regression suite: 63 passed, 0 failed
- Hard gates terkait (PII Redaction, Identity Anonymization, Side-effect Free Failure): TERPENUHI.
