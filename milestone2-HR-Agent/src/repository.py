"""Repository contracts. Implement MemoryRepository first, then PostgreSQL/pgvector."""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import date, datetime, timezone
import json
from math import sqrt
from pathlib import Path
import re
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from psycopg.types.json import Jsonb

from .contracts import (
    ActionProposal,
    ActionResult,
    AuthContext,
    LeaveAttachmentView,
    LeaveBalance,
    LeaveRequestView,
    LoginResponse,
    ManagerReviewResult,
    PolicyChunk,
)
from .security import hash_password, redact, token_hash, verify_password

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _load_employees() -> list[dict[str, Any]]:
    path = _DATA_DIR / "employees.json"
    if not path.is_file():
        raise FileNotFoundError(f"Employees catalog not found at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


class Repository(Protocol):
    def health(self) -> bool: ...
    def authenticate(self, token: str) -> AuthContext | None: ...
    def authenticate_password(self, username: str, password: str) -> LoginResponse | None: ...
    def lexical_search(self, query: str, limit: int) -> list[PolicyChunk]: ...
    def vector_search(self, embedding: list[float], limit: int) -> list[PolicyChunk]: ...
    def get_balances(self, employee_id: str) -> list[LeaveBalance]: ...
    def has_overlap(self, employee_id: str, start: date, end: date) -> bool: ...
    def save_proposal(self, employee_id: str, proposal: ActionProposal) -> None: ...
    def get_proposal(self, proposal_id: str) -> tuple[str, ActionProposal] | None: ...
    def confirm_proposal(self, employee_id: str, proposal_id: str, idempotency_key: str) -> ActionResult: ...
    def list_leave_requests(self, employee_id: str) -> list[LeaveRequestView]: ...
    def list_team_leave_requests(self, manager_id: str, include_all_departments: bool = False) -> list[LeaveRequestView]: ...
    def review_leave_request(
        self,
        reviewer_id: str,
        request_id: str,
        decision: str,
        review_note: str,
        is_admin: bool = False,
    ) -> ManagerReviewResult: ...
    def save_leave_attachment(
        self,
        employee_id: str,
        request_id: str,
        filename: str,
        content_type: str,
        file_bytes: bytes,
    ) -> LeaveAttachmentView: ...
    def get_leave_attachment(
        self,
        requester: AuthContext,
        request_id: str,
    ) -> LeaveAttachmentView: ...
    def create_ticket(self, employee_id: str, category: str, summary: str) -> str: ...
    def save_trace(self, trace: dict[str, Any]) -> None: ...
    def get_trace(self, trace_id: str) -> dict[str, Any] | None: ...
    def monitoring_summary(self) -> dict[str, Any]: ...
    def get_hr_analytics(self, auth: AuthContext, metric_focus: str = "overview", low_balance_threshold: int = 3) -> dict[str, Any]: ...


class ConflictError(RuntimeError):
    pass


class MemoryRepository:
    def __init__(self) -> None:
        self.chunks: list[PolicyChunk] = []
        self.identities: dict[str, tuple[AuthContext, str]] = {}
        self.credentials: dict[str, dict[str, Any]] = {}
        self.balances: dict[str, list[LeaveBalance]] = {}
        today = date.today()
        for emp in _load_employees():
            emp_id = emp["employee_id"]
            auth_ctx = AuthContext(
                employee_id=emp_id,
                display_name=emp["display_name"],
                role=emp.get("role", "employee"),
                department=emp.get("department"),
                manager_id=emp.get("manager_id"),
            )
            self.identities[emp_id] = (
                auth_ctx,
                token_hash(emp["token"]),
            )
            username = (emp.get("username") or emp_id).casefold()
            pwd_hash = hash_password(emp.get("password", "Password#123"), salt="mem-salt")
            self.credentials[emp_id] = {
                "username": username,
                "password_hash": pwd_hash,
                "token": emp["token"],
                "context": auth_ctx,
            }
            self.balances[emp_id] = [
                LeaveBalance(leave_type=leave_type, available_days=days, as_of_date=today)
                for leave_type, days in emp.get("balances", {}).items()
            ]
        self.proposals: dict[str, tuple[str, ActionProposal]] = {}
        self.idempotency_keys: dict[str, str] = {}
        self.embeddings: dict[str, list[float]] = {}
        self.requests: dict[str, list[LeaveRequestView]] = {}
        self.attachments: dict[str, dict[str, Any]] = {}
        self.approval_audits: list[dict[str, Any]] = []
        self.tickets: dict[str, dict[str, str]] = {}
        self.traces: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    def health(self) -> bool:
        return True

    def authenticate(self, token: str) -> AuthContext | None:
        hashed = token_hash(token)
        for context, stored_hash in self.identities.values():
            if stored_hash == hashed:
                return context.model_copy(deep=True)
        return None

    def authenticate_password(self, username: str, password: str) -> LoginResponse | None:
        ident = username.strip().casefold()
        for emp_id, rec in self.credentials.items():
            valid_idents = {emp_id.casefold(), rec["username"]}
            if emp_id.casefold() == "mgr-001":
                valid_idents.update(["raka", "rakabuming"])
            if ident in valid_idents:
                if verify_password(password, rec["password_hash"]):
                    return LoginResponse(
                        access_token=rec["token"],
                        profile=rec["context"].model_copy(deep=True),
                    )
                return None
        return None

    def lexical_search(self, query: str, limit: int) -> list[PolicyChunk]:
        stopwords = {"berapa", "apakah", "bagaimana", "kapan", "siapa", "yang", "dan", "di", "ke", "dari", "untuk", "pada", "saya", "aku", "bisa", "boleh", "per"}
        raw_terms = [t for t in re.findall(r"[a-z0-9]+", query.casefold()) if len(t) >= 2]
        terms = set(t for t in raw_terms if t not in stopwords) or set(raw_terms)
        if not terms:
            return []
        ranked: list[tuple[int, PolicyChunk]] = []
        for chunk in self.chunks:
            haystack_text = f"{chunk.title} {chunk.section} {chunk.content}".casefold()
            haystack_tokens = set(re.findall(r"[a-z0-9]+", haystack_text))
            title_tokens = set(re.findall(r"[a-z0-9]+", f"{chunk.title} {chunk.section}".casefold()))
            score = sum(
                (
                    3
                    if term in title_tokens
                    else (2 if term in haystack_tokens else (1 if len(term) >= 4 and term in haystack_text else 0))
                )
                for term in terms
            )
            if score:
                ranked.append((score, chunk))
        ranked.sort(key=lambda item: (-item[0], item[1].chunk_id))
        return [chunk.model_copy(update={"score": float(score)}) for score, chunk in ranked[:limit]]

    def vector_search(self, embedding: list[float], limit: int) -> list[PolicyChunk]:
        if not embedding:
            return []
        ranked: list[tuple[float, PolicyChunk]] = []
        for chunk in self.chunks:
            vector = self.embeddings.get(chunk.chunk_id)
            if not isinstance(vector, list) or len(vector) != len(embedding):
                continue
            norm = sqrt(sum(value * value for value in embedding) * sum(value * value for value in vector))
            similarity = sum(left * right for left, right in zip(embedding, vector)) / norm if norm else 0.0
            ranked.append((similarity, chunk))
        ranked.sort(key=lambda item: (-item[0], item[1].chunk_id))
        return [chunk.model_copy(update={"score": score}) for score, chunk in ranked[:limit]]

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

    def has_overlap(self, employee_id: str, start: date, end: date) -> bool:
        return any(
            request.start_date <= end and request.end_date >= start
            for request in self.requests.get(employee_id, [])
            if request.status in ("pending_manager_review", "approved")
        )

    def save_proposal(self, employee_id: str, proposal: ActionProposal) -> None:
        with self._lock:
            self.proposals[proposal.proposal_id] = (employee_id, proposal.model_copy(deep=True))

    def get_proposal(self, proposal_id: str) -> tuple[str, ActionProposal] | None:
        item = self.proposals.get(proposal_id)
        if item is None:
            return None
        owner, proposal = item
        return owner, proposal.model_copy(deep=True)

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

            emp_ctx = self.identities.get(owner, (None, None))[0]
            display_name = emp_ctx.display_name if emp_ctx else None
            request = LeaveRequestView(
                request_id=proposal.proposal_id,
                leave_type=proposal.leave_type,
                start_date=proposal.start_date,
                end_date=proposal.end_date,
                business_days=proposal.business_days,
                status="pending_manager_review",
                created_at=datetime.now(timezone.utc),
                employee_id=owner,
                employee_name=display_name,
            )
            self.idempotency_keys[proposal_id] = idempotency_key
            self.requests.setdefault(owner, []).append(request)
            return ActionResult(
                request_id=request.request_id,
                idempotent_replay=False,
                audit_reference=f"audit-{request.request_id}",
            )

    def _enrich_with_attachment_meta(self, req: LeaveRequestView) -> LeaveRequestView:
        att = self.attachments.get(req.request_id)
        if att:
            return req.model_copy(
                update={
                    "has_attachment": True,
                    "attachment_filename": att["filename"],
                    "attachment_content_type": att["content_type"],
                    "attachment_size_bytes": att["file_size_bytes"],
                    "attachment_uploaded_at": att["uploaded_at"],
                },
                deep=True,
            )
        return req

    def list_leave_requests(self, employee_id: str) -> list[LeaveRequestView]:
        return [
            self._enrich_with_attachment_meta(request.model_copy(deep=True))
            for request in self.requests.get(employee_id, [])
        ]

    def list_team_leave_requests(self, manager_id: str, include_all_departments: bool = False) -> list[LeaveRequestView]:
        items: list[LeaveRequestView] = []
        for emp_id, req_list in self.requests.items():
            ctx = self.identities.get(emp_id, (None, None))[0]
            if ctx is None:
                continue
            if include_all_departments or ctx.manager_id == manager_id:
                for req in req_list:
                    items.append(
                        self._enrich_with_attachment_meta(
                            req.model_copy(
                                update={"employee_id": emp_id, "employee_name": ctx.display_name},
                                deep=True,
                            )
                        )
                    )
        items.sort(key=lambda r: (r.created_at, r.request_id), reverse=True)
        return items

    def review_leave_request(
        self,
        reviewer_id: str,
        request_id: str,
        decision: str,
        review_note: str,
        is_admin: bool = False,
    ) -> ManagerReviewResult:
        with self._lock:
            target_req: LeaveRequestView | None = None
            owner_id: str | None = None
            for emp_id, req_list in self.requests.items():
                for req in req_list:
                    if req.request_id == request_id:
                        target_req = req
                        owner_id = emp_id
                        break
                if target_req is not None:
                    break

            if target_req is None or owner_id is None:
                raise KeyError("leave request not found")

            # Guardrail 1 (No Self-Approval)
            if owner_id == reviewer_id:
                raise ConflictError("manager cannot review own leave request")

            # Guardrail 2 (Subordinate Isolation)
            owner_ctx = self.identities.get(owner_id, (None, None))[0]
            if not is_admin and (owner_ctx is None or owner_ctx.manager_id != reviewer_id):
                raise KeyError("leave request not found in manager team")

            # Guardrail 3 (State Transition)
            if target_req.status != "pending_manager_review":
                raise ConflictError(f"leave request already finalized as {target_req.status}")

            # Guardrail 4 (Balance Deduction saat approved)
            if decision == "approved":
                emp_balances = self.balances.get(owner_id, [])
                bal = next((b for b in emp_balances if b.leave_type == target_req.leave_type), None)
                if bal is None or bal.available_days < target_req.business_days:
                    raise ConflictError("insufficient balance")
                bal.available_days -= target_req.business_days

            clean_note = redact(review_note)
            now_dt = datetime.now(timezone.utc)
            updated_req = target_req.model_copy(
                update={
                    "status": decision,
                    "reviewed_by": reviewer_id,
                    "review_note": clean_note,
                    "reviewed_at": now_dt,
                    "employee_id": owner_id,
                    "employee_name": owner_ctx.display_name if owner_ctx else None,
                },
                deep=True,
            )
            idx = self.requests[owner_id].index(target_req)
            self.requests[owner_id][idx] = updated_req

            audit_ref = f"audit-review-{target_req.request_id}-{uuid4().hex[:8]}"
            self.approval_audits.append({
                "audit_id": audit_ref,
                "request_id": target_req.request_id,
                "reviewer_id": reviewer_id,
                "previous_status": "pending_manager_review",
                "new_status": decision,
                "review_note": clean_note,
                "created_at": now_dt,
            })
            return ManagerReviewResult(
                request_id=target_req.request_id,
                employee_id=owner_id,
                status=decision,
                reviewed_by=reviewer_id,
                review_note=clean_note,
                reviewed_at=now_dt,
                audit_reference=audit_ref,
            )

    def save_leave_attachment(
        self,
        employee_id: str,
        request_id: str,
        filename: str,
        content_type: str,
        file_bytes: bytes,
    ) -> LeaveAttachmentView:
        with self._lock:
            user_reqs = self.requests.get(employee_id, [])
            target_req = next((r for r in user_reqs if r.request_id == request_id), None)
            if target_req is None:
                raise KeyError("leave request not found")
            if target_req.leave_type != "sick":
                raise ConflictError("attachment is only supported for sick leave requests")
            if target_req.status != "pending_manager_review":
                raise ConflictError("cannot attach document to finalized leave request")

            uploaded_at = datetime.now(timezone.utc)
            att_data = {
                "request_id": request_id,
                "employee_id": employee_id,
                "filename": filename,
                "content_type": content_type,
                "file_size_bytes": len(file_bytes),
                "file_bytes": file_bytes,
                "uploaded_at": uploaded_at,
            }
            self.attachments[request_id] = att_data
            return LeaveAttachmentView(
                request_id=request_id,
                employee_id=employee_id,
                filename=filename,
                content_type=content_type,
                file_size_bytes=len(file_bytes),
                content_base64=base64.b64encode(file_bytes).decode("ascii"),
                uploaded_at=uploaded_at,
            )

    def get_leave_attachment(
        self,
        requester: AuthContext,
        request_id: str,
    ) -> LeaveAttachmentView:
        with self._lock:
            att = self.attachments.get(request_id)
            if att is None:
                raise KeyError("attachment not found")
            owner_id = att["employee_id"]
            owner_ctx = self.identities.get(owner_id, (None, None))[0]

            is_owner = requester.employee_id == owner_id
            is_admin = requester.role == "monitoring_admin"
            is_manager = (
                requester.role == "manager"
                and owner_ctx is not None
                and owner_ctx.manager_id == requester.employee_id
            )
            if not (is_owner or is_admin or is_manager):
                raise PermissionError("not authorized to view this attachment")

            file_bytes = att["file_bytes"]
            return LeaveAttachmentView(
                request_id=att["request_id"],
                employee_id=att["employee_id"],
                filename=att["filename"],
                content_type=att["content_type"],
                file_size_bytes=att["file_size_bytes"],
                content_base64=base64.b64encode(file_bytes).decode("ascii"),
                uploaded_at=att["uploaded_at"],
            )

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

    def save_trace(self, trace: dict[str, Any]) -> None:
        trace_id = str(trace["trace_id"])
        self.traces[trace_id] = redact_trace(trace)

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        trace = self.traces.get(trace_id)
        return deepcopy(trace) if trace is not None else None

    def monitoring_summary(self) -> dict[str, Any]:
        traces = list(self.traces.values())
        total = len(traces)
        errors = sum(bool(trace.get("error")) for trace in traces)
        abstains = sum(trace.get("outcome") == "abstained" for trace in traces)
        blocked = sum(bool(trace.get("blocked_reason")) for trace in traces)
        latencies = [
            float(trace.get("usage", {}).get("latency_ms", 0.0))
            for trace in traces
            if isinstance(trace.get("usage"), dict) and trace.get("usage", {}).get("latency_ms") is not None
        ]
        p95_latency = (
            sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)]
            if latencies
            else 0.0
        )
        tool_calls_count = sum(
            len(trace.get("tool_calls", []))
            for trace in traces
            if isinstance(trace.get("tool_calls"), list)
        )
        return {
            "run_count": total,
            "total_traces": total,
            "error_count": errors,
            "error_rate": errors / total if total else 0.0,
            "abstain_count": abstains,
            "abstain_rate": abstains / total if total else 0.0,
            "blocked_count": blocked,
            "p95_latency_ms": p95_latency,
            "tool_calls": tool_calls_count,
        }

    def get_hr_analytics(self, auth: AuthContext, metric_focus: str = "overview", low_balance_threshold: int = 3) -> dict[str, Any]:
        if auth.role not in ("manager", "monitoring_admin"):
            raise PermissionError("analytics requires manager or admin role")

        is_admin = auth.role == "monitoring_admin"
        scope = "organization" if is_admin else "team"

        if is_admin:
            scoped_employees = [
                ctx for ctx, _ in self.identities.values() if ctx.role != "monitoring_admin"
            ]
        else:
            scoped_employees = [
                ctx for ctx, _ in self.identities.values() if ctx.manager_id == auth.employee_id
            ]

        scoped_emp_ids = [ctx.employee_id for ctx in scoped_employees]
        team_size = len(scoped_emp_ids)

        requests_by_status = {
            "pending_manager_review": 0,
            "approved": 0,
            "rejected": 0,
            "cancelled": 0,
        }
        days_by_leave_type = {
            "annual": 0,
            "sick": 0,
            "parental": 0,
        }
        department_breakdown: dict[str, dict[str, int]] = {}
        for ctx in scoped_employees:
            dept = ctx.department or "Unknown"
            if dept not in department_breakdown:
                department_breakdown[dept] = {"employee_count": 0, "active_leave_days": 0}
            department_breakdown[dept]["employee_count"] += 1

        for emp_id in scoped_emp_ids:
            ctx = self.identities.get(emp_id, (None, None))[0]
            dept = (ctx.department if ctx else None) or "Unknown"
            for req in self.requests.get(emp_id, []):
                if req.status in requests_by_status:
                    requests_by_status[req.status] += 1
                else:
                    requests_by_status[req.status] = 1

                if req.status in ("pending_manager_review", "approved"):
                    days_by_leave_type[req.leave_type] = days_by_leave_type.get(req.leave_type, 0) + req.business_days
                    if dept in department_breakdown:
                        department_breakdown[dept]["active_leave_days"] += req.business_days

        low_balance_employees = []
        for ctx in scoped_employees:
            balances = self.get_balances(ctx.employee_id)
            annual_bal = next((b.available_days for b in balances if b.leave_type == "annual"), 0)
            if annual_bal <= low_balance_threshold:
                low_balance_employees.append({
                    "employee_id": ctx.employee_id,
                    "display_name": ctx.display_name,
                    "annual_remaining": annual_bal,
                })
        low_balance_employees.sort(key=lambda x: (x["annual_remaining"], x["employee_id"]))

        analytics: dict[str, Any] = {
            "scope": scope,
            "metric_focus": metric_focus,
            "low_balance_threshold": low_balance_threshold,
            "team_size": team_size,
            "requests_by_status": requests_by_status,
            "days_by_leave_type": days_by_leave_type,
            "low_balance_employees": low_balance_employees,
            "department_breakdown": department_breakdown,
        }

        if is_admin:
            tickets_by_category: dict[str, int] = {}
            for ticket in self.tickets.values():
                cat = ticket.get("category", "unknown")
                tickets_by_category[cat] = tickets_by_category.get(cat, 0) + 1
            analytics["tickets_by_category"] = tickets_by_category
            analytics["ai_operations"] = self.monitoring_summary()

        return analytics


