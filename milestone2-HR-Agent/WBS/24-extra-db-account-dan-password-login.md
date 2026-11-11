# WBS-24-extra — Rombak Database Account & Sub-App Session Selector (Step-Up Password Auth)

- **Target:** `data/employees.json`, `src/security.py`, `src/contracts.py`, `src/setup_lab.py`, `src/repository.py`, `src/api.py`, `app2.py`, `tests/self_test_contracts_config.py`.
- **Owner:** Agent AI.
- **Dependency:** WBS-23-P3.
- **Status:** DONE

## Konsep Arsitektur: Sub-App Session & Step-Up Authentication

Aplikasi HR Agent ini diposisikan sebagai **Sub-Application (Modul Internal HR)** di dalam ekosistem portal utama perusahaan, di mana pengguna diasumsikan **sudah login pada aplikasi utama (Single Sign-On / Active Intranet Session)**:
1. **Halaman Pilih Pengguna (User Directory List):** Halaman awal tidak lagi menampilkan form login utama yang meminta username dan password dari nol, melainkan menampilkan **Daftar Akun Pengguna (User List)** yang sedang terdaftar di sistem.
2. **Akses Langsung Tanpa Password untuk Pegawai Reguler (`role: employee`):** Akun pegawai biasa (`EMP-001` Alya Pratama, `EMP-002` Bima Santoso) dapat langsung dipilih (*1-Click Switch / Direct Enter*) tanpa memerlukan input password tambahan.
3. **Re-Authentication Wajib (Step-Up Password) untuk Manager & Admin (`role: manager`, `role: monitoring_admin`):** Karena akun Manager (`MGR-001` Rakabuming Raka) dan Admin (`ADM-001` Monitoring Admin) memiliki kewenangan sensitif (persetujuan cuti bawahan, analitik SDM lintas tim, serta audit & monitoring operasional), pemilihan akun Manager atau Admin **wajib melalui verifikasi ulang password (*re-required password*)** melalui endpoint `POST /api/v1/auth/login` sebelum sesi diaktifkan.

## Batasan Scope & Guardrail Penilaian (Wajib Dipatuhi Agent)

- **Boleh diedit:** `data/employees.json`, `src/security.py`, `src/contracts.py`, `src/setup_lab.py`, `src/repository.py`, `src/api.py`, `app2.py`, `tests/self_test_contracts_config.py`.
- **DILARANG KERAS diedit:** `demo_personas.json`, `app.py`, `ui_contract.py`, `requirements.txt`, `tests/test_*.py` (test bawaan instruktur).
  - *Alasan:* `tests/test_supplied_ui.py` memeriksa bahwa `demo_personas.json` hanya memiliki tepat 3 persona (`EMP-001`, `EMP-002`, `ADM-001`). Akun Manager (`MGR-001`) hanya boleh ditambahkan di `data/employees.json`.
- **Jangan mengubah cara kerja `Authorization: Bearer <token>`:** Seluruh endpoint `/api/v1/*` tetap menggunakan Bearer token yang sudah ada (`token-alya`, `token-bima`, `token-admin`, dan tambahan `token-manager`). Endpoint verifikasi password (`POST /api/v1/auth/login`) memverifikasi password untuk Step-Up Auth lalu mengembalikan Bearer token tersebut kepada UI `app2.py`.

---

## Pekerjaan

### Task 1: Perbarui `data/employees.json` dengan Field Akun Lengkap & Role Manager

Ganti isi `data/employees.json` menjadi berikut (mempertahankan seluruh `employee_id`, `token`, dan `balances` lama agar 100% kompatibel dengan test lama, sambil menambahkan `username`, `password`, `department`, `manager_id`, dan akun `MGR-001`):

