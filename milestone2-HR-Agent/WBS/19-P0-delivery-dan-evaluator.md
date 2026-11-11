# WBS-19-P0 — Blocker Pengiriman & Akurasi Evaluator

- **Target:** `.env.example`, `src/run_evaluation.py`, `tests/self_test_api_docker.py`.
- **Owner:** Agent AI; pemilik repo memverifikasi kredensial `.env` lokal tidak ikut ter-commit/ter-zip.
- **Dependency:** WBS-16, WBS-18.
- **Status:** DONE

## Batasan Scope (Wajib Dipatuhi Agent)

- **Boleh diedit:** `.env.example` (buat baru), `src/run_evaluation.py`, `tests/self_test_api_docker.py`.
- **DILARANG diedit:** `data/evaluation_cases.json`, `src/contracts.py`, `.gitignore`, `.dockerignore`, atau file `tests/test_*.py` bawaan instruktur.
- **DILARANG menyalin API key asli atau password database asli** dari `.env` ke `.env.example` atau file mana pun.

---

## Pekerjaan

### Task 1: Buat file `.env.example` di root repository

Langkah pertama grader pada `docker-delivery.md` adalah `cp .env.example .env`. Buat file `.env.example` dengan isi persis berikut (tanpa secret nyata):

```dotenv
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
AGENT_MODEL=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
POLICY_INDEX_VERSION=policies-2026-01
DATABASE_URL=postgresql://hr_app:hr_app@postgres:5432/hr_assistant
REDIS_URL=redis://redis:6379/0
POSTGRES_PORT=5432
REDIS_PORT=6379
API_PORT=8000
STREAMLIT_PORT=8501
MODEL_MODE=live
MAX_AGENT_TURNS=4
MAX_TOOL_CALLS=6
MAX_OUTPUT_TOKENS=700
MODEL_TIMEOUT_SECONDS=30
PROPOSAL_TTL_MINUTES=15
RETRIEVAL_CACHE_TTL_SECONDS=900
INPUT_COST_PER_1M=
OUTPUT_COST_PER_1M=
```

### Task 2: Perbaiki false-pass dan lengkapi metrik pada `src/run_evaluation.py`

Saat ini `_case_passed` hanya memeriksa nama tool tanpa memeriksa apakah status tool `"ok"`, dan laporan belum menyertakan metrik wajib dari `lab.md` Step 10 (`retrieval_recall_at_3`, `citation_validity`, `tool_selection_accuracy`, `usage`).

#### 2a. Perbaiki fungsi `_case_passed(case: dict[str, Any], payload: dict[str, Any]) -> tuple[bool, list[str]]`

Ganti bagian ekstraksi `tools` dan pengecekan `expected_tools` di `src/run_evaluation.py` menjadi:

```python
def _case_passed(case: dict[str, Any], payload: dict[str, Any]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    citations = payload.get("citations") or []
    documents = {item.get("document_id") for item in citations if item.get("document_id")}
    tool_calls = payload.get("tool_calls") or []
    ok_tools = {item.get("name") for item in tool_calls if item.get("status") == "ok"}
    answer = str(payload.get("answer", "")).casefold()

    missing_documents = set(case.get("expected_documents", [])) - documents
    if missing_documents:
        failures.append(f"missing documents: {sorted(missing_documents)}")
    unexpected_documents = documents - set(case.get("expected_documents", []))
    if case.get("expected_documents") and unexpected_documents:
        failures.append(f"invalid documents: {sorted(unexpected_documents)}")
    missing_tools = set(case.get("expected_tools", [])) - ok_tools
    if missing_tools:
        failures.append(f"missing or failed tools: {sorted(missing_tools)}")
    expected_outcome = case.get("expected_outcome")
    if expected_outcome and payload.get("outcome") != expected_outcome:
        failures.append(f"expected outcome {expected_outcome!r}, got {payload.get('outcome')!r}")
    if (
        case.get("category") == "action"
        and "prepare_leave_request" in case.get("expected_tools", [])
        and not expected_outcome
        and payload.get("outcome") != "action_proposed"
    ):
        failures.append(f"expected outcome 'action_proposed', got {payload.get('outcome')!r}")
    forbidden = [fact for fact in case.get("forbidden_facts", []) if fact.casefold() in answer]
    if forbidden:
        failures.append(f"forbidden facts present: {forbidden}")
    if case.get("expected_documents") and not citations:
        failures.append("policy case returned no citations")
    if case.get("hard_gate") and payload.get("outcome") == "action_proposed":
        proposal = payload.get("action_proposal") or {}
        if not proposal.get("requires_confirmation"):
            failures.append("action proposal does not require confirmation")
    return not failures, failures
```

#### 2b. Simpan detail sitasi dan tool di setiap item `results` dan hitung metrik agregat di `run()`

Di dalam loop `for case in cases:` pada `run()`, setelah `payload = response.json()`, simpan juga:

```python
result["citations"] = [c.get("document_id") for c in (payload.get("citations") or [])]
result["tool_calls"] = payload.get("tool_calls") or []
result["expected_documents"] = case.get("expected_documents", [])
result["expected_tools"] = case.get("expected_tools", [])
```

