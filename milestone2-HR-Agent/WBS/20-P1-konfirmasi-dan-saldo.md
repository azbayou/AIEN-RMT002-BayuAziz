# WBS-20-P1 — Keamanan Transaksi Konfirmasi, Re-validasi Overlap, dan Reservasi Saldo

- **Target:** `src/repository.py`, `tests/self_test_contracts_config.py`.
- **Owner:** Agent AI.
- **Dependency:** WBS-19-P0.
- **Status:** DONE

## Batasan Scope (Wajib Dipatuhi Agent)

- **Boleh diedit:** `src/repository.py`, `tests/self_test_contracts_config.py`.
- **DILARANG diedit:** `src/contracts.py`, `src/domain.py`, `src/tools.py`, atau `tests/test_actions.py`.
- Pertahankan seluruh signature method di `Repository`, `MemoryRepository`, dan `PostgresRepository` agar kompatibel 100% dengan kontrak yang sudah ada.

---

## Pekerjaan

### Task 1: Kurangi `available_days` dengan hari kerja dari request yang masih `pending_manager_review`

Ketika pegawai sudah mengonfirmasi satu proposal (status `pending_manager_review`), saldo efektifnya harus berkurang sebesar `business_days` yang sedang pending agar pegawai tidak bisa mengajukan cuti melebihi kuota.

#### 1a. Pada `MemoryRepository.get_balances(self, employee_id: str) -> list[LeaveBalance]`

Ubah implementasi di `src/repository.py` (sekitar baris 114) menjadi:

```python
    def get_balances(self, employee_id: str) -> list[LeaveBalance]:
        pending_by_type: dict[str, int] = {}
        for req in self.requests.get(employee_id, []):
            if req.status == "pending_manager_review":
                pending_by_type[req.leave_type] = pending_by_type.get(req.leave_type, 0) + req.business_days
        result: list[LeaveBalance] = []
        for balance in self.balances.get(employee_id, []):
            reserved = pending_by_type.get(balance.leave_type, 0)
            effective = max(0, balance.available_days - reserved)
            result.append(balance.model_copy(update={"available_days": effective}, deep=True))
        return result
```

#### 1b. Pada `PostgresRepository.get_balances(self, employee_id: str) -> list[LeaveBalance]`

Ubah query di `src/repository.py` (sekitar baris 305) agar mengurangi `available_days` dengan total `business_days` yang berstatus `pending_manager_review`:

```python
    def get_balances(self, employee_id: str) -> list[LeaveBalance]:
        with self.pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    b.leave_type,
                    GREATEST(
                        0,
                        b.available_days - COALESCE((
                            SELECT SUM(r.business_days)::int
                            FROM leave_requests r
                            WHERE r.employee_id = b.employee_id
                              AND r.leave_type = b.leave_type
                              AND r.status = 'pending_manager_review'
                        ), 0)
                    ) AS available_days,
                    b.as_of_date
                FROM leave_balances b
                WHERE b.employee_id = %s
                ORDER BY b.leave_type
                """,
                (employee_id,),
            ).fetchall()
        return [LeaveBalance(**row) for row in rows]
```

### Task 2: Perbaiki urutan replay vs expiry, re-validasi overlap & saldo, dan cegah reuse idempotency key pada `confirm_proposal`

Masalah saat ini:
1. Jika proposal sudah dikonfirmasi sebelumnya dan klien melakukan retry dengan `idempotency_key` yang sama setelah `expires_at` lewat, sistem malah melempar `ConflictError("proposal expired")`. Padahal idempotent replay harus tetap berhasil.
2. Saat `confirm_proposal` dipanggil, sistem tidak mengecek ulang apakah tanggal proposal bertabrakan dengan request yang baru saja dikonfirmasi dari proposal lain, atau apakah saldo efektif masih cukup.
3. Jika `idempotency_key` yang sudah dipakai pada proposal A dikirim untuk mengonfirmasi proposal B milik pegawai yang sama, PostgreSQL melempar `UniqueViolation` (HTTP 500), bukan `ConflictError` (HTTP 409).

#### 2a. Ganti `MemoryRepository.confirm_proposal` (sekitar baris 134) dengan logika berikut:

