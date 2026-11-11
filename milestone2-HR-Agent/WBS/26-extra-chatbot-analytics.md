# WBS-26-extra — Capability Analytics pada Chatbot Khusus Manager & Admin

- **Target:** `src/contracts.py`, `src/repository.py`, `src/tools.py`, `src/agent.py`, `src/providers.py`, `src/api.py`, `app2.py`, `tests/self_test_tools_agent.py`.
- **Owner:** Agent AI.
- **Dependency:** WBS-25-extra.
- **Status:** DONE

## Batasan Scope & Guardrail Penilaian (Wajib Dipatuhi Agent)

- **Boleh diedit:** `src/contracts.py`, `src/repository.py`, `src/tools.py`, `src/agent.py`, `src/providers.py`, `src/api.py`, `app2.py`, `tests/self_test_tools_agent.py`.
- **DILARANG KERAS diedit:** `tests/test_tools.py`, `tests/test_agent_reliability.py`, `app.py`.
- **PERINGATAN KRITIS (`tests/test_tools.py`):**
  Di `tests/test_tools.py` baris 26 terdapat asersi ketat:
  `assert {schema["name"] for schema in TOOL_SCHEMAS} == {"search_hr_policy", "get_my_leave_balance", "prepare_leave_request", "create_hr_ticket"}`
  dan di `tests/self_test_tools_agent.py` baris 53 terdapat:
  `assert len(TOOL_SCHEMAS) == 4`
  Oleh karena itu, **JANGAN menambahkan item ke dalam list `TOOL_SCHEMAS`!**
  Buat konstanta terpisah `MANAGER_ANALYTICS_TOOL_SCHEMA` dan fungsi helper `get_tools_for_role(role: str)` yang menggabungkan `TOOL_SCHEMAS + [MANAGER_ANALYTICS_TOOL_SCHEMA]` **HANYA** jika `role in ("manager", "monitoring_admin")`.

---

## Pekerjaan

### Task 1: Tambahkan Kontrak Argumen Tool Analytics di `src/contracts.py`

Tambahkan `AnalyticsQueryArgs` di `src/contracts.py` (di dekat `TicketArgs`):

```python
class AnalyticsQueryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_focus: Literal["overview", "leave_trends", "balance_risks", "ai_operations"] = "overview"
```

### Task 2: Buat Query Agregasi Analytics yang Aman & Terisolasi Role di `src/repository.py`

1. Tambahkan signature ke `class Repository(Protocol)`:
   ```python
   def get_hr_analytics(self, auth: AuthContext, metric_focus: str = "overview") -> dict[str, Any]: ...
   ```

2. Implementasikan `MemoryRepository.get_hr_analytics(self, auth: AuthContext, metric_focus: str = "overview") -> dict[str, Any]`:
   - Tolak jika `auth.role not in ("manager", "monitoring_admin")` dengan `raise PermissionError("analytics requires manager or admin role")`.
   - Tentukan daftar `scoped_emp_ids`:
     - Jika `auth.role == "monitoring_admin"`: seluruh pegawai (`role != "monitoring_admin"`).
     - Jika `auth.role == "manager"`: hanya pegawai yang memiliki `context.manager_id == auth.employee_id`.
   - Hitung metrik bisnis berikut tanpa menyertakan PII atau alasan medis mentah:
     - `scope`: `"organization"` jika admin, `"team"` jika manager.
     - `team_size`: `len(scoped_emp_ids)`
     - `requests_by_status`: dict jumlah request (`pending_manager_review`, `approved`, `rejected`, `cancelled`) milik `scoped_emp_ids`.
     - `days_by_leave_type`: dict total `business_days` (`annual`, `sick`, `parental`) dari request yang `pending_manager_review` atau `approved`.
     - `low_balance_employees`: list dict `[{"employee_id": emp_id, "display_name": ctx.display_name, "annual_remaining": bal}]` untuk anggota tim yang sisa saldo cuti tahunannya `<= 3` hari.
     - `department_breakdown`: dict jumlah pegawai dan total hari cuti aktif per `department`.
     - Jika `auth.role == "monitoring_admin"`: sertakan juga `"ai_operations": self.monitoring_summary()` dan `"tickets_by_category"` (jumlah tiket per kategori).

