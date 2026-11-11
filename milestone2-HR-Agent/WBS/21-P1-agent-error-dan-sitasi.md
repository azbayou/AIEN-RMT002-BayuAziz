# WBS-21-P1 — Penanganan DomainError, Gate Sitasi, Deduplikasi Tiket, dan Akurasi Telemetry

- **Target:** `src/agent.py`, `src/repository.py`, `tests/self_test_tools_agent.py`.
- **Owner:** Agent AI.
- **Dependency:** WBS-20-P1.
- **Status:** DONE

## Batasan Scope (Wajib Dipatuhi Agent)

- **Boleh diedit:** `src/agent.py`, `src/repository.py`, `tests/self_test_tools_agent.py`.
- **DILARANG diedit:** `src/contracts.py`, `src/domain.py`, `tests/test_agent_reliability.py`, `tests/test_tools.py`.
- Semua test di `tests/test_agent_reliability.py` wajib tetap lulus tanpa modifikasi.

---

## Pekerjaan

### Task 1: Pisahkan `DomainError` (Blocked Action) dari System Error di `src/agent.py`

Saat ini, ketika `prepare_leave_request` ditolak oleh aturan bisnis (`DomainError`, misalnya tanggal masa lalu, saldo kurang, atau kurang dari 3 hari kerja), `src/agent.py` menangkapnya sebagai exception umum:
1. User hanya mendapat pesan generik `"Maaf, layanan sedang tidak dapat memberikan jawaban yang aman."` tanpa tahu alasan penolakannya.
2. Field `trace["error"]` terisi, sehingga menaikkan `error_rate` di `/api/v1/monitoring/summary` dan memicu false alarm `agent-error-spike`.

#### Perubahan di `src/agent.py`:

1. Impor `DomainError` di bagian atas `src/agent.py`:
   ```python
   from .domain import DomainError
   ```
2. Ubah inisialisasi `input_tokens` di `AgentService.run` (baris 39) dari `len(request.message.split())` menjadi `0`, lalu setelah loop selesai, jika `input_tokens == 0`, isi fallback `input_tokens = len(request.message.split())`. Ini mencegah pencampuran jumlah kata dengan jumlah token asli dari provider.
3. Tambahkan variabel `blocked_reason: str | None = None` sebelum `try:` di `AgentService.run`.
4. Di dalam blok `except Exception as tool_error:` (baris 122–131), tangani `DomainError` secara khusus:
   ```python
                    except DomainError as domain_error:
                        blocked_reason = redact(str(domain_error))
                        tool_summaries.append(
                            ToolCallSummary(
                                name=call.name,
                                status="blocked",
                                duration_ms=max(0, int((time.monotonic() - call_started) * 1000)),
                            )
                        )
                        answer = f"Maaf, permintaan tidak dapat diproses: {blocked_reason}."
                        outcome = Outcome.abstained
                        break
                    except Exception as tool_error:
                        tool_summaries.append(
                            ToolCallSummary(
                                name=call.name,
                                status="error",
                                duration_ms=max(0, int((time.monotonic() - call_started) * 1000)),
                            )
                        )
                        raise
   ```
5. Karena `break` di atas hanya keluar dari loop `for call in turn.tool_calls:`, tambahkan tepat setelah loop `for call in turn.tool_calls:` (sebelum akhir iterasi `for _ in range(self.settings.max_agent_turns):`):
   ```python
                if blocked_reason is not None:
                    break
   ```
   Dengan begitu:
   - `outcome` tetap `Outcome.abstained` (sesuai kontrak evaluation case `leave-past-009`),
   - `answer` menjelaskan alasan bisnis secara aman dan jelas kepada pegawai,
   - `error_message` tetap `None` (tidak mencemari `error_rate` sistem), sedangkan `blocked_reason` tercatat di trace.

### Task 2: Perketat Gate Sitasi dan Outcome `escalated` di `src/agent.py`

Saat ini:
- Jika `search_hr_policy` dipanggil tetapi pertanyaan user tidak mengandung kata kunci di `_requires_evidence`, model dapat menjawab tanpa sitasi.
- Jika jawaban mengandung tanda kurung siku `[HR-FAKE-999]` bersamaan dengan tool `get_my_leave_balance`, `has_tool_evidence` meloloskan jawaban tersebut.
- Jika `create_hr_ticket` berhasil dipanggil, outcome dapat diset ke `Outcome.escalated` (atau tetap diterima oleh kontrak). Namun perhatikan: cek apakah ada test atau evaluation case yang mengharapkan outcome tertentu. Pada `data/evaluation_cases.json`, tidak ada case yang memanggil `create_hr_ticket` dengan `expected_outcome` selain default. Agar aman terhadap seluruh test yang sudah ada, pertahankan `outcome` tetapi perketat validasi sitasi.