def redact_trace(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: redact_trace(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_trace(item) for item in value]
    return value


class PostgresRepository:
    def __init__(self, database_url: str, embedding_dimensions: int) -> None:
        self.embedding_dimensions = embedding_dimensions
        self.pool = ConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=8,
            kwargs={"row_factory": dict_row},
            open=True,
        )
        try:
            with self.pool.connection() as conn:
                conn.execute("ALTER TABLE action_proposals ADD COLUMN IF NOT EXISTS requires_attachment BOOLEAN DEFAULT FALSE;")
        except Exception:
            pass

    def health(self) -> bool:
        try:
            with self.pool.connection() as connection:
                row = connection.execute(
                    "SELECT COUNT(*) AS chunk_count FROM policy_chunks"
                ).fetchone()
            return bool(row and int(row["chunk_count"]) > 0)
        except Exception:
            return False

    def authenticate(self, token: str) -> AuthContext | None:
        hashed = token_hash(token)
        with self.pool.connection() as connection:
            row = connection.execute(
                "SELECT employee_id, display_name, role, department, manager_id FROM employees WHERE token_hash = %s",
                (hashed,),
            ).fetchone()
        return AuthContext(**row) if row else None

    def authenticate_password(self, username: str, password: str) -> LoginResponse | None:
        ident = username.strip().casefold()
        with self.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT employee_id, username, password_hash, display_name, role, department, manager_id
                FROM employees
                WHERE LOWER(username) = %s OR LOWER(employee_id) = %s
                """,
                (ident, ident),
            ).fetchone()
            if not row and ident in ("raka", "rakabuming"):
                row = connection.execute(
                    """
                    SELECT employee_id, username, password_hash, display_name, role, department, manager_id
                    FROM employees
                    WHERE employee_id = 'MGR-001'
                    """
                ).fetchone()
        if not row or not row.get("password_hash"):
            return None
        if not verify_password(password, row["password_hash"]):
            return None
        token_map = {e["employee_id"]: e["token"] for e in _load_employees()}
        token = token_map.get(row["employee_id"], "")
        profile = AuthContext(
            employee_id=row["employee_id"],
            display_name=row["display_name"],
            role=row["role"],
            department=row.get("department"),
            manager_id=row.get("manager_id"),
        )
        return LoginResponse(access_token=token, profile=profile)

    @staticmethod
    def _chunk(row: dict[str, Any]) -> PolicyChunk:
        return PolicyChunk(**row)

    def lexical_search(self, query: str, limit: int) -> list[PolicyChunk]:
        stopwords = {"berapa", "apakah", "bagaimana", "kapan", "siapa", "yang", "dan", "di", "ke", "dari", "untuk", "pada", "saya", "aku", "bisa", "boleh"}
        raw_terms = [t for t in re.findall(r"[a-z0-9]+", query.casefold()) if len(t) >= 2]
        filtered_terms = [t for t in raw_terms if t not in stopwords] or raw_terms
        if not filtered_terms:
            return []
        tsquery_str = " | ".join(filtered_terms)
        with self.pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT chunk_id, document_id, title, section, version, effective_date, content,
                       ts_rank(
                           to_tsvector('simple', title || ' ' || section || ' ' || content),
                           to_tsquery('simple', %s)
                       ) AS score
                FROM policy_chunks
                WHERE effective_date <= CURRENT_DATE
                  AND to_tsvector('simple', title || ' ' || section || ' ' || content)
                      @@ to_tsquery('simple', %s)
                ORDER BY score DESC, chunk_id
                LIMIT %s
                """,
                (tsquery_str, tsquery_str, limit),
            ).fetchall()
        return [self._chunk(row) for row in rows]

    def vector_search(self, embedding: list[float], limit: int) -> list[PolicyChunk]:
        if not embedding:
            return []
        vector = "[" + ",".join(str(float(value)) for value in embedding) + "]"
        with self.pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT chunk_id, document_id, title, section, version, effective_date, content,
                       1 - (embedding <=> %s::vector) AS score
                FROM policy_chunks
                WHERE vector_dims(embedding) = %s AND effective_date <= CURRENT_DATE
                ORDER BY embedding <=> %s::vector, chunk_id
                LIMIT %s
                """,
                (vector, self.embedding_dimensions, vector, limit),
            ).fetchall()
        return [self._chunk(row) for row in rows]

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

    def has_overlap(self, employee_id: str, start: date, end: date) -> bool:
        with self.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM leave_requests
                    WHERE employee_id = %s
                      AND status IN ('pending_manager_review', 'approved')
                      AND start_date <= %s AND end_date >= %s
                ) AS overlaps
                """,
                (employee_id, end, start),
            ).fetchone()
        return bool(row["overlaps"])

    def save_proposal(self, employee_id: str, proposal: ActionProposal) -> None:
        with self.pool.connection() as connection:
            connection.execute(
                """
                INSERT INTO action_proposals
                    (proposal_id, employee_id, action_type, leave_type, start_date, end_date,
                     business_days, reason, validation_summary, expires_at, requires_attachment)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (proposal_id) DO UPDATE SET
                    employee_id = EXCLUDED.employee_id,
                    action_type = EXCLUDED.action_type,
                    leave_type = EXCLUDED.leave_type,
                    start_date = EXCLUDED.start_date,
                    end_date = EXCLUDED.end_date,
                    business_days = EXCLUDED.business_days,
                    reason = EXCLUDED.reason,
                    validation_summary = EXCLUDED.validation_summary,
                    expires_at = EXCLUDED.expires_at,
                    requires_attachment = EXCLUDED.requires_attachment
                """,
                (
                    proposal.proposal_id,
                    employee_id,
                    proposal.action_type,
                    proposal.leave_type,
                    proposal.start_date,
                    proposal.end_date,
                    proposal.business_days,
                    proposal.reason,
                    proposal.validation_summary,
                    proposal.expires_at,
                    proposal.requires_attachment,
                ),
            )

    def get_proposal(self, proposal_id: str) -> tuple[str, ActionProposal] | None:
        with self.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT employee_id, proposal_id, action_type, leave_type, start_date, end_date,
                       business_days, reason, validation_summary, expires_at,
                       COALESCE(requires_attachment, FALSE) AS requires_attachment
                FROM action_proposals
                WHERE proposal_id = %s
                """,
                (proposal_id,),
            ).fetchone()
        if not row:
            return None
        owner = row.pop("employee_id")
        return owner, ActionProposal(**row)

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

    def list_leave_requests(self, employee_id: str) -> list[LeaveRequestView]:
        with self.pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT r.request_id, r.leave_type, r.start_date, r.end_date, r.business_days, r.status, r.created_at,
                       (a.request_id IS NOT NULL) AS has_attachment,
                       a.filename AS attachment_filename,
                       a.content_type AS attachment_content_type,
                       a.file_size_bytes AS attachment_size_bytes,
                       a.uploaded_at AS attachment_uploaded_at
                FROM leave_requests r
                LEFT JOIN leave_attachments a ON a.request_id = r.request_id
                WHERE r.employee_id = %s
                ORDER BY r.created_at, r.request_id
                """,
                (employee_id,),
            ).fetchall()
        return [LeaveRequestView(**row) for row in rows]

    def list_team_leave_requests(self, manager_id: str, include_all_departments: bool = False) -> list[LeaveRequestView]:
        with self.pool.connection() as connection:
            if include_all_departments:
                rows = connection.execute(
                    """
                    SELECT r.request_id, r.employee_id, e.display_name AS employee_name,
                           r.leave_type, r.start_date, r.end_date, r.business_days,
                           r.status, r.reviewed_by, r.review_note, r.reviewed_at, r.created_at,
                           (a.request_id IS NOT NULL) AS has_attachment,
                           a.filename AS attachment_filename,
                           a.content_type AS attachment_content_type,
                           a.file_size_bytes AS attachment_size_bytes,
                           a.uploaded_at AS attachment_uploaded_at
                    FROM leave_requests r
                    JOIN employees e ON e.employee_id = r.employee_id
                    LEFT JOIN leave_attachments a ON a.request_id = r.request_id
                    ORDER BY r.created_at DESC, r.request_id
                    """
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT r.request_id, r.employee_id, e.display_name AS employee_name,
                           r.leave_type, r.start_date, r.end_date, r.business_days,
                           r.status, r.reviewed_by, r.review_note, r.reviewed_at, r.created_at,
                           (a.request_id IS NOT NULL) AS has_attachment,
                           a.filename AS attachment_filename,
                           a.content_type AS attachment_content_type,
                           a.file_size_bytes AS attachment_size_bytes,
                           a.uploaded_at AS attachment_uploaded_at
                    FROM leave_requests r
                    JOIN employees e ON e.employee_id = r.employee_id
                    LEFT JOIN leave_attachments a ON a.request_id = r.request_id
                    WHERE e.manager_id = %s
                    ORDER BY r.created_at DESC, r.request_id
                    """,
                    (manager_id,),
                ).fetchall()
        return [LeaveRequestView(**row) for row in rows]

    def review_leave_request(
        self,
        reviewer_id: str,
        request_id: str,
        decision: str,
        review_note: str,
        is_admin: bool = False,
    ) -> ManagerReviewResult:
        with self.pool.connection() as connection:
            with connection.transaction():
                row = connection.execute(
                    """
                    SELECT r.request_id, r.employee_id, e.manager_id, r.leave_type,
                           r.business_days, r.status
                    FROM leave_requests r
                    JOIN employees e ON e.employee_id = r.employee_id
                    WHERE r.request_id = %s
                    FOR UPDATE OF r
                    """,
                    (request_id,),
                ).fetchone()
                if not row:
                    raise KeyError("leave request not found")

                if row["employee_id"] == reviewer_id:
                    raise ConflictError("manager cannot review own leave request")

                if not is_admin and row["manager_id"] != reviewer_id:
                    raise KeyError("leave request not found in manager team")

                if row["status"] != "pending_manager_review":
                    raise ConflictError(f"leave request already finalized as {row['status']}")

                if decision == "approved":
                    bal = connection.execute(
                        """
                        SELECT available_days
                        FROM leave_balances
                        WHERE employee_id = %s AND leave_type = %s
                        FOR UPDATE
                        """,
                        (row["employee_id"], row["leave_type"]),
                    ).fetchone()
                    if not bal or int(bal["available_days"]) < int(row["business_days"]):
                        raise ConflictError("insufficient balance")
                    connection.execute(
                        """
                        UPDATE leave_balances
                        SET available_days = available_days - %s
                        WHERE employee_id = %s AND leave_type = %s
                        """,
                        (row["business_days"], row["employee_id"], row["leave_type"]),
                    )

                clean_note = redact(review_note)
                reviewed_at = datetime.now(timezone.utc)
                audit_id = f"audit-review-{request_id}-{uuid4().hex[:8]}"

                connection.execute(
                    """
                    UPDATE leave_requests
                    SET status = %s, reviewed_by = %s, review_note = %s, reviewed_at = %s
                    WHERE request_id = %s
                    """,
                    (decision, reviewer_id, clean_note, reviewed_at, request_id),
                )
                connection.execute(
                    """
                    INSERT INTO approval_audit_logs
                        (audit_id, request_id, reviewer_id, previous_status, new_status, review_note, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (audit_id, request_id, reviewer_id, "pending_manager_review", decision, clean_note, reviewed_at),
                )
        return ManagerReviewResult(
            request_id=request_id,
            employee_id=row["employee_id"],
            status=decision,
            reviewed_by=reviewer_id,
            review_note=clean_note,
            reviewed_at=reviewed_at,
            audit_reference=audit_id,
        )

    def save_leave_attachment(
        self,
        employee_id: str,
        request_id: str,
        filename: str,
        content_type: str,
        file_bytes: bytes,
    ) -> LeaveAttachmentView:
        with self.pool.connection() as connection:
            with connection.transaction():
                row = connection.execute(
                    """
                    SELECT leave_type, status
                    FROM leave_requests
                    WHERE request_id = %s AND employee_id = %s
                    FOR UPDATE
                    """,
                    (request_id, employee_id),
                ).fetchone()
                if not row:
                    raise KeyError("leave request not found")
                if row["leave_type"] != "sick":
                    raise ConflictError("attachment is only supported for sick leave requests")
                if row["status"] != "pending_manager_review":
                    raise ConflictError("cannot attach document to finalized leave request")

                uploaded_at = datetime.now(timezone.utc)
                connection.execute(
                    """
                    INSERT INTO leave_attachments (
                        request_id, employee_id, filename, content_type, file_size_bytes, file_bytes, uploaded_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (request_id) DO UPDATE SET
                        filename = EXCLUDED.filename,
                        content_type = EXCLUDED.content_type,
                        file_size_bytes = EXCLUDED.file_size_bytes,
                        file_bytes = EXCLUDED.file_bytes,
                        uploaded_at = EXCLUDED.uploaded_at
                    """,
                    (
                        request_id,
                        employee_id,
                        filename,
                        content_type,
                        len(file_bytes),
                        file_bytes,
                        uploaded_at,
                    ),
                )
                return LeaveAttachmentView(
                    request_id=request_id,
                    employee_id=employee_id,
                    filename=filename,
                    content_type=content_type,
                    file_size_bytes=len(file_bytes),
                    content_base64=base64.b64encode(file_bytes).decode("ascii"),
                    uploaded_at=uploaded_at,
                )

    def get_leave_attachment(
        self,
        requester: AuthContext,
        request_id: str,
    ) -> LeaveAttachmentView:
        with self.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT a.request_id, a.employee_id, a.filename, a.content_type,
                       a.file_size_bytes, a.file_bytes, a.uploaded_at,
                       e.manager_id
                FROM leave_attachments a
                JOIN employees e ON e.employee_id = a.employee_id
                WHERE a.request_id = %s
                """,
                (request_id,),
            ).fetchone()
            if not row:
                raise KeyError("attachment not found")

            is_owner = requester.employee_id == row["employee_id"]
            is_admin = requester.role == "monitoring_admin"
            is_manager = requester.role == "manager" and row["manager_id"] == requester.employee_id
            if not (is_owner or is_admin or is_manager):
                raise PermissionError("not authorized to view this attachment")

            raw_bytes = bytes(row["file_bytes"])
            return LeaveAttachmentView(
                request_id=row["request_id"],
                employee_id=row["employee_id"],
                filename=row["filename"],
                content_type=row["content_type"],
                file_size_bytes=row["file_size_bytes"],
                content_base64=base64.b64encode(raw_bytes).decode("ascii"),
                uploaded_at=row["uploaded_at"],
            )

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

    def save_trace(self, trace: dict[str, Any]) -> None:
        trace_id = str(trace["trace_id"])
        employee_id = str(trace["employee_id"])
        with self.pool.connection() as connection:
            connection.execute(
                """
                INSERT INTO traces (trace_id, employee_id, payload)
                VALUES (%s, %s, %s)
                ON CONFLICT (trace_id) DO UPDATE SET
                    employee_id = EXCLUDED.employee_id,
                    payload = EXCLUDED.payload
                """,
                (trace_id, employee_id, Jsonb(redact_trace(trace))),
            )

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        with self.pool.connection() as connection:
            row = connection.execute(
                "SELECT payload FROM traces WHERE trace_id = %s",
                (trace_id,),
            ).fetchone()
        return deepcopy(row["payload"]) if row else None

    def monitoring_summary(self) -> dict[str, Any]:
        with self.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_traces,
                    COUNT(*) FILTER (WHERE COALESCE(payload->>'error', '') <> '') AS error_count,
                    COUNT(*) FILTER (WHERE payload->>'outcome' = 'abstained') AS abstain_count,
                    COUNT(*) FILTER (WHERE COALESCE(payload->>'blocked_reason', '') <> '') AS blocked_count,
                    COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY NULLIF(payload->'usage'->>'latency_ms', '')::double precision), 0.0) AS p95_latency_ms,
                    COALESCE(SUM(jsonb_array_length(CASE WHEN jsonb_typeof(payload->'tool_calls') = 'array' THEN payload->'tool_calls' ELSE '[]'::jsonb END)), 0) AS tool_calls
                FROM traces
                """
            ).fetchone()
        total = int(row["total_traces"])
        errors = int(row["error_count"])
        abstains = int(row["abstain_count"]) if row["abstain_count"] is not None else 0
        blocked = int(row["blocked_count"]) if row["blocked_count"] is not None else 0
        p95_latency = float(row["p95_latency_ms"]) if row["p95_latency_ms"] is not None else 0.0
        tool_calls = int(row["tool_calls"]) if row["tool_calls"] is not None else 0
        return {
            "run_count": total,
            "total_traces": total,
            "error_count": errors,
            "error_rate": errors / total if total else 0.0,
            "abstain_count": abstains,
            "abstain_rate": abstains / total if total else 0.0,
            "blocked_count": blocked,
            "p95_latency_ms": p95_latency,
            "tool_calls": tool_calls,
        }

    def get_hr_analytics(self, auth: AuthContext, metric_focus: str = "overview", low_balance_threshold: int = 3) -> dict[str, Any]:
        if auth.role not in ("manager", "monitoring_admin"):
            raise PermissionError("analytics requires manager or admin role")

        is_admin = auth.role == "monitoring_admin"
        scope = "organization" if is_admin else "team"

        with self.pool.connection() as connection:
            if is_admin:
                emp_rows = connection.execute(
                    "SELECT employee_id, display_name, department FROM employees WHERE role != 'monitoring_admin' ORDER BY employee_id"
                ).fetchall()
            else:
                emp_rows = connection.execute(
                    "SELECT employee_id, display_name, department FROM employees WHERE manager_id = %s ORDER BY employee_id",
                    (auth.employee_id,),
                ).fetchall()

            scoped_emp_ids = [row["employee_id"] for row in emp_rows]
            team_size = len(scoped_emp_ids)

            requests_by_status = {
                "pending_manager_review": 0,
                "approved": 0,
                "rejected": 0,
                "cancelled": 0,
            }
            days_by_leave_type = {
                "annual": 0,
                "sick": 0,
                "parental": 0,
            }
            department_breakdown: dict[str, dict[str, int]] = {}
            for row in emp_rows:
                dept = row["department"] or "Unknown"
                if dept not in department_breakdown:
                    department_breakdown[dept] = {"employee_count": 0, "active_leave_days": 0}
                department_breakdown[dept]["employee_count"] += 1

            if scoped_emp_ids:
                req_rows = connection.execute(
                    """
                    SELECT r.employee_id, r.leave_type, r.business_days, r.status, e.department
                    FROM leave_requests r
                    JOIN employees e ON e.employee_id = r.employee_id
                    WHERE r.employee_id = ANY(%s)
                    """,
                    (scoped_emp_ids,),
                ).fetchall()
                for req in req_rows:
                    st_val = req["status"]
                    if st_val in requests_by_status:
                        requests_by_status[st_val] += 1
                    else:
                        requests_by_status[st_val] = 1

                    if st_val in ("pending_manager_review", "approved"):
                        l_type = req["leave_type"]
                        days_by_leave_type[l_type] = days_by_leave_type.get(l_type, 0) + int(req["business_days"])
                        dept = req["department"] or "Unknown"
                        if dept in department_breakdown:
                            department_breakdown[dept]["active_leave_days"] += int(req["business_days"])

                bal_rows = connection.execute(
                    """
                    SELECT
                        e.employee_id,
                        e.display_name,
                        GREATEST(
                            0,
                            b.available_days - COALESCE((
                                SELECT SUM(r.business_days)::int
                                FROM leave_requests r
                                WHERE r.employee_id = b.employee_id
                                  AND r.leave_type = 'annual'
                                  AND r.status = 'pending_manager_review'
                            ), 0)
                        ) AS annual_remaining
                    FROM employees e
                    JOIN leave_balances b ON b.employee_id = e.employee_id AND b.leave_type = 'annual'
                    WHERE e.employee_id = ANY(%s)
                    ORDER BY annual_remaining, e.employee_id
                    """,
                    (scoped_emp_ids,),
                ).fetchall()
                low_balance_employees = [
                    {
                        "employee_id": row["employee_id"],
                        "display_name": row["display_name"],
                        "annual_remaining": int(row["annual_remaining"]),
                    }
                    for row in bal_rows
                    if int(row["annual_remaining"]) <= low_balance_threshold
                ]
            else:
                low_balance_employees = []

            analytics: dict[str, Any] = {
                "scope": scope,
                "metric_focus": metric_focus,
                "low_balance_threshold": low_balance_threshold,
                "team_size": team_size,
                "requests_by_status": requests_by_status,
                "days_by_leave_type": days_by_leave_type,
                "low_balance_employees": low_balance_employees,
                "department_breakdown": department_breakdown,
            }

            if is_admin:
                ticket_rows = connection.execute(
                    "SELECT category, COUNT(*) AS count FROM tickets GROUP BY category"
                ).fetchall()
                analytics["tickets_by_category"] = {
                    row["category"]: int(row["count"]) for row in ticket_rows
                }
                analytics["ai_operations"] = self.monitoring_summary()

            return analytics
