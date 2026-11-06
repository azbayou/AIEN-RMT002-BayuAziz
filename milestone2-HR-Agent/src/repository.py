"""Repository contracts. Implement MemoryRepository first, then PostgreSQL/pgvector."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from math import sqrt
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4

from .contracts import ActionProposal, ActionResult, AuthContext, LeaveBalance, LeaveRequestView, PolicyChunk
from .security import redact, token_hash


class Repository(Protocol):
    def health(self) -> bool: ...
    def authenticate(self, token: str) -> AuthContext | None: ...
    def lexical_search(self, query: str, limit: int) -> list[PolicyChunk]: ...
    def vector_search(self, embedding: list[float], limit: int) -> list[PolicyChunk]: ...
    def get_balances(self, employee_id: str) -> list[LeaveBalance]: ...
    def has_overlap(self, employee_id: str, start: date, end: date) -> bool: ...
    def save_proposal(self, employee_id: str, proposal: ActionProposal) -> None: ...
    def get_proposal(self, proposal_id: str) -> tuple[str, ActionProposal] | None: ...
    def confirm_proposal(self, employee_id: str, proposal_id: str, idempotency_key: str) -> ActionResult: ...
    def list_leave_requests(self, employee_id: str) -> list[LeaveRequestView]: ...
    def create_ticket(self, employee_id: str, category: str, summary: str) -> str: ...
    def save_trace(self, trace: dict[str, Any]) -> None: ...
    def get_trace(self, trace_id: str) -> dict[str, Any] | None: ...
    def monitoring_summary(self) -> dict[str, Any]: ...


class ConflictError(RuntimeError):
    pass


class MemoryRepository:
    def __init__(self) -> None:
        self.chunks: list[PolicyChunk] = []
        self.identities: dict[str, tuple[AuthContext, str]] = {
            "EMP-001": (AuthContext(employee_id="EMP-001", display_name="Alya Pratama"), token_hash("token-alya")),
            "EMP-002": (AuthContext(employee_id="EMP-002", display_name="Bima Santoso"), token_hash("token-bima")),
            "ADM-001": (
                AuthContext(employee_id="ADM-001", display_name="Monitoring Admin", role="monitoring_admin"),
                token_hash("token-admin"),
            ),
        }
        today = date.today()
        self.balances: dict[str, list[LeaveBalance]] = {
            "EMP-001": [
                LeaveBalance(leave_type="annual", available_days=8, as_of_date=today),
                LeaveBalance(leave_type="sick", available_days=10, as_of_date=today),
                LeaveBalance(leave_type="parental", available_days=60, as_of_date=today),
            ],
            "EMP-002": [
                LeaveBalance(leave_type="annual", available_days=3, as_of_date=today),
                LeaveBalance(leave_type="sick", available_days=10, as_of_date=today),
                LeaveBalance(leave_type="parental", available_days=60, as_of_date=today),
            ],
        }
        self.proposals: dict[str, tuple[str, ActionProposal]] = {}
        self.idempotency_keys: dict[str, str] = {}
        self.embeddings: dict[str, list[float]] = {}
        self.requests: dict[str, list[LeaveRequestView]] = {}
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

    def lexical_search(self, query: str, limit: int) -> list[PolicyChunk]:
        terms = set(query.casefold().split())
        ranked: list[tuple[int, PolicyChunk]] = []
        for chunk in self.chunks:
            haystack = f"{chunk.title} {chunk.section} {chunk.content}".casefold()
            score = sum(term in haystack for term in terms)
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
        return [balance.model_copy(deep=True) for balance in self.balances.get(employee_id, [])]

    def has_overlap(self, employee_id: str, start: date, end: date) -> bool:
        return any(
            request.start_date <= end and request.end_date >= start
            for request in self.requests.get(employee_id, [])
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
            expiry = proposal.expires_at
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry <= datetime.now(timezone.utc):
                raise ConflictError("proposal expired")
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

    def list_leave_requests(self, employee_id: str) -> list[LeaveRequestView]:
        return [request.model_copy(deep=True) for request in self.requests.get(employee_id, [])]

    def create_ticket(self, employee_id: str, category: str, summary: str) -> str:
        ticket_id = f"T-{uuid4().hex[:12]}"
        self.tickets[ticket_id] = {
            "employee_id": employee_id,
            "category": category,
            "summary": redact(summary),
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
        errors = sum(bool(trace.get("error")) for trace in traces)
        return {
            "total_traces": len(traces),
            "error_count": errors,
            "error_rate": errors / len(traces) if traces else 0.0,
        }


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
        # TODO(M2): Create a psycopg connection pool. Do not interpolate user input into SQL.
        raise NotImplementedError

    # TODO(M2): Implement transaction-safe persistence and pgvector/full-text queries.