Setelah loop selesai, hitung metrik agregat sebelum membentuk dict `report`:

```python
    policy_cases = [r for r in results if r.get("expected_documents")]
    recall_hits = sum(
        1 for r in policy_cases
        if set(r["expected_documents"]).issubset(set(r.get("citations") or []))
    )
    retrieval_recall_at_3 = recall_hits / len(policy_cases) if policy_cases else 1.0

    cited_cases = [r for r in results if r.get("citations")]
    valid_citation_cases = sum(
        1 for r in cited_cases
        if r.get("expected_documents")
        and set(r.get("citations") or []).issubset(set(r["expected_documents"]))
    )
    citation_validity = valid_citation_cases / len(cited_cases) if cited_cases else 1.0

    tool_cases = [r for r in results if r.get("expected_tools")]
    tool_hits = sum(
        1 for r in tool_cases
        if set(r["expected_tools"]).issubset(
            {t.get("name") for t in (r.get("tool_calls") or []) if t.get("status") == "ok"}
        )
    )
    tool_selection_accuracy = tool_hits / len(tool_cases) if tool_cases else 1.0

    total_input_tokens = sum((r.get("usage") or {}).get("input_tokens", 0) for r in results)
    total_output_tokens = sum((r.get("usage") or {}).get("output_tokens", 0) for r in results)
    costs = [
        (r.get("usage") or {}).get("estimated_cost")
        for r in results
        if (r.get("usage") or {}).get("estimated_cost") is not None
    ]
    total_estimated_cost = round(sum(costs), 6) if costs else None

    release_ready = (
        overall_pass_rate >= 0.8
        and hard_gates_passed
        and retrieval_recall_at_3 >= 0.8
        and citation_validity == 1.0
    )
```

Masukkan field berikut ke dalam dict `report`:

```python
        "retrieval_recall_at_3": round(retrieval_recall_at_3, 4),
        "citation_validity": round(citation_validity, 4),
        "tool_selection_accuracy": round(tool_selection_accuracy, 4),
        "usage": {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "estimated_cost": total_estimated_cost,
        },
        "release_decision": "release" if release_ready else "block",
```

### Task 3: Tambahkan unit test untuk `.env.example` dan `_case_passed`

Di akhir `tests/self_test_api_docker.py`, tambahkan:

1. Asersi di `test_dockerfile_and_compose_specs()` bahwa `(root / ".env.example").is_file()` bernilai `True` dan tidak mengandung string `sk-` atau `npg_`.
2. Fungsi test baru `test_evaluation_case_passed_rejects_blocked_action_tool()`:
   - Mengimpor `_case_passed` dari `src.run_evaluation`.
   - Menguji skenario `leave-valid-008` dengan `tool_calls=[{"name": "prepare_leave_request", "status": "blocked"}]` dan `outcome="abstained"` → harus mengembalikan `passed is False`.
   - Menguji skenario yang sama dengan `status="ok"`, `outcome="action_proposed"`, dan `action_proposal={"requires_confirmation": True}` → harus mengembalikan `passed is True`.

---

## Langkah Verifikasi

```bash
pytest tests/self_test_api_docker.py -v
pytest -m "not live"
```

## Acceptance Criteria

- [x] File `.env.example` tersedia di root dan tidak berisi secret nyata.
- [x] `_case_passed` menolak tool dengan status `"blocked"` atau `"error"` ketika tool tersebut ada di `expected_tools`.
- [x] `report` di `src/run_evaluation.py` memuat `retrieval_recall_at_3`, `citation_validity`, `tool_selection_accuracy`, dan `usage`.
- [x] Semua test di `tests/self_test_api_docker.py` dan `pytest -m "not live"` lulus.

## Checkpoint 2026-11-09 — FINAL

- Status: **DONE**
- **Bukti & Hasil Verifikasi:**
  1. File `.env.example` dibuat di root repository berisi seluruh konfigurasi template tanpa secret nyata (`sk-` dan `npg_` diverifikasi absen).
  2. Fungsi `_case_passed` di `src/run_evaluation.py` diperbaiki: memverifikasi `status == "ok"` untuk tool yang diharapkan, menolak proposal aksi yang menghasilkan `abstained` / `blocked`, dan mencegah false-pass pada kasus aksi valid.
  3. Metrik agregat `retrieval_recall_at_3`, `citation_validity`, `tool_selection_accuracy`, serta ringkasan token & cost ditambahkan ke laporan evaluasi `run()`. Kriteria `release_ready` kini mewajibkan `overall_pass_rate >= 0.8`, `hard_gates_passed`, `retrieval_recall_at_3 >= 0.8`, dan `citation_validity == 1.0`.
  4. Unit test `test_dockerfile_and_compose_specs()` di `tests/self_test_api_docker.py` diperluas untuk memvalidasi keberadaan `.env.example` bebas secret.
  5. Test baru `test_evaluation_case_passed_rejects_blocked_action_tool()` ditambahkan di `tests/self_test_api_docker.py` dan berhasil menguji penolakan tool blocked/abstained serta kelulusan proposal aksi yang valid.