```json
[
  {
    "employee_id": "EMP-001",
    "username": "alya",
    "password": "Password#123",
    "display_name": "Alya Pratama",
    "role": "employee",
    "department": "Engineering",
    "manager_id": "MGR-001",
    "token": "token-alya",
    "balances": {"annual": 8, "sick": 10, "parental": 60}
  },
  {
    "employee_id": "EMP-002",
    "username": "bima",
    "password": "Password#123",
    "display_name": "Bima Santoso",
    "role": "employee",
    "department": "Engineering",
    "manager_id": "MGR-001",
    "token": "token-bima",
    "balances": {"annual": 3, "sick": 10, "parental": 60}
  },
  {
    "employee_id": "MGR-001",
    "username": "rakabuming",
    "password": "Password#123",
    "display_name": "Rakabuming Raka",
    "role": "manager",
    "department": "Engineering",
    "manager_id": null,
    "token": "token-manager",
    "balances": {"annual": 12, "sick": 10, "parental": 60}
  },
  {
    "employee_id": "ADM-001",
    "username": "admin",
    "password": "Password#123",
    "display_name": "Monitoring Admin",
    "role": "monitoring_admin",
    "department": "HR & People Ops",
    "manager_id": null,
    "token": "token-admin",
    "balances": {}
  }
]
```

### Task 2: Tambahkan Salted Password Hashing (PBKDF2-HMAC-SHA256) di `src/security.py`

Gunakan pustaka standar Python (`hashlib`, `hmac`, `secrets`) tanpa menambah dependency baru di `requirements.txt`.
Tambahkan di bagian akhir `src/security.py`:

```python
import hmac
import secrets


def hash_password(password: str, salt: str | None = None) -> str:
    """Hash password with PBKDF2-HMAC-SHA256 and random/provided salt."""
    active_salt = salt or secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        active_salt.encode("utf-8"),
        100_000,
    ).hex()
    return f"pbkdf2_sha256${active_salt}${derived}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time verification of a password against a stored PBKDF2 hash."""
    if not stored_hash or "$" not in stored_hash:
        return False
    parts = stored_hash.split("$")
    if len(parts) != 3 or parts[0] != "pbkdf2_sha256":
        return False
    _, salt, _ = parts
    candidate = hash_password(password, salt=salt)
    return hmac.compare_digest(candidate, stored_hash)
```

### Task 3: Perbarui Kontrak `AuthContext` dan Tambahkan Skema Login di `src/contracts.py`

1. Di `src/contracts.py`, ubah class `AuthContext` (sekitar baris 17) agar mendukung role `"manager"` dan menyertakan atribut organisasi opsional dengan nilai default (sehingga pemanggilan `AuthContext(employee_id="EMP-001", display_name="Alya")` di test lama tetap valid):

```python
class AuthContext(BaseModel):
    employee_id: str
    display_name: str
    role: Literal["employee", "manager", "monitoring_admin"] = "employee"
    department: str | None = None
    manager_id: str | None = None
```

2. Tambahkan kontrak request/response untuk login di bagian bawah `src/contracts.py`:

```python
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    profile: AuthContext
```

### Task 4: Perbarui DDL Tabel `employees` dan Seeding di `src/setup_lab.py`

1. Impor `hash_password` dari `.security` di bagian atas `src/setup_lab.py`:
   ```python
   from .security import hash_password, token_hash
   ```
2. Pada fungsi `reset_and_seed` di `src/setup_lab.py` (sekitar baris 115), ubah definisi `CREATE TABLE IF NOT EXISTS employees` dan tambahkan `ALTER TABLE` idempotent (agar database yang sudah telanjur dibuat tanpa `--reset` tetap memiliki kolom baru):

```sql
                CREATE TABLE IF NOT EXISTS employees (
                    employee_id TEXT PRIMARY KEY,
                    username TEXT UNIQUE,
                    password_hash TEXT,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('employee', 'manager', 'monitoring_admin')),
                    department TEXT,
                    manager_id TEXT,
                    token_hash TEXT NOT NULL UNIQUE
                );
                ALTER TABLE employees ADD COLUMN IF NOT EXISTS username TEXT UNIQUE;
                ALTER TABLE employees ADD COLUMN IF NOT EXISTS password_hash TEXT;
                ALTER TABLE employees ADD COLUMN IF NOT EXISTS department TEXT;
                ALTER TABLE employees ADD COLUMN IF NOT EXISTS manager_id TEXT;
                ALTER TABLE employees DROP CONSTRAINT IF EXISTS employees_role_check;
                ALTER TABLE employees ADD CONSTRAINT employees_role_check
                    CHECK (role IN ('employee', 'manager', 'monitoring_admin'));
```

