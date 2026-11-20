"""Repository contracts. Implement MemoryRepository first, then PostgreSQL/pgvector."""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import math
from math import sqrt
import re
import secrets
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from .contracts import (
    ActionProposal,
    ActionResult,
    AuthContext,
    LeaveAttachmentView,
    LeaveBalance,
    LeaveRequestView,
    LoginResponse,
    PolicyChunk,
    ProposalAttachmentView,
)
from .security import hash_password, redact, token_hash, verify_password


class Repository(Protocol):
    def health(self) -> bool: ...
    def authenticate(self, token: str) -> AuthContext | None: ...
    def authenticate_password(self, username: str, password: str) -> LoginResponse | None: ...
    def create_demo_session(self, employee_id: str, ttl_hours: int = 8) -> LoginResponse: ...
    def list_personas(self, allow_demo_session: bool = False) -> list[dict[str, Any]]: ...
    def lexical_search(self, query: str, limit: int, as_of: date | None = None) -> list[PolicyChunk]: ...
    def vector_search(self, embedding: list[float], limit: int, as_of: date | None = None) -> list[PolicyChunk]: ...
    def get_policy_document_text(self, document_id: str, as_of: date | None = None) -> str | None: ...
    def policy_fingerprint(self, as_of: date | None = None) -> str: ...
    def list_evaluation_cases(self) -> list[dict[str, Any]]: ...
    def get_balances(self, employee_id: str, as_of: date | None = None) -> list[LeaveBalance]: ...
    def has_overlap(self, employee_id: str, start: date, end: date) -> bool: ...
    def save_proposal(self, employee_id: str, proposal: ActionProposal) -> None: ...
    def get_proposal(self, proposal_id: str) -> tuple[str, ActionProposal] | None: ...
    def save_proposal_attachment(
        self,
        employee_id: str,
        proposal_id: str,
        filename: str,
        content_type: str,
        file_bytes: bytes,
    ) -> ProposalAttachmentView: ...
    def confirm_proposal(
        self,
        employee_id: str,
        proposal_id: str,
        idempotency_key: str,
        today: date | None = None,
        enforce_attachment: bool = False,
    ) -> ActionResult: ...
    def list_leave_requests(self, employee_id: str) -> list[LeaveRequestView]: ...
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
    def create_ticket(
        self,
        employee_id: str,
        category: str,
        summary: str,
        ticket_id: str | None = None,
    ) -> str: ...
    def list_tickets(
        self,
        employee_id: str | None = None,
        manager_id: str | None = None,
    ) -> list[dict[str, Any]]: ...
    def update_ticket_status(
        self,
        ticket_id: str,
        status: str,
        admin_id: str,
        allowed_manager_id: str | None = None,
    ) -> dict[str, Any]: ...
    def save_trace(self, trace: dict[str, Any]) -> None: ...
    def get_trace(self, trace_id: str) -> dict[str, Any] | None: ...
    def monitoring_summary(self) -> dict[str, Any]: ...
    def list_monitoring_rules(self) -> list[dict[str, Any]]: ...
    def get_hr_analytics(self, auth: AuthContext, metric_focus: str = "overview", low_balance_threshold: int = 3) -> dict[str, Any]: ...


class ConflictError(RuntimeError):
    pass


def _version_key(version: str) -> tuple[tuple[int, int | str], ...]:
    parts: list[tuple[int, int | str]] = []
    for token in re.findall(r"\d+|[a-zA-Z]+", str(version)):
        if token.isdigit():
            parts.append((1, int(token)))
        else:
            parts.append((0, token.casefold()))
    return tuple(parts)


def _active_latest_chunks(chunks: list[PolicyChunk], active_today: date) -> list[PolicyChunk]:
    active = [chunk for chunk in chunks if chunk.effective_date <= active_today]
    if not active:
        return []
    latest_versions: dict[str, tuple[tuple[tuple[int, int | str], ...], date, str]] = {}
    for chunk in active:
        key = (_version_key(chunk.version), chunk.effective_date, chunk.version)
        current = latest_versions.get(chunk.document_id)
        if current is None or key > current:
            latest_versions[chunk.document_id] = key
    return [
        chunk
        for chunk in active
        if chunk.version == latest_versions[chunk.document_id][2]
    ]


def _default_memory_employees() -> list[dict[str, Any]]:
    return [
        {
            "employee_id": "EMP-001",
            "username": "alya",
            "password": "Password#123",
            "display_name": "Alya Pratama",
            "role": "employee",
            "department": "Engineering",
            "manager_id": None,
            "token_hash": token_hash("token-alya"),
            "balances": {"annual": 8, "sick": 10, "parental": 60},
        },
        {
            "employee_id": "EMP-002",
            "username": "bima",
            "password": "Password#123",
            "display_name": "Bima Santoso",
            "role": "employee",
            "department": "Engineering",
            "manager_id": None,
            "token_hash": token_hash("token-bima"),
            "balances": {"annual": 3, "sick": 10, "parental": 60},
        },
        {
            "employee_id": "ADM-001",
            "username": "admin",
            "password": "Password#123",
            "display_name": "Monitoring Admin",
            "role": "monitoring_admin",
            "department": "HR & People Ops",
            "manager_id": None,
            "token_hash": token_hash("token-admin"),
            "balances": {},
        },
    ]


def _default_monitoring_rules() -> list[dict[str, Any]]:
    return [
        {
            "rule_id": "agent-error-spike",
            "metric": "error_rate",
            "operator": "gt",
            "threshold": 0.2,
            "minimum_samples": 5,
            "owner": "AI Platform",
            "response": "Inspect redacted traces and provider health; disable mutating tools if errors persist.",
        },
        {
            "rule_id": "agent-latency-p95",
            "metric": "p95_latency_ms",
            "operator": "gt",
            "threshold": 8000.0,
            "minimum_samples": 5,
            "owner": "AI Platform",
            "response": "Inspect provider latency, retrieval cache, and database query timing.",
        },
    ]