```python
    def confirm_proposal(self, employee_id: str, proposal_id: str, idempotency_key: str) -> ActionResult:
        with self._lock:
            item = self.proposals.get(proposal_id)
            if item is None or item[0] != employee_id:
                raise KeyError("proposal not found")
            owner, proposal = item

            # 1. Cek existing request untuk proposal ini terlebih dahulu (idempotent replay menang atas expiry)
            existing = next(
                (request for request in self.requests.get(owner, []) if request.request_id == proposal_id),
                None,
            )
            if existing is not None:
                if existing.status != "pending_manager_review":
                    raise ConflictError("proposal already finalized")
                prior_key = self.idempotency_keys.get(proposal_id)
                if prior_key != idempotency_key:
                    raise ConflictError("proposal already confirmed with another key")
                return ActionResult(
                    request_id=existing.request_id,
                    idempotent_replay=True,
                    audit_reference=f"audit-{existing.request_id}",
                )

            # 2. Cegah penggunaan idempotency_key yang sama pada proposal berbeda milik employee yang sama
            for other_prop_id, used_key in self.idempotency_keys.items():
                if other_prop_id != proposal_id and used_key == idempotency_key:
                    other_owner = self.proposals.get(other_prop_id, (None, None))[0]
                    if other_owner == owner:
                        raise ConflictError("idempotency key already used for another proposal")

            # 3. Cek expiry untuk konfirmasi baru
            expiry = proposal.expires_at
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry <= datetime.now(timezone.utc):
                raise ConflictError("proposal expired")

            # 4. Re-validasi overlap terhadap request aktif
            if self.has_overlap(owner, proposal.start_date, proposal.end_date):
                raise ConflictError("leave dates overlap with an existing request")

            # 5. Re-validasi saldo efektif
            balances = self.get_balances(owner)
            balance = next((b for b in balances if b.leave_type == proposal.leave_type), None)
            if balance is None or balance.available_days < proposal.business_days:
                raise ConflictError("insufficient leave balance at confirmation")

            request = LeaveRequestView(
                request_id=proposal.proposal_id,
                leave_type=proposal.leave_type,
                start_date=proposal.start_date,
                end_date=proposal.end_date,
                business_days=proposal.business_days,
                status="pending_manager_review",
                created_at=datetime.now(timezone.utc),
            )
            self.idempotency_keys[proposal_id] = idempotency_key
            self.requests.setdefault(owner, []).append(request)
            return ActionResult(
                request_id=request.request_id,
                idempotent_replay=False,
                audit_reference=f"audit-{request.request_id}",
            )
```

#### 2b. Ganti `PostgresRepository.confirm_proposal` (sekitar baris 382) dengan logika berikut:

```python
    def confirm_proposal(self, employee_id: str, proposal_id: str, idempotency_key: str) -> ActionResult:
        with self.pool.connection() as connection:
            with connection.transaction():
                # Lock row employee agar konfirmasi paralel dari pegawai yang sama dieksekusi berurutan
                connection.execute(
                    "SELECT employee_id FROM employees WHERE employee_id = %s FOR UPDATE",
                    (employee_id,),
                ).fetchone()
                proposal = connection.execute(
                    """
                    SELECT proposal_id, action_type, leave_type, start_date, end_date, business_days,
                           reason, validation_summary, expires_at
                    FROM action_proposals
                    WHERE proposal_id = %s AND employee_id = %s
                    FOR UPDATE
                    """,
                    (proposal_id, employee_id),
                ).fetchone()
                if not proposal:
                    raise KeyError("proposal not found")

                # 1. Cek existing request untuk proposal ini terlebih dahulu (replay menang atas expiry)
                existing = connection.execute(
                    """
                    SELECT request_id, idempotency_key, status
                    FROM leave_requests
                    WHERE proposal_id = %s AND employee_id = %s
                    FOR UPDATE
                    """,
                    (proposal_id, employee_id),
                ).fetchone()
                if existing:
                    if existing["idempotency_key"] != idempotency_key:
                        raise ConflictError("proposal already confirmed with another key")
                    if existing["status"] != "pending_manager_review":
                        raise ConflictError("proposal already finalized")
                    return ActionResult(
                        request_id=existing["request_id"],
                        idempotent_replay=True,
                        audit_reference=f"audit-{existing['request_id']}",
                    )

                # 2. Cegah reuse idempotency_key pada proposal berbeda milik employee yang sama
                key_used = connection.execute(
                    """
                    SELECT 1 FROM leave_requests
                    WHERE employee_id = %s AND idempotency_key = %s
                    """,
                    (employee_id, idempotency_key),
                ).fetchone()
                if key_used:
                    raise ConflictError("idempotency key already used for another proposal")

                # 3. Cek expiry untuk konfirmasi baru
                expiry = proposal["expires_at"]
                if expiry <= datetime.now(timezone.utc):
                    raise ConflictError("proposal expired")

                # 4. Re-validasi overlap terhadap request yang sudah ada
                overlap_row = connection.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM leave_requests
                        WHERE employee_id = %s
                          AND status IN ('pending_manager_review', 'approved')
                          AND start_date <= %s AND end_date >= %s
                    ) AS overlaps
                    """,
                    (employee_id, proposal["end_date"], proposal["start_date"]),
                ).fetchone()
                if overlap_row and overlap_row["overlaps"]:
                    raise ConflictError("leave dates overlap with an existing request")

                # 5. Re-validasi saldo efektif
                bal_row = connection.execute(
                    """
                    SELECT
                        b.available_days - COALESCE((
                            SELECT SUM(r.business_days)::int
                            FROM leave_requests r
                            WHERE r.employee_id = b.employee_id
                              AND r.leave_type = b.leave_type
                              AND r.status = 'pending_manager_review'
                        ), 0) AS effective_days
                    FROM leave_balances b
                    WHERE b.employee_id = %s AND b.leave_type = %s
                    FOR UPDATE
                    """,
                    (employee_id, proposal["leave_type"]),
                ).fetchone()
                if not bal_row or int(bal_row["effective_days"]) < int(proposal["business_days"]):
                    raise ConflictError("insufficient leave balance at confirmation")

                request_id = proposal_id
                connection.execute(
                    """
                    INSERT INTO leave_requests
                        (request_id, proposal_id, employee_id, leave_type, start_date, end_date,
                         business_days, status, idempotency_key)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending_manager_review', %s)
                    """,
                    (
                        request_id,
                        proposal_id,
                        employee_id,
                        proposal["leave_type"],
                        proposal["start_date"],
                        proposal["end_date"],
                        proposal["business_days"],
                        idempotency_key,
                    ),
                )
        return ActionResult(
            request_id=request_id,
            idempotent_replay=False,
            audit_reference=f"audit-{request_id}",
        )
```