#### Perubahan pada blok `if not turn.tool_calls:` di `src/agent.py` (sekitar baris 58–70):

Ganti blok tersebut menjadi:

```python
                if not turn.tool_calls:
                    answer = turn.text.strip() or answer
                    raw_brackets = set(re.findall(r"\[([A-Z0-9-]+)\]", answer))
                    citations = self._citations_from_text(answer, retrieved)
                    policy_searched = any(
                        t.name == "search_hr_policy" and t.status == "ok"
                        for t in tool_summaries
                    )
                    has_tool_evidence = any(
                        t.name in ("get_my_leave_balance", "create_hr_ticket") and t.status == "ok"
                        for t in tool_summaries
                    )
                    # Jika model menulis sitasi [ID] tetapi ada yang tidak valid -> wajib abstain
                    has_invalid_citation = bool(raw_brackets) and not citations
                    needs_policy_citation = (
                        (policy_searched or self._requires_evidence(request.message))
                        and not has_tool_evidence
                        and not proposal
                    )
                    if has_invalid_citation or (needs_policy_citation and not citations):
                        answer = "Maaf, bukti kebijakan yang valid belum tersedia."
                        citations = []
                        outcome = Outcome.abstained
                    else:
                        outcome = Outcome.action_proposed if proposal else Outcome.answered
                    break
```

### Task 3: Lengkapi Payload Trace dengan `retrieved_document_ids`, `citation_ids`, dan `blocked_reason`

`lab.md` Step 9 mewajibkan trace mencatat `retrieved document IDs`. Di `src/agent.py` pada pemanggilan `self.repository.save_trace({...})` (sekitar baris 145), tambahkan field berikut:

```python
        retrieved_doc_ids = list(
            dict.fromkeys(
                chunk.document_id for chunk in retrieved if hasattr(chunk, "document_id")
            )
        )
        self.repository.save_trace(
            {
                "trace_id": trace_id,
                "employee_id": auth.employee_id,
                "outcome": outcome.value,
                "error": error_message,
                "blocked_reason": blocked_reason,
                "retrieved_document_ids": retrieved_doc_ids,
                "citation_ids": [c.document_id for c in citations] if outcome == Outcome.answered else [],
                "tool_calls": [summary.model_dump() for summary in tool_summaries],
                "usage": usage.model_dump(),
            }
        )
```

### Task 4: Deduplikasi `create_ticket` di `src/repository.py`

Agar model tidak membuat tiket duplikat berulang kali untuk pegawai, kategori, dan ringkasan yang sama:

1. Pada `MemoryRepository.create_ticket(self, employee_id: str, category: str, summary: str) -> str`:
   ```python
    def create_ticket(self, employee_id: str, category: str, summary: str) -> str:
        clean_summary = redact(summary)
        with self._lock:
            for existing_id, item in self.tickets.items():
                if (
                    item.get("employee_id") == employee_id
                    and item.get("category") == category
                    and item.get("summary") == clean_summary
                ):
                    return existing_id
            ticket_id = f"T-{uuid4().hex[:12]}"
            self.tickets[ticket_id] = {
                "employee_id": employee_id,
                "category": category,
                "summary": clean_summary,
            }
            return ticket_id
   ```
2. Pada `PostgresRepository.create_ticket(self, employee_id: str, category: str, summary: str) -> str`:
   ```python
    def create_ticket(self, employee_id: str, category: str, summary: str) -> str:
        clean_summary = redact(summary)
        with self.pool.connection() as connection:
            existing = connection.execute(
                """
                SELECT ticket_id FROM tickets
                WHERE employee_id = %s AND category = %s AND summary = %s
                ORDER BY created_at DESC LIMIT 1
                """,
                (employee_id, category, clean_summary),
            ).fetchone()
            if existing:
                return str(existing["ticket_id"])
            ticket_id = f"T-{uuid4().hex[:12]}"
            connection.execute(
                """
                INSERT INTO tickets (ticket_id, employee_id, category, summary)
                VALUES (%s, %s, %s, %s)
                """,
                (ticket_id, employee_id, category, clean_summary),
            )
        return ticket_id
   ```

### Task 5: Tambahkan unit test di `tests/self_test_tools_agent.py`