3. Implementasikan `PostgresRepository.get_hr_analytics(self, auth: AuthContext, metric_focus: str = "overview") -> dict[str, Any]`:
   - Tolak jika `auth.role not in ("manager", "monitoring_admin")` dengan `raise PermissionError("analytics requires manager or admin role")`.
   - Jalankan query agregasi SQL terparameterisasi dengan filter `WHERE e.manager_id = %s` (untuk `manager`) atau seluruh pegawai (untuk `monitoring_admin`) yang mengembalikan struktur dictionary dengan key yang sama persis (`scope`, `team_size`, `requests_by_status`, `days_by_leave_type`, `low_balance_employees`, `department_breakdown`, dan `ai_operations` khusus admin).

### Task 3: Tambahkan `MANAGER_ANALYTICS_TOOL_SCHEMA` dan `get_tools_for_role` di `src/tools.py`

1. Impor `AnalyticsQueryArgs` dari `.contracts` di `src/tools.py`.
2. **Biarkan `TOOL_SCHEMAS` tetap berisi 4 tool asli.** Di bawah `TOOL_SCHEMAS`, tambahkan:

```python
MANAGER_ANALYTICS_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "name": "get_team_hr_analytics",
    "description": "Ambil ringkasan analitik SDM, tren cuti tim, risiko saldo rendah, dan metrik operasional (khusus Manager dan Admin).",
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {
            "metric_focus": {
                "type": "string",
                "enum": ["overview", "leave_trends", "balance_risks", "ai_operations"],
            },
        },
        "required": ["metric_focus"],
        "additionalProperties": False,
    },
}


def get_tools_for_role(role: str) -> list[dict[str, Any]]:
    if role in ("manager", "monitoring_admin"):
        return [*TOOL_SCHEMAS, MANAGER_ANALYTICS_TOOL_SCHEMA]
    return list(TOOL_SCHEMAS)
```

3. Di dalam `ToolExecutor.execute(self, name: str, arguments: dict[str, Any], auth: AuthContext)`, tambahkan cabang sebelum `raise ValueError(f"unknown tool: {name}")`:

```python
        if name == "get_team_hr_analytics":
            if auth.role not in ("manager", "monitoring_admin"):
                from .domain import DomainError
                raise DomainError("akses analitik hanya diizinkan untuk Manager atau HR Admin")
            args = AnalyticsQueryArgs.model_validate(arguments)
            return self.repository.get_hr_analytics(auth, args.metric_focus), None
```

### Task 4: Hubungkan `get_tools_for_role` ke `src/agent.py` dan `src/providers.py`

1. Di `src/agent.py`:
   - Impor `get_tools_for_role` dari `.tools`:
     ```python
     from .tools import TOOL_SCHEMAS, ToolExecutor, get_tools_for_role
     ```
   - Pada `SYSTEM_INSTRUCTIONS`, tambahkan 1 kalimat panduan:
     `Untuk pengguna dengan role manager atau monitoring_admin yang menanyakan analitik tim, tren cuti, statistik departemen, atau performa operasional, panggil tool get_team_hr_analytics.`
   - Pada pemanggilan `self.provider.respond(...)` di `AgentService.run` (sekitar baris 49), ganti `tools=TOOL_SCHEMAS` menjadi:
     ```python
     tools=get_tools_for_role(auth.role),
     ```
   - Pada pengecekan `has_tool_evidence` di `AgentService.run` (sekitar baris 61), tambahkan `"get_team_hr_analytics"`:
     ```python
     has_tool_evidence = any(
         t.name in ("get_my_leave_balance", "create_hr_ticket", "get_team_hr_analytics") and t.status == "ok"
         for t in tool_summaries
     )
     ```