3. Di dalam loop `for employee in employees:` pada `src/setup_lab.py` (sekitar baris 168), simpan juga `username`, `password_hash`, `department`, dan `manager_id`:

```python
                username = employee.get("username") or employee["employee_id"].lower()
                raw_password = employee.get("password", "Password#123")
                # Gunakan salt deterministik berbasis employee_id saat seed agar idempotent
                pwd_salt = hashlib.sha256(f"salt:{employee['employee_id']}".encode()).hexdigest()[:16]
                pwd_hash = hash_password(raw_password, salt=pwd_salt)
                cursor.execute(
                    """
                    INSERT INTO employees
                        (employee_id, username, password_hash, display_name, role, department, manager_id, token_hash)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (employee_id) DO UPDATE SET
                        username = EXCLUDED.username,
                        password_hash = EXCLUDED.password_hash,
                        display_name = EXCLUDED.display_name,
                        role = EXCLUDED.role,
                        department = EXCLUDED.department,
                        manager_id = EXCLUDED.manager_id,
                        token_hash = EXCLUDED.token_hash
                    """,
                    (
                        employee["employee_id"],
                        username,
                        pwd_hash,
                        employee["display_name"],
                        employee["role"],
                        employee.get("department"),
                        employee.get("manager_id"),
                        token_hash(employee["token"]),
                    ),
                )
```

### Task 5: Tambahkan `authenticate_password` di `src/repository.py`

1. Impor `LoginResponse` dari `.contracts` dan `hash_password, verify_password` dari `.security` di `src/repository.py`.
2. Tambahkan signature di `class Repository(Protocol)`:
   ```python
   def authenticate_password(self, username: str, password: str) -> LoginResponse | None: ...
   ```
3. Pada `MemoryRepository.__init__`, simpan juga dictionary `self.credentials: dict[str, dict[str, Any]] = {}` saat membaca `_load_employees()`:
   - Di dalam loop `for emp in _load_employees():`, pastikan `AuthContext` menyertakan `department=emp.get("department")` dan `manager_id=emp.get("manager_id")`.
   - Simpan ke `self.credentials[emp_id]`:
     ```python
     username = (emp.get("username") or emp_id).casefold()
     pwd_hash = hash_password(emp.get("password", "Password#123"), salt="mem-salt")
     self.credentials[emp_id] = {
         "username": username,
         "password_hash": pwd_hash,
         "token": emp["token"],
         "context": self.identities[emp_id][0],
     }
     ```
4. Implementasikan `MemoryRepository.authenticate_password`:
   ```python
    def authenticate_password(self, username: str, password: str) -> LoginResponse | None:
        ident = username.strip().casefold()
        for emp_id, rec in self.credentials.items():
            if ident in (emp_id.casefold(), rec["username"]):
                if verify_password(password, rec["password_hash"]):
                    return LoginResponse(
                        access_token=rec["token"],
                        profile=rec["context"].model_copy(deep=True),
                    )
                return None
        return None
   ```
5. Pada `PostgresRepository.authenticate(self, token: str)` (sekitar baris 255), sertakan `department, manager_id` pada `SELECT`:
   ```python
            row = connection.execute(
                "SELECT employee_id, display_name, role, department, manager_id FROM employees WHERE token_hash = %s",
                (hashed,),
            ).fetchone()
   ```
6. Implementasikan `PostgresRepository.authenticate_password(self, username: str, password: str) -> LoginResponse | None`:
   - Cocokkan `LOWER(username) = LOWER(%s) OR LOWER(employee_id) = LOWER(%s)` di tabel `employees`.
   - Verifikasi password dengan `verify_password(password, row["password_hash"])`.
   - Jika cocok, ambil token yang sesuai dari `_load_employees()` berdasarkan `employee_id` dan kembalikan `LoginResponse(access_token=..., profile=AuthContext(...))`.

### Task 6: Tambahkan Endpoint `POST /api/v1/auth/login` di `src/api.py`

1. Impor `LoginRequest, LoginResponse` dari `.contracts` di `src/api.py`.
2. Tambahkan endpoint di dalam `create_app`:
   ```python
    @app.post("/api/v1/auth/login", response_model=LoginResponse)
    def login(payload: LoginRequest) -> LoginResponse:
        result = repository.authenticate_password(payload.username, payload.password)
        if result is None:
            raise HTTPException(status_code=401, detail="Invalid username or password")
        return result
   ```