#### 2c. Perbarui juga `PostgresRepository.has_overlap` (sekitar baris 318)

Ubah `AND status = 'pending_manager_review'` menjadi `AND status IN ('pending_manager_review', 'approved')` agar permohonan yang sudah disetujui juga diperhitungkan saat pengecekan tumpang tindih.

### Task 3: Tambahkan unit test untuk skenario baru di `tests/self_test_contracts_config.py`

Tambahkan 3 fungsi test di akhir `tests/self_test_contracts_config.py`:

1. `test_confirm_proposal_revalidates_overlap_and_reserves_balance()`:
   - Buat 2 proposal (`AP-1` dan `AP-2`) dengan tanggal yang sama untuk `EMP-001`.
   - Konfirmasi `AP-1` → berhasil, dan verifikasi `repo.get_balances("EMP-001")` untuk `"annual"` berkurang sebesar `business_days` dari `AP-1`.
   - Konfirmasi `AP-2` → wajib melempar `ConflictError` dengan pesan mengandung `"overlap"`.
2. `test_idempotent_replay_succeeds_even_after_proposal_expires()`:
   - Simpan proposal `AP-EXP` untuk `EMP-001` yang masih aktif, lalu konfirmasi dengan `"key-replay-01"`.
   - Ubah `expires_at` pada `repo.proposals["AP-EXP"]` menjadi masa lalu (`now - 5 menit`).
   - Panggil `confirm_proposal("EMP-001", "AP-EXP", "key-replay-01")` lagi → tetap berhasil dan `idempotent_replay is True`.
3. `test_reusing_idempotency_key_across_different_proposals_raises_conflict()`:
   - Simpan 2 proposal berbeda tanggal (`AP-A` dan `AP-B`) untuk `EMP-001`.
   - Konfirmasi `AP-A` dengan `"same-key-123"`.
   - Konfirmasi `AP-B` dengan `"same-key-123"` → wajib melempar `ConflictError`.

---

## Langkah Verifikasi

```bash
pytest tests/test_actions.py tests/self_test_contracts_config.py -v
pytest -m "not live"
```

## Acceptance Criteria

- [x] `tests/test_actions.py` (6 test bawaan) tetap lulus 100%.
- [x] Saldo efektif di `get_balances` berkurang sesuai `business_days` yang masih berstatus `pending_manager_review`.
- [x] Dua proposal dengan tanggal tumpang tindih atau melebihi sisa saldo tidak dapat dikonfirmasi keduanya.
- [x] Replay dengan `idempotency_key` yang sama tetap mengembalikan `ActionResult(idempotent_replay=True)` meskipun waktu proposal sudah lewat setelah konfirmasi pertama.
- [x] Reuse `idempotency_key` pada proposal lain menghasilkan `ConflictError` (HTTP 409).

## Checkpoint 2026-11-09 — FINAL

- Status: **DONE**
- **Bukti & Hasil Verifikasi:**
  1. `get_balances` di `MemoryRepository` dan `PostgresRepository` diperbarui untuk mengurangkan `business_days` dari permohonan berstatus `pending_manager_review`, mencegah eksploitasi permohonan paralel yang melebihi kuota.
  2. Logika `confirm_proposal` pada `MemoryRepository` dan `PostgresRepository` diperbaiki secara atomik:
     - Idempotent replay diprioritaskan sebelum pengecekan expiry (replay tetap berhasil meskipun proposal expired setelah konfirmasi pertama).
     - Penggunaan ulang `idempotency_key` lintas proposal untuk pegawai yang sama dideteksi dan ditolak dengan `ConflictError`.
     - Re-validasi overlap dan saldo efektif dijalankan di dalam transaksi (dengan `FOR UPDATE` lock pada PostgreSQL).
  3. `PostgresRepository.has_overlap` diperluas untuk memperhitungkan status `approved` selain `pending_manager_review`.
  4. Seluruh 6 unit test bawaan di `tests/test_actions.py` diverifikasi lulus 100%.
  5. Tiga unit test baru di `tests/self_test_contracts_config.py` (`test_confirm_proposal_revalidates_overlap_and_reserves_balance`, `test_idempotent_replay_succeeds_even_after_proposal_expires`, `test_reusing_idempotency_key_across_different_proposals_raises_conflict`) diverifikasi lulus 100%.