class MemoryRepository:
    def __init__(self, employees: list[dict[str, Any]] | None = None) -> None:
        self._lock = RLock()
        self.chunks: list[PolicyChunk] = []
        self.identities: dict[str, tuple[AuthContext, str]] = {}
        self.credentials: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, tuple[str, datetime]] = {}
        self.balances: dict[str, list[LeaveBalance]] = {}
        today = date.today()
        if employees is None:
            employee_rows = _default_memory_employees()
            db_rules = _default_monitoring_rules()
        else:
            employee_rows = employees
            db_rules = _default_monitoring_rules()
        for emp in employee_rows:
            emp_id = emp["employee_id"]
            auth_ctx = AuthContext(
                employee_id=emp_id,
                display_name=emp["display_name"],
                role=emp.get("role", "employee"),
                department=emp.get("department"),
                manager_id=emp.get("manager_id"),
            )
            stored_hash = emp.get("token_hash")
            if not stored_hash:
                raw_token = emp.get("token") or secrets.token_hex(16)
                stored_hash = token_hash(raw_token)
            self.identities[emp_id] = (auth_ctx, stored_hash)
            username = (emp.get("username") or emp_id).casefold()
            pwd_hash = emp.get("password_hash") or hash_password(
                emp.get("password", "Password#123")
            )
            self.credentials[emp_id] = {
                "username": username,
                "password_hash": pwd_hash,
                "context": auth_ctx,
            }
            self.balances[emp_id] = [
                LeaveBalance(leave_type=leave_type, available_days=days, as_of_date=today)
                for leave_type, days in emp.get("balances", {}).items()
            ]
        self.proposals: dict[str, tuple[str, ActionProposal]] = {}
        self.proposal_attachments: dict[str, dict[str, Any]] = {}
        self.idempotency_keys: dict[str, str] = {}
        self.embeddings: dict[str, list[float]] = {}
        self.requests: dict[str, list[LeaveRequestView]] = {}
        self.attachments: dict[str, dict[str, Any]] = {}
        self.tickets: dict[str, dict[str, str | None]] = {}
        self.monitoring_rules: list[dict[str, Any]] = deepcopy(db_rules)
        self.evaluation_cases: list[dict[str, Any]] = []
        self.traces: dict[str, dict[str, Any]] = {}

    def health(self) -> bool:
        return True

    def authenticate(self, token: str) -> AuthContext | None:
        if not token:
            return None
        hashed = token_hash(token)
        with self._lock:
            for context, stored_hash in self.identities.values():
                if stored_hash == hashed:
                    return context.model_copy(deep=True)
            session = self.sessions.get(hashed)
            if session is not None:
                emp_id, expires_at = session
                if expires_at > datetime.now(timezone.utc):
                    identity = self.identities.get(emp_id)
                    if identity is not None:
                        return identity[0].model_copy(deep=True)
                else:
                    self.sessions.pop(hashed, None)
        return None

    def authenticate_password(self, username: str, password: str, ttl_hours: int = 8) -> LoginResponse | None:
        ident = username.strip().casefold()
        with self._lock:
            for emp_id, rec in self.credentials.items():
                valid_idents = {emp_id.casefold(), rec["username"]}
                if ident in valid_idents:
                    if verify_password(password, rec["password_hash"]):
                        token = f"sess_{secrets.token_hex(24)}"
                        expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
                        self.sessions[token_hash(token)] = (emp_id, expires_at)
                        return LoginResponse(
                            access_token=token,
                            profile=rec["context"].model_copy(deep=True),
                        )
                    return None
        return None

    def create_demo_session(self, employee_id: str, ttl_hours: int = 8) -> LoginResponse:
        with self._lock:
            identity = self.identities.get(employee_id)
            if identity is None:
                raise KeyError("employee not found")
            ctx, _ = identity
            if ctx.role != "employee":
                raise PermissionError("demo session is only allowed for employee role")
            token = f"sess_{secrets.token_hex(24)}"
            expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
            self.sessions[token_hash(token)] = (ctx.employee_id, expires_at)
            return LoginResponse(
                access_token=token,
                profile=ctx.model_copy(deep=True),
            )

    def list_personas(self, allow_demo_session: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            result: list[dict[str, Any]] = []
            for emp_id in sorted(self.credentials):
                rec = self.credentials[emp_id]
                ctx: AuthContext = rec["context"]
                result.append({
                    "employee_id": ctx.employee_id,
                    "username": rec["username"],
                    "display_name": ctx.display_name,
                    "role": ctx.role,
                    "department": ctx.department or "Engineering",
                    "requires_password": (not allow_demo_session) or (ctx.role != "employee"),
                })
            return result

    def lexical_search(self, query: str, limit: int, as_of: date | None = None) -> list[PolicyChunk]:
        stopwords = {"berapa", "apakah", "bagaimana", "kapan", "siapa", "yang", "dan", "di", "ke", "dari", "untuk", "pada", "saya", "aku", "bisa", "boleh", "per"}
        raw_terms = [t for t in re.findall(r"[a-z0-9]+", query.casefold()) if len(t) >= 2]
        terms = set(t for t in raw_terms if t not in stopwords) or set(raw_terms)
        if not terms:
            return []
        active_today = as_of or date.today()
        with self._lock:
            active_chunks = _active_latest_chunks(self.chunks, active_today)
            ranked: list[tuple[int, PolicyChunk]] = []
            for chunk in active_chunks:
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

    def vector_search(self, embedding: list[float], limit: int, as_of: date | None = None) -> list[PolicyChunk]:
        if not embedding:
            return []
        active_today = as_of or date.today()
        with self._lock:
            active_chunks = _active_latest_chunks(self.chunks, active_today)
            ranked: list[tuple[float, PolicyChunk]] = []
            for chunk in active_chunks:
                vector = self.embeddings.get(chunk.chunk_id)
                if not isinstance(vector, list) or len(vector) != len(embedding):
                    continue
                norm = sqrt(sum(value * value for value in embedding) * sum(value * value for value in vector))
                similarity = sum(left * right for left, right in zip(embedding, vector)) / norm if norm else 0.0
                ranked.append((similarity, chunk))
            ranked.sort(key=lambda item: (-item[0], item[1].chunk_id))
            return [chunk.model_copy(update={"score": score}) for score, chunk in ranked[:limit]]

    def get_policy_document_text(self, document_id: str, as_of: date | None = None) -> str | None:
        active_today = as_of or date.today()
        with self._lock:
            doc_chunks = [c for c in self.chunks if c.document_id == document_id]
            active_chunks = _active_latest_chunks(doc_chunks, active_today)
            if not active_chunks:
                return None
            active_chunks.sort(key=lambda c: c.chunk_id)
            parts = [c.content.strip() for c in active_chunks if c.content and c.content.strip()]
            return "\n\n".join(parts) if parts else None

    def policy_fingerprint(self, as_of: date | None = None) -> str:
        active_today = as_of or date.today()
        with self._lock:
            active_chunks = _active_latest_chunks(self.chunks, active_today)
            items = sorted((c.chunk_id, c.version, c.content) for c in active_chunks)
        digest = hashlib.sha256()
        for chunk_id, version, content in items:
            digest.update(f"{chunk_id}\0{version}\0{content}\n".encode("utf-8"))
        return digest.hexdigest()[:12]

    def list_evaluation_cases(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self.evaluation_cases)

    def get_balances(self, employee_id: str, as_of: date | None = None) -> list[LeaveBalance]:
        effective_date = as_of or date.today()
        with self._lock:
            pending_by_type: dict[str, int] = {}
            for req in self.requests.get(employee_id, []):
                if req.status == "pending_manager_review":
                    pending_by_type[req.leave_type] = pending_by_type.get(req.leave_type, 0) + req.business_days
            result: list[LeaveBalance] = []
            for balance in self.balances.get(employee_id, []):
                reserved = pending_by_type.get(balance.leave_type, 0)
                effective = max(0, balance.available_days - reserved)
                result.append(balance.model_copy(update={"available_days": effective, "as_of_date": effective_date}, deep=True))
            return result

    def has_overlap(self, employee_id: str, start: date, end: date) -> bool:
        with self._lock:
            return any(
                request.start_date <= end and request.end_date >= start
                for request in self.requests.get(employee_id, [])
                if request.status in ("pending_manager_review", "approved")
            )

    def save_proposal(self, employee_id: str, proposal: ActionProposal) -> None:
        with self._lock:
            existing = self.proposals.get(proposal.proposal_id)
            if existing is not None and existing[0] != employee_id:
                raise ConflictError("proposal_id belongs to another employee")
            self.proposals[proposal.proposal_id] = (employee_id, proposal.model_copy(deep=True))

    def get_proposal(self, proposal_id: str) -> tuple[str, ActionProposal] | None:
        with self._lock:
            item = self.proposals.get(proposal_id)
            if item is None:
                return None
            owner, proposal = item
            return owner, proposal.model_copy(deep=True)

    def save_proposal_attachment(
        self,
        employee_id: str,
        proposal_id: str,
        filename: str,
        content_type: str,
        file_bytes: bytes,
    ) -> ProposalAttachmentView:
        with self._lock:
            item = self.proposals.get(proposal_id)
            if item is None or item[0] != employee_id:
                raise KeyError("proposal not found")
            _, proposal = item
            expiry = proposal.expires_at
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry <= datetime.now(timezone.utc):
                raise ConflictError("proposal expired")
            already_confirmed = any(
                req.request_id == proposal_id for req in self.requests.get(employee_id, [])
            )
            if already_confirmed:
                raise ConflictError("proposal already confirmed")
            if proposal.leave_type != "sick":
                raise ConflictError("attachment is only supported for sick leave proposals")

            uploaded_at = datetime.now(timezone.utc)
            self.proposal_attachments[proposal_id] = {
                "proposal_id": proposal_id,
                "employee_id": employee_id,
                "filename": filename,
                "content_type": content_type,
                "file_size_bytes": len(file_bytes),
                "file_bytes": file_bytes,
                "uploaded_at": uploaded_at,
            }
            return ProposalAttachmentView(
                proposal_id=proposal_id,
                employee_id=employee_id,
                filename=filename,
                content_type=content_type,
                file_size_bytes=len(file_bytes),
                uploaded_at=uploaded_at,
            )

    def confirm_proposal(
        self,
        employee_id: str,
        proposal_id: str,
        idempotency_key: str,
        today: date | None = None,
        enforce_attachment: bool = False,
    ) -> ActionResult:
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

            # 4. Re-validasi tanggal masa lalu
            if today is not None and proposal.start_date < today:
                raise ConflictError("proposal dates are in the past")

            # 5. Re-validasi lampiran wajib (hanya dipaksa bila enforce_attachment=True, e.g. dari web SPA)
            if (
                enforce_attachment
                and proposal.requires_attachment
                and proposal_id not in self.proposal_attachments
                and proposal_id not in self.attachments
            ):
                raise ConflictError("dokumen pendukung surat dokter wajib diunggah sebelum konfirmasi")

            # 6. Re-validasi overlap terhadap request aktif
            if self.has_overlap(owner, proposal.start_date, proposal.end_date):
                raise ConflictError("leave dates overlap with an existing request")

            # 7. Re-validasi saldo efektif
            balances = self.get_balances(owner, as_of=today)
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

            staged_att = self.proposal_attachments.pop(proposal_id, None)
            if staged_att is not None and proposal_id not in self.attachments:
                self.attachments[proposal_id] = {
                    "request_id": request.request_id,
                    "employee_id": staged_att["employee_id"],
                    "filename": staged_att["filename"],
                    "content_type": staged_att["content_type"],
                    "file_size_bytes": staged_att["file_size_bytes"],
                    "file_bytes": staged_att["file_bytes"],
                    "uploaded_at": staged_att["uploaded_at"],
                }

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
        with self._lock:
            return [
                self._enrich_with_attachment_meta(request.model_copy(deep=True))
                for request in self.requests.get(employee_id, [])
            ]

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
            if requester.employee_id != owner_id:
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

    def create_ticket(
        self,
        employee_id: str,
        category: str,
        summary: str,
        ticket_id: str | None = None,
    ) -> str:
        clean_summary = redact(summary)
        with self._lock:
            for existing_id, item in self.tickets.items():
                if (
                    item.get("employee_id") == employee_id
                    and item.get("category") == category
                    and item.get("summary") == clean_summary
                    and item.get("status") != "done"
                ):
                    return existing_id
            active_ticket_id = ticket_id or f"T-{uuid4().hex[:12]}"
            self.tickets[active_ticket_id] = {
                "ticket_id": active_ticket_id,
                "employee_id": employee_id,
                "category": category,
                "summary": clean_summary,
                "status": "pending",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": None,
                "updated_by": None,
            }
            return active_ticket_id

    def list_tickets(
        self,
        employee_id: str | None = None,
        manager_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            results = []
            for t_id, t in self.tickets.items():
                emp_id = t.get("employee_id") or ""
                if employee_id and emp_id != employee_id:
                    continue
                if manager_id is not None:
                    owner_ctx = self.identities.get(emp_id, (None, None))[0]
                    if emp_id != manager_id and (owner_ctx is None or owner_ctx.manager_id != manager_id):
                        continue
                emp_name = None
                emp_dept = None
                if emp_id in self.credentials:
                    emp_name = self.credentials[emp_id]["context"].display_name
                    emp_dept = self.credentials[emp_id]["context"].department
                results.append({
                    "ticket_id": t_id,
                    "employee_id": emp_id,
                    "employee_name": emp_name or emp_id,
                    "department": emp_dept or "General",
                    "category": t.get("category") or "policy_question",
                    "summary": t.get("summary") or "",
                    "status": t.get("status") or "pending",
                    "created_at": t.get("created_at") or datetime.now(timezone.utc).isoformat(),
                    "updated_at": t.get("updated_at"),
                    "updated_by": t.get("updated_by"),
                })
            results.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)
            return results

    def update_ticket_status(
        self,
        ticket_id: str,
        status: str,
        admin_id: str,
        allowed_manager_id: str | None = None,
    ) -> dict[str, Any]:
        if status not in ("pending", "on progress", "done"):
            raise ValueError(f"Status tidak valid: {status}")
        with self._lock:
            if ticket_id not in self.tickets:
                raise KeyError(f"Tiket {ticket_id} tidak ditemukan")
            t = self.tickets[ticket_id]
            emp_id = t.get("employee_id") or ""
            if allowed_manager_id is not None:
                owner_ctx = self.identities.get(emp_id, (None, None))[0]
                if owner_ctx is None or owner_ctx.manager_id != allowed_manager_id:
                    raise PermissionError("not authorized to update ticket outside your team")
            t["status"] = status
            t["updated_at"] = datetime.now(timezone.utc).isoformat()
            t["updated_by"] = admin_id
            emp_name = None
            emp_dept = None
            if emp_id in self.credentials:
                emp_name = self.credentials[emp_id]["context"].display_name
                emp_dept = self.credentials[emp_id]["context"].department
            return {
                "ticket_id": ticket_id,
                "employee_id": emp_id,
                "employee_name": emp_name or emp_id,
                "department": emp_dept or "General",
                "category": t.get("category") or "policy_question",
                "summary": t.get("summary") or "",
                "status": t.get("status") or "pending",
                "created_at": t.get("created_at") or datetime.now(timezone.utc).isoformat(),
                "updated_at": t.get("updated_at"),
                "updated_by": t.get("updated_by"),
            }

    def save_trace(self, trace: dict[str, Any]) -> None:
        with self._lock:
            trace_id = str(trace["trace_id"])
            self.traces[trace_id] = redact_trace(trace)

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        with self._lock:
            trace = self.traces.get(trace_id)
            return deepcopy(trace) if trace is not None else None

    def monitoring_summary(self) -> dict[str, Any]:
        with self._lock:
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
            sorted(latencies)[min(len(latencies) - 1, max(0, math.ceil(len(latencies) * 0.95) - 1))]
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

    def list_monitoring_rules(self) -> list[dict[str, Any]]:
        # In-memory evaluation rules for offline tests
        with self._lock:
            return deepcopy(self.monitoring_rules)

    def get_hr_analytics(self, auth: AuthContext, metric_focus: str = "overview", low_balance_threshold: int = 3) -> dict[str, Any]:
        if auth.role != "monitoring_admin":
            raise PermissionError("analytics requires monitoring_admin role")

        with self._lock:
            scoped_employees = [
                ctx for ctx, _ in self.identities.values() if ctx.role != "monitoring_admin"
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

            low_balance_employee_count = 0
            for ctx in scoped_employees:
                balances = self.get_balances(ctx.employee_id)
                annual_bal = next((b.available_days for b in balances if b.leave_type == "annual"), 0)
                if annual_bal <= low_balance_threshold:
                    low_balance_employee_count += 1

            tickets_by_category: dict[str, int] = {}
            for ticket in self.tickets.values():
                cat = ticket.get("category") or "unknown"
                tickets_by_category[cat] = tickets_by_category.get(cat, 0) + 1

            return {
                "scope": "organization",
                "metric_focus": metric_focus,
                "low_balance_threshold": low_balance_threshold,
                "team_size": team_size,
                "requests_by_status": requests_by_status,
                "days_by_leave_type": days_by_leave_type,
                "low_balance_employee_count": low_balance_employee_count,
                "low_balance_employees": [],
                "department_breakdown": department_breakdown,
                "tickets_by_category": tickets_by_category,
                "ai_operations": self.monitoring_summary(),
            }


def redact_trace(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return redact_trace(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {key: redact_trace(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact_trace(item) for item in value]
    return redact(str(value))


class PostgresRepository:
    def __init__(self, database_url: str, embedding_dimensions: int) -> None:
        self.embedding_dimensions = embedding_dimensions
        active_url = database_url
        if "@postgres:" in database_url:
            try:
                with psycopg.connect(database_url, connect_timeout=2):
                    pass
            except Exception:
                local_url = database_url.replace("@postgres:", "@localhost:")
                try:
                    with psycopg.connect(local_url, connect_timeout=2):
                        active_url = local_url
                except Exception:
                    pass
        self.pool = ConnectionPool(
            conninfo=active_url,
            min_size=1,
            max_size=8,
            timeout=20,
            max_idle=120,
            reconnect_timeout=30,
            kwargs={"row_factory": dict_row, "connect_timeout": 15},
            check=ConnectionPool.check_connection,
            open=True,
        )
        try:
            with self.pool.connection() as conn:
                conn.execute("ALTER TABLE action_proposals ADD COLUMN IF NOT EXISTS requires_attachment BOOLEAN DEFAULT FALSE;")
        except Exception:
            pass

    def close(self) -> None:
        self.pool.close()

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
        if not token:
            return None
        hashed = token_hash(token)
        with self.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT employee_id, display_name, role, department, manager_id
                FROM employees
                WHERE token_hash = %s
                UNION ALL
                SELECT e.employee_id, e.display_name, e.role, e.department, e.manager_id
                FROM auth_sessions s
                JOIN employees e ON e.employee_id = s.employee_id
                WHERE s.session_token_hash = %s
                  AND s.expires_at > CURRENT_TIMESTAMP
                LIMIT 1
                """,
                (hashed, hashed),
            ).fetchone()
        return AuthContext(**row) if row else None

    def authenticate_password(self, username: str, password: str, ttl_hours: int = 8) -> LoginResponse | None:
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
            if not row or not row.get("password_hash"):
                return None
            if not verify_password(password, row["password_hash"]):
                return None
            token = f"sess_{secrets.token_hex(24)}"
            expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
            connection.execute(
                """
                INSERT INTO auth_sessions (session_token_hash, employee_id, expires_at)
                VALUES (%s, %s, %s)
                """,
                (token_hash(token), row["employee_id"], expires_at),
            )
        profile = AuthContext(
            employee_id=row["employee_id"],
            display_name=row["display_name"],
            role=row["role"],
            department=row.get("department"),
            manager_id=row.get("manager_id"),
        )
        return LoginResponse(access_token=token, profile=profile)

    def create_demo_session(self, employee_id: str, ttl_hours: int = 8) -> LoginResponse:
        with self.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT employee_id, display_name, role, department, manager_id
                FROM employees
                WHERE employee_id = %s
                """,
                (employee_id,),
            ).fetchone()
            if not row:
                raise KeyError("employee not found")
            if row["role"] != "employee":
                raise PermissionError("demo session is only allowed for employee role")
            token = f"sess_{secrets.token_hex(24)}"
            expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
            connection.execute(
                """
                INSERT INTO auth_sessions (session_token_hash, employee_id, expires_at)
                VALUES (%s, %s, %s)
                """,
                (token_hash(token), row["employee_id"], expires_at),
            )
        return LoginResponse(
            access_token=token,
            profile=AuthContext(**row),
        )

    def list_personas(self, allow_demo_session: bool = False) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        rows: list[dict[str, Any]] = []
        for attempt in range(2):
            try:
                with self.pool.connection() as connection:
                    rows = connection.execute(
                        """
                        SELECT employee_id, username, display_name, role, department
                        FROM employees
                        ORDER BY employee_id
                        """
                    ).fetchall()
                last_error = None
                break
            except (psycopg.OperationalError, psycopg.InterfaceError) as err:
                last_error = err
                if attempt == 1:
                    raise
        if last_error is not None:
            raise last_error

        result: list[dict[str, Any]] = []
        for r in rows:
            emp_id = r["employee_id"]
            role = r["role"]
            result.append({
                "employee_id": emp_id,
                "username": r.get("username") or emp_id.lower(),
                "display_name": r["display_name"],
                "role": role,
                "department": r.get("department") or "Engineering",
                "requires_password": (not allow_demo_session) or (role != "employee"),
            })
        return result

    @staticmethod
    def _chunk(row: dict[str, Any]) -> PolicyChunk:
        return PolicyChunk(**row)

    _LATEST_VERSIONS_CTE = """
        WITH latest_versions AS (
            SELECT DISTINCT ON (document_id) document_id, version
            FROM policy_chunks
            WHERE effective_date <= COALESCE(%s::date, CURRENT_DATE)
            ORDER BY
                document_id,
                COALESCE(NULLIF(regexp_replace(split_part(version, '.', 1), '[^0-9]', '', 'g'), ''), '0')::bigint DESC,
                COALESCE(NULLIF(regexp_replace(split_part(version, '.', 2), '[^0-9]', '', 'g'), ''), '0')::bigint DESC,
                COALESCE(NULLIF(regexp_replace(split_part(version, '.', 3), '[^0-9]', '', 'g'), ''), '0')::bigint DESC,
                effective_date DESC,
                version DESC
        )
    """

    def lexical_search(self, query: str, limit: int, as_of: date | None = None) -> list[PolicyChunk]:
        stopwords = {"berapa", "apakah", "bagaimana", "kapan", "siapa", "yang", "dan", "di", "ke", "dari", "untuk", "pada", "saya", "aku", "bisa", "boleh", "per"}
        raw_terms = [t for t in re.findall(r"[a-z0-9]+", query.casefold()) if len(t) >= 2]
        filtered_terms = [t for t in raw_terms if t not in stopwords] or raw_terms
        if not filtered_terms:
            return []
        tsquery_str = " | ".join(filtered_terms)
        with self.pool.connection() as connection:
            rows = connection.execute(
                self._LATEST_VERSIONS_CTE
                + """
                SELECT pc.chunk_id, pc.document_id, pc.title, pc.section, pc.version, pc.effective_date, pc.content,
                       ts_rank(
                           to_tsvector('simple', pc.title || ' ' || pc.section || ' ' || pc.content),
                           to_tsquery('simple', %s)
                       ) AS score
                FROM policy_chunks pc
                JOIN latest_versions lv
                  ON pc.document_id = lv.document_id AND pc.version = lv.version
                WHERE pc.effective_date <= COALESCE(%s::date, CURRENT_DATE)
                  AND to_tsvector('simple', pc.title || ' ' || pc.section || ' ' || pc.content)
                      @@ to_tsquery('simple', %s)
                ORDER BY score DESC, pc.chunk_id
                LIMIT %s
                """,
                (as_of, tsquery_str, as_of, tsquery_str, limit),
            ).fetchall()
        return [self._chunk(row) for row in rows]

    def vector_search(self, embedding: list[float], limit: int, as_of: date | None = None) -> list[PolicyChunk]:
        if not embedding or len(embedding) != self.embedding_dimensions:
            return []
        try:
            floats = [float(value) for value in embedding]
        except (TypeError, ValueError):
            return []
        if any(not math.isfinite(value) for value in floats):
            return []
        vector = "[" + ",".join(str(value) for value in floats) + "]"
        with self.pool.connection() as connection:
            rows = connection.execute(
                self._LATEST_VERSIONS_CTE
                + """
                SELECT pc.chunk_id, pc.document_id, pc.title, pc.section, pc.version, pc.effective_date, pc.content,
                       1 - (pc.embedding <=> %s::vector) AS score
                FROM policy_chunks pc
                JOIN latest_versions lv
                  ON pc.document_id = lv.document_id AND pc.version = lv.version
                WHERE vector_dims(pc.embedding) = %s
                  AND pc.effective_date <= COALESCE(%s::date, CURRENT_DATE)
                ORDER BY pc.embedding <=> %s::vector, pc.chunk_id
                LIMIT %s
                """,
                (as_of, vector, self.embedding_dimensions, as_of, vector, limit),
            ).fetchall()
        return [self._chunk(row) for row in rows]

    def get_policy_document_text(self, document_id: str, as_of: date | None = None) -> str | None:
        with self.pool.connection() as connection:
            rows = connection.execute(
                """
                WITH latest_doc_version AS (
                    SELECT version
                    FROM policy_chunks
                    WHERE document_id = %s
                      AND effective_date <= COALESCE(%s::date, CURRENT_DATE)
                    ORDER BY
                        COALESCE(NULLIF(regexp_replace(split_part(version, '.', 1), '[^0-9]', '', 'g'), ''), '0')::bigint DESC,
                        COALESCE(NULLIF(regexp_replace(split_part(version, '.', 2), '[^0-9]', '', 'g'), ''), '0')::bigint DESC,
                        COALESCE(NULLIF(regexp_replace(split_part(version, '.', 3), '[^0-9]', '', 'g'), ''), '0')::bigint DESC,
                        effective_date DESC,
                        version DESC
                    LIMIT 1
                )
                SELECT pc.content
                FROM policy_chunks pc
                JOIN latest_doc_version lv ON pc.version = lv.version
                WHERE pc.document_id = %s
                  AND pc.effective_date <= COALESCE(%s::date, CURRENT_DATE)
                ORDER BY pc.chunk_id
                """,
                (document_id, as_of, document_id, as_of),
            ).fetchall()
        parts = [str(row["content"]).strip() for row in rows if row.get("content") and str(row["content"]).strip()]
        return "\n\n".join(parts) if parts else None

    def policy_fingerprint(self, as_of: date | None = None) -> str:
        with self.pool.connection() as connection:
            rows = connection.execute(
                self._LATEST_VERSIONS_CTE
                + """
                SELECT pc.chunk_id, pc.version, pc.content
                FROM policy_chunks pc
                JOIN latest_versions lv
                  ON pc.document_id = lv.document_id AND pc.version = lv.version
                WHERE pc.effective_date <= COALESCE(%s::date, CURRENT_DATE)
                ORDER BY pc.chunk_id
                """,
                (as_of, as_of),
            ).fetchall()
        digest = hashlib.sha256()
        for row in rows:
            digest.update(f"{row['chunk_id']}\0{row['version']}\0{row['content']}\n".encode("utf-8"))
        return digest.hexdigest()[:12]

    def list_evaluation_cases(self) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM evaluation_cases ORDER BY sort_order, case_id"
            ).fetchall()
        return [deepcopy(row["payload"]) for row in rows if isinstance(row.get("payload"), dict)]

    def get_balances(self, employee_id: str, as_of: date | None = None) -> list[LeaveBalance]:
        effective_date = as_of or date.today()
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
                    %s::date AS as_of_date
                FROM leave_balances b
                WHERE b.employee_id = %s
                ORDER BY b.leave_type
                """,
                (effective_date, employee_id),
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
            saved = connection.execute(
                """
                INSERT INTO action_proposals
                    (proposal_id, employee_id, action_type, leave_type, start_date, end_date,
                     business_days, reason, validation_summary, expires_at, requires_attachment)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (proposal_id) DO UPDATE SET
                    action_type = EXCLUDED.action_type,
                    leave_type = EXCLUDED.leave_type,
                    start_date = EXCLUDED.start_date,
                    end_date = EXCLUDED.end_date,
                    business_days = EXCLUDED.business_days,
                    reason = EXCLUDED.reason,
                    validation_summary = EXCLUDED.validation_summary,
                    expires_at = EXCLUDED.expires_at,
                    requires_attachment = EXCLUDED.requires_attachment
                WHERE action_proposals.employee_id = EXCLUDED.employee_id
                RETURNING proposal_id
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
            ).fetchone()
            if not saved:
                raise ConflictError("proposal_id belongs to another employee")

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

    def save_proposal_attachment(
        self,
        employee_id: str,
        proposal_id: str,
        filename: str,
        content_type: str,
        file_bytes: bytes,
    ) -> ProposalAttachmentView:
        with self.pool.connection() as connection:
            with connection.transaction():
                prop = connection.execute(
                    """
                    SELECT leave_type, expires_at
                    FROM action_proposals
                    WHERE proposal_id = %s AND employee_id = %s
                    FOR UPDATE
                    """,
                    (proposal_id, employee_id),
                ).fetchone()
                if not prop:
                    raise KeyError("proposal not found")
                expiry = prop["expires_at"]
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if expiry <= datetime.now(timezone.utc):
                    raise ConflictError("proposal expired")
                existing = connection.execute(
                    "SELECT 1 FROM leave_requests WHERE proposal_id = %s",
                    (proposal_id,),
                ).fetchone()
                if existing:
                    raise ConflictError("proposal already confirmed")
                if prop["leave_type"] != "sick":
                    raise ConflictError("attachment is only supported for sick leave proposals")

                uploaded_at = datetime.now(timezone.utc)
                connection.execute(
                    """
                    INSERT INTO proposal_attachments (
                        proposal_id, employee_id, filename, content_type, file_size_bytes, file_bytes, uploaded_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (proposal_id) DO UPDATE SET
                        filename = EXCLUDED.filename,
                        content_type = EXCLUDED.content_type,
                        file_size_bytes = EXCLUDED.file_size_bytes,
                        file_bytes = EXCLUDED.file_bytes,
                        uploaded_at = EXCLUDED.uploaded_at
                    """,
                    (
                        proposal_id,
                        employee_id,
                        filename,
                        content_type,
                        len(file_bytes),
                        file_bytes,
                        uploaded_at,
                    ),
                )
        return ProposalAttachmentView(
            proposal_id=proposal_id,
            employee_id=employee_id,
            filename=filename,
            content_type=content_type,
            file_size_bytes=len(file_bytes),
            uploaded_at=uploaded_at,
        )

    def confirm_proposal(
        self,
        employee_id: str,
        proposal_id: str,
        idempotency_key: str,
        today: date | None = None,
        enforce_attachment: bool = False,
    ) -> ActionResult:
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
                           reason, validation_summary, expires_at,
                           COALESCE(requires_attachment, FALSE) AS requires_attachment
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
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if expiry <= datetime.now(timezone.utc):
                    raise ConflictError("proposal expired")

                # 4. Re-validasi tanggal masa lalu
                if today is not None and proposal["start_date"] < today:
                    raise ConflictError("proposal dates are in the past")

                # 5. Re-validasi lampiran wajib (hanya dipaksa bila enforce_attachment=True, e.g. dari web SPA)
                if enforce_attachment and proposal["requires_attachment"]:
                    has_prop_att = connection.execute(
                        "SELECT 1 FROM proposal_attachments WHERE proposal_id = %s",
                        (proposal_id,),
                    ).fetchone()
                    has_req_att = connection.execute(
                        "SELECT 1 FROM leave_attachments WHERE request_id = %s",
                        (proposal_id,),
                    ).fetchone()
                    if not has_prop_att and not has_req_att:
                        raise ConflictError("dokumen pendukung surat dokter wajib diunggah sebelum konfirmasi")

                # 6. Re-validasi overlap terhadap request yang sudah ada
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

                # 7. Re-validasi saldo efektif
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
                connection.execute(
                    """
                    INSERT INTO leave_attachments (
                        request_id, employee_id, filename, content_type, file_size_bytes, file_bytes, uploaded_at
                    )
                    SELECT %s, employee_id, filename, content_type, file_size_bytes, file_bytes, uploaded_at
                    FROM proposal_attachments
                    WHERE proposal_id = %s
                    ON CONFLICT (request_id) DO NOTHING
                    """,
                    (request_id, proposal_id),
                )
                connection.execute(
                    "DELETE FROM proposal_attachments WHERE proposal_id = %s",
                    (proposal_id,),
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
                       r.reviewed_by, r.review_note, r.reviewed_at,
                       (a.request_id IS NOT NULL) AS has_attachment,
                       a.filename AS attachment_filename,
                       a.content_type AS attachment_content_type,
                       a.file_size_bytes AS attachment_size_bytes,
                       a.uploaded_at AS attachment_uploaded_at
                FROM leave_requests r
                LEFT JOIN leave_attachments a ON a.request_id = r.request_id
                WHERE r.employee_id = %s
                ORDER BY r.created_at DESC, r.request_id
                """,
                (employee_id,),
            ).fetchall()
        return [LeaveRequestView(**row) for row in rows]

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

            if requester.employee_id != row["employee_id"]:
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

    def create_ticket(
        self,
        employee_id: str,
        category: str,
        summary: str,
        ticket_id: str | None = None,
    ) -> str:
        clean_summary = redact(summary)
        with self.pool.connection() as connection:
            with connection.transaction():
                existing = connection.execute(
                    """
                    SELECT ticket_id FROM tickets
                    WHERE employee_id = %s AND category = %s AND summary = %s AND status != 'done'
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (employee_id, category, clean_summary),
                ).fetchone()
                if existing:
                    return str(existing["ticket_id"])
                active_ticket_id = ticket_id or f"T-{uuid4().hex[:12]}"
                connection.execute(
                    """
                    INSERT INTO tickets (ticket_id, employee_id, category, summary, status)
                    VALUES (%s, %s, %s, %s, 'pending')
                    ON CONFLICT (ticket_id) DO NOTHING
                    """,
                    (active_ticket_id, employee_id, category, clean_summary),
                )
        return active_ticket_id

    def list_tickets(
        self,
        employee_id: str | None = None,
        manager_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT
                t.ticket_id,
                t.employee_id,
                e.display_name AS employee_name,
                e.department,
                t.category,
                t.summary,
                COALESCE(t.status, 'pending') AS status,
                t.created_at,
                t.updated_at,
                t.updated_by
            FROM tickets t
            LEFT JOIN employees e ON t.employee_id = e.employee_id
        """
        clauses: list[str] = []
        params: list[Any] = []
        if employee_id:
            clauses.append("t.employee_id = %s")
            params.append(employee_id)
        if manager_id is not None:
            clauses.append("(e.manager_id = %s OR t.employee_id = %s)")
            params.extend([manager_id, manager_id])
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY t.created_at DESC"

        with self.pool.connection() as connection:
            rows = connection.execute(query, params).fetchall()

        results = []
        for r in rows:
            created_str = (
                r["created_at"].isoformat()
                if isinstance(r["created_at"], (datetime, date))
                else str(r["created_at"])
            )
            updated_str = (
                r["updated_at"].isoformat()
                if isinstance(r.get("updated_at"), (datetime, date))
                else (str(r["updated_at"]) if r.get("updated_at") else None)
            )
            results.append({
                "ticket_id": r["ticket_id"],
                "employee_id": r["employee_id"],
                "employee_name": r.get("employee_name") or r["employee_id"],
                "department": r.get("department") or "General",
                "category": r["category"],
                "summary": r["summary"],
                "status": r.get("status") or "pending",
                "created_at": created_str,
                "updated_at": updated_str,
                "updated_by": r.get("updated_by"),
            })
        return results

    def update_ticket_status(
        self,
        ticket_id: str,
        status: str,
        admin_id: str,
        allowed_manager_id: str | None = None,
    ) -> dict[str, Any]:
        if status not in ("pending", "on progress", "done"):
            raise ValueError(f"Status tidak valid: {status}")
        with self.pool.connection() as connection:
            with connection.transaction():
                current = connection.execute(
                    """
                    SELECT t.ticket_id, t.employee_id, e.manager_id
                    FROM tickets t
                    LEFT JOIN employees e ON e.employee_id = t.employee_id
                    WHERE t.ticket_id = %s
                    FOR UPDATE OF t
                    """,
                    (ticket_id,),
                ).fetchone()
                if not current:
                    raise KeyError(f"Tiket {ticket_id} tidak ditemukan")
                if allowed_manager_id is not None and current.get("manager_id") != allowed_manager_id:
                    raise PermissionError("not authorized to update ticket outside your team")
                row = connection.execute(
                    """
                    UPDATE tickets
                    SET status = %s, updated_at = CURRENT_TIMESTAMP, updated_by = %s
                    WHERE ticket_id = %s
                    RETURNING ticket_id, employee_id, category, summary, status, created_at, updated_at, updated_by
                    """,
                    (status, admin_id, ticket_id),
                ).fetchone()

                emp_row = connection.execute(
                    "SELECT display_name, department FROM employees WHERE employee_id = %s",
                    (row["employee_id"],),
                ).fetchone()

        created_str = (
            row["created_at"].isoformat()
            if isinstance(row["created_at"], (datetime, date))
            else str(row["created_at"])
        )
        updated_str = (
            row["updated_at"].isoformat()
            if isinstance(row.get("updated_at"), (datetime, date))
            else (str(row["updated_at"]) if row.get("updated_at") else None)
        )
        return {
            "ticket_id": row["ticket_id"],
            "employee_id": row["employee_id"],
            "employee_name": emp_row["display_name"] if emp_row else row["employee_id"],
            "department": emp_row["department"] if emp_row else "General",
            "category": row["category"],
            "summary": row["summary"],
            "status": row["status"],
            "created_at": created_str,
            "updated_at": updated_str,
            "updated_by": row.get("updated_by"),
        }


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

    def list_monitoring_rules(self) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT rule_id, metric, operator, threshold, minimum_samples, owner, response
                FROM monitoring_rules
                ORDER BY rule_id
                """
            ).fetchall()
        return [
            {
                "rule_id": r["rule_id"],
                "metric": r["metric"],
                "operator": r["operator"],
                "threshold": float(r["threshold"]),
                "minimum_samples": int(r["minimum_samples"]),
                "owner": r["owner"],
                "response": r["response"],
            }
            for r in rows
        ]

    def get_hr_analytics(self, auth: AuthContext, metric_focus: str = "overview", low_balance_threshold: int = 3) -> dict[str, Any]:
        if auth.role != "monitoring_admin":
            raise PermissionError("analytics requires monitoring_admin role")

        with self.pool.connection() as connection:
            emp_rows = connection.execute(
                "SELECT employee_id, department FROM employees WHERE role != 'monitoring_admin' ORDER BY employee_id"
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

            low_balance_employee_count = 0
            if scoped_emp_ids:
                req_rows = connection.execute(
                    """
                    SELECT r.leave_type, r.business_days, r.status, e.department
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
                    """,
                    (scoped_emp_ids,),
                ).fetchall()
                low_balance_employee_count = sum(
                    1 for row in bal_rows if int(row["annual_remaining"]) <= low_balance_threshold
                )

            ticket_rows = connection.execute(
                "SELECT category, COUNT(*) AS count FROM tickets GROUP BY category"
            ).fetchall()
            tickets_by_category = {
                row["category"]: int(row["count"]) for row in ticket_rows
            }

            return {
                "scope": "organization",
                "metric_focus": metric_focus,
                "low_balance_threshold": low_balance_threshold,
                "team_size": team_size,
                "requests_by_status": requests_by_status,
                "days_by_leave_type": days_by_leave_type,
                "low_balance_employee_count": low_balance_employee_count,
                "low_balance_employees": [],
                "department_breakdown": department_breakdown,
                "tickets_by_category": tickets_by_category,
                "ai_operations": self.monitoring_summary(),
            }