### Task 7: Rombak Portal Akses di `app2.py` Menjadi Sub-App User List dengan Step-Up Re-Authentication (Manager & Admin)

Di `app2.py` pada bagian `VIEW 1: SUB-APP SESSION SELECTOR`:
- **Asumsi Sub-App:** Pengguna dianggap sudah terautentikasi pada aplikasi portal utama perusahaan, sehingga halaman awal menampilkan **Daftar Akun Pengguna (User Directory List)** dari `data/employees.json` (`EMP-001` Alya Pratama, `EMP-002` Bima Santoso, `MGR-001` Rakabuming Raka, `ADM-001` Monitoring Admin) tanpa form login username/password umum.
- **Alur Pegawai Reguler (`role: employee` — Alya & Bima):**
  - Menampilkan tombol langsung (**"Masuk sebagai [Nama]"** / **"Pilih Sesi"**).
  - Saat diklik, sistem langsung mengaktifkan sesi (`st.session_state["authenticated"] = True`, menyetel `active_persona` beserta `demo_token` pegawai terkait, memanggil `select_persona(...)`, dan `st.rerun()`) **tanpa meminta password**.
- **Alur Privileged Role (`role: manager` & `role: monitoring_admin` — Manager & Admin):**
  - Menampilkan indikator bahwa akun memiliki hak akses sensitif (*Step-Up Authentication Required*).
  - Saat akun Manager atau Admin dipilih, sistem membuka panel/form **Verifikasi Ulang Password (Re-Required Password)** khusus untuk akun terpilih (`st.session_state["pending_stepup_user"]`).
  - Saat password disubmit, UI memanggil `POST /api/v1/auth/login` dengan `username` akun terkait dan `password` yang diinputkan:
    - Jika HTTP 200: aktifkan sesi (`st.session_state["authenticated"] = True`), simpan profil dan `access_token`, bersihkan `pending_stepup_user`, dan `st.rerun()`.
    - Jika HTTP 401: tampilkan pesan gagal verifikasi password tanpa mengaktifkan sesi.
- **Keterangan Pengujian Demo:**
  - Sediakan informasi ringkas mengenai password demo (`Password#123`) untuk keperluan pengujian re-autentikasi akun Manager dan Admin.

### Task 8: Tambahkan Unit Test di `tests/self_test_contracts_config.py`

Tambahkan test `test_password_hashing_and_login_authentication()` di akhir `tests/self_test_contracts_config.py`:
- Memastikan `hash_password` dan `verify_password` bekerja dengan benar (password benar -> `True`, password salah -> `False`).
- Memastikan `MemoryRepository().authenticate_password("alya", "Password#123")` mengembalikan `LoginResponse` dengan `profile.employee_id == "EMP-001"` dan `access_token == "token-alya"`.
- Memastikan `MemoryRepository().authenticate_password` untuk akun Manager (`MGR-001` / `rakabuming` / alias `raka`) mengembalikan `profile.role == "manager"`.
- Memastikan password salah mengembalikan `None`.

---

## Langkah Verifikasi

```bash
pytest tests/test_supplied_ui.py tests/self_test_contracts_config.py tests/test_api.py -v
pytest -m "not live"
```

## Acceptance Criteria

- [x] `tests/test_supplied_ui.py` tetap lulus 100% (`demo_personas.json` tidak berubah).
- [x] Password disimpan sebagai salted hash PBKDF2-HMAC-SHA256 (`pbkdf2_sha256$...`), bukan plaintext di DB.
- [x] Endpoint `POST /api/v1/auth/login` mengembalikan 200 beserta `LoginResponse` untuk kredensial valid, dan 401 `ProblemDetail` untuk kredensial salah.
- [x] Akun Manager (`MGR-001` / `Rakabuming Raka`) terdaftar di `data/employees.json`.
- [x] `app2.py` beroperasi sebagai Sub-App: menampilkan daftar user, mengizinkan akses langsung tanpa password untuk role `employee`, dan mewajibkan re-input password (*Step-Up Authentication*) untuk role `manager` dan `monitoring_admin`.