2. Di `DeterministicProvider.respond` (`src/providers.py` sekitar baris 115):
   - Tambahkan dukungan deterministik untuk kata kunci `"analitik"` atau `"statistik"` jika `get_team_hr_analytics` tersedia di `kwargs.get("tools", [])`:
     ```python
        available_tool_names = {t.get("name") for t in (kwargs.get("tools") or []) if isinstance(t, dict)}
        if any(term in lowered for term in ("analitik", "analytics", "statistik", "tren")) and "get_team_hr_analytics" in available_tool_names:
            tool_calls = [{
                "call_id": f"call-{self._response_number}",
                "name": "get_team_hr_analytics",
                "arguments": {"metric_focus": "overview"},
            }]
     ```

### Task 5: Tambahkan Endpoint `GET /api/v1/analytics/overview` di `src/api.py` & Visualisasi di `app2.py`

1. Di `src/api.py`, tambahkan endpoint untuk dashboard analitik Manager/Admin:
   ```python
    @app.get("/api/v1/analytics/overview")
    def analytics_overview(
        metric_focus: str = "overview",
        auth: AuthContext = Depends(manager_auth),
    ) -> dict[str, Any]:
        return repository.get_hr_analytics(auth, metric_focus)
   ```
2. Di `app2.py`:
   - Ketika `user_role in ("manager", "monitoring_admin")`, tambahkan tombol Quick Prompt khusus di sidebar seperti:
     - `"Bagaimana analitik dan tren cuti tim saya saat ini?"`
     - `"Siapa anggota tim yang sisa saldo cutinya paling rendah?"`
   - Di tab Manager/Monitoring pada `app2.py`, tampilkan ringkasan visual dari `GET /api/v1/analytics/overview` (jumlah anggota tim, distribusi status cuti, dan daftar pegawai dengan sisa saldo rendah).

### Task 6: Tambahkan Unit Test di `tests/self_test_tools_agent.py`

Tambahkan 2 fungsi test di akhir `tests/self_test_tools_agent.py`:
1. `test_analytics_tool_is_role_gated_for_manager_and_admin(repository: MemoryRepository)`:
   - Verifikasi `len(get_tools_for_role("employee")) == 4` dan `len(get_tools_for_role("manager")) == 5`.
   - Pegawai biasa (`role="employee"`) memanggil `tools.execute("get_team_hr_analytics", {"metric_focus": "overview"}, auth_emp)` → wajib melempar `DomainError`.
   - Manager (`employee_id="MGR-001", role="manager"`) memanggil `tools.execute("get_team_hr_analytics", {"metric_focus": "overview"}, auth_mgr)` → berhasil mengembalikan dict analitik berisi `team_size`, `requests_by_status`, dan `low_balance_employees` (termasuk `EMP-002` yang saldonya 3).
2. `test_agent_answers_analytics_query_for_manager(repository: MemoryRepository)`:
   - Jalankan `agent.run(ChatRequest(message="Tampilkan analitik dan statistik cuti tim"), AuthContext(employee_id="MGR-001", display_name="Raka", role="manager"))` dengan `DeterministicProvider`.
   - Verifikasi `response.outcome == Outcome.answered` dan `any(tc.name == "get_team_hr_analytics" and tc.status == "ok" for tc in response.tool_calls)`.

---

## Langkah Verifikasi

```bash
pytest tests/test_tools.py tests/self_test_tools_agent.py -v
pytest -m "not live"
```

## Acceptance Criteria

- [x] `tests/test_tools.py` tetap lulus 100% (`TOOL_SCHEMAS` tetap berisi 4 tool standar).
- [x] `get_team_hr_analytics` hanya diberikan ke model jika `auth.role in ("manager", "monitoring_admin")`.
- [x] Pegawai biasa (`employee`) diblokir (`DomainError` / status `"blocked"`) jika mencoba memanggil tool analitik.
- [x] Manager hanya menerima data agregat bawahan di timnya sendiri, sedangkan Monitoring Admin menerima agregat lintas departemen + operasional AI.
- [x] Seluruh test non-live lulus 100%.

## Bukti Eksekusi & Hasil Pengujian

1. `pytest tests/test_tools.py tests/self_test_tools_agent.py -v`: 17 passed (100%).
2. `pytest -m "not live"`: 38 passed, 2 skipped (Postgres integration), 1 deselected (100%).
3. `pytest tests/self_test*.py -v`: 59 passed, 1 skipped (Postgres integration) (100%).