Tambahkan 3 test baru di akhir `tests/self_test_tools_agent.py`:
1. `test_domain_error_sets_blocked_status_without_polluting_error_rate(repository: MemoryRepository)`:
   - Buat provider yang memanggil `prepare_leave_request` dengan tanggal masa lalu (`2025-01-02` s/d `2025-01-03`).
   - Jalankan `agent.run(...)`.
   - Verifikasi `response.outcome == Outcome.abstained`, `"masa lalu"` ada di `response.answer`, `response.tool_calls[0].status == "blocked"`, `trace["error"] is None`, dan `repository.monitoring_summary()["error_count"] == 0`.
2. `test_trace_records_retrieved_document_ids_and_citations(repository: MemoryRepository)`:
   - Gunakan `MultiTurnSuccessProvider` seperti pada `test_agent_multi_turn_with_valid_citation`.
   - Verifikasi `trace["retrieved_document_ids"] == ["HR-LEAVE-001"]` dan `trace["citation_ids"] == ["HR-LEAVE-001"]`.
3. `test_create_ticket_is_idempotent_for_identical_summary(repository: MemoryRepository)`:
   - Panggil `repository.create_ticket("EMP-001", "privacy", "Pertanyaan sama")` dua kali → mengembalikan `ticket_id` yang sama.

---

## Langkah Verifikasi

```bash
pytest tests/test_agent_reliability.py tests/self_test_tools_agent.py -v
pytest -m "not live"
```

## Acceptance Criteria

- [x] `DomainError` menghasilkan tool status `"blocked"`, jawaban informatif berisi alasan penolakan, dan `trace["error"]` bernilai `None` sehingga `error_rate` monitoring tidak naik karena input user yang tidak valid.
- [x] Trace menyimpan `retrieved_document_ids` dan `citation_ids`.
- [x] `input_tokens` tidak lagi mencampur hitungan kata dengan token dari provider.
- [x] Pembuatan tiket dengan `(employee_id, category, summary)` identik tidak menduplikasi tiket.
- [x] Seluruh test di `tests/test_agent_reliability.py` dan `tests/self_test_tools_agent.py` lulus.

---

## Checkpoint & Catatan Implementasi

- **DomainError Handling (`src/agent.py`):**
  - Diimpor `DomainError` dari `.domain`.
  - Pada eksekusi tool, exception `DomainError` ditangkap terpisah sebelum exception umum.
  - Dicatat sebagai `ToolCallSummary(status="blocked")` dengan durasi eksekusi.
  - Menghasilkan respon user `Maaf, permintaan tidak dapat diproses: {blocked_reason}.` dan `outcome = Outcome.abstained`.
  - `error_message` tetap `None` sehingga tidak menaikkan `error_rate` pada `/api/v1/monitoring/summary`.
- **Akurasi Token (`src/agent.py`):**
  - Inisialisasi `input_tokens = 0` dan hanya menjumlahkan token provider yang sebenarnya. Jika turn berakhir dengan 0 token (mock tanpa token), digunakan fallback hitungan kata pesan pengguna.
- **Gate Sitasi & Abstain (`src/agent.py`):**
  - Sitasi dengan bracket palsu atau tidak lengkap langsung memaksa `Outcome.abstained` dan menghapus sitasi (`citations = []`).
  - Pencarian kebijakan yang tidak membuahkan sitasi sah otomatis dialihkan ke pesan `"Maaf, bukti kebijakan yang valid belum tersedia."` dan `Outcome.abstained`.
- **Telemetry Payload (`src/agent.py`):**
  - Trace menyimpan `retrieved_document_ids` dan `citation_ids` (jika outcome `answered`).
  - Field `blocked_reason` disimpan untuk memudahkan audit alasan penolakan bisnis.
- **Deduplikasi Tiket (`src/repository.py`):**
  - `MemoryRepository.create_ticket` dan `PostgresRepository.create_ticket` mengembalikan `ticket_id` yang sudah ada jika terdapat kombinasi `(employee_id, category, redacted_summary)` yang identik.
- **Unit & Integration Tests:**
  - Ditambahkan 3 unit test di `tests/self_test_tools_agent.py` (`test_domain_error_sets_blocked_status_without_polluting_error_rate`, `test_trace_records_retrieved_document_ids_and_citations`, `test_create_ticket_is_idempotent_for_identical_summary`).
  - Seluruh test di `tests/test_agent_reliability.py`, `tests/test_tools.py`, dan `tests/self_test_tools_agent.py` terverifikasi lulus 100%.
