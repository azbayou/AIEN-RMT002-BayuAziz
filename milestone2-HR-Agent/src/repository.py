"""Repository contracts. Implement MemoryRepository first, then PostgreSQL/pgvector."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import json
from math import sqrt
from pathlib import Path
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from psycopg.types.json import Jsonb

from .contracts import ActionProposal, ActionResult, AuthContext, LeaveBalance, LeaveRequestView, PolicyChunk
from .security import redact, token_hash

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _load_employees() -> list[dict[str, Any]]:
    path = _DATA_DIR / "employees.json"
    if not path.is_file():
        raise FileNotFoundError(f"Employees catalog not found at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


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
        self.identities: dict[str, tuple[AuthContext, str]] = {}
        self.balances: dict[str, list[LeaveBalance]] = {}
        today = date.today()
        for emp in _load_employees():
            emp_id = emp["employee_id"]
            self.identities[emp_id] = (
                AuthContext(
                    employee_id=emp_id,
                    display_name=emp["display_name"],
                    role=emp.get("role", "employee"),
                ),
                token_hash(emp["token"]),
            )
            self.balances[emp_id] = [
                LeaveBalance(leave_type=leave_type, available_days=days, as_of_date=today)
                for leave_type, days in emp.get("balances", {}).items()
            ]
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
        total = len(traces)
        errors = sum(bool(trace.get("error")) for trace in traces)
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
            "p95_latency_ms": p95_latency,
            "tool_calls": tool_calls_count,
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
        self.embedding_dimensions = embedding_dimensions
        self.pool = ConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=8,
            kwargs={"row_factory": dict_row},
            open=True,
        )

    def health(self) -> bool:
        try:
            with self.pool.connection() as connection:
                connection.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False

    def authenticate(self, token: str) -> AuthContext | None:
        hashed = token_hash(token)
        with self.pool.connection() as connection:
            row = connection.execute(
                "SELECT employee_id, display_name, role FROM employees WHERE token_hash = %s",
                (hashed,),
            ).fetchone()
        return AuthContext(**row) if row else None

    @staticmethod
    def _chunk(row: dict[str, Any]) -> PolicyChunk:
        return PolicyChunk(**row)

    def lexical_search(self, query: str, limit: int) -> list[PolicyChunk]:
        with self.pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT chunk_id, document_id, title, section, version, effective_date, content,
                       ts_rank(
                           to_tsvector('simple', title || ' ' || section || ' ' || content),
                           plainto_tsquery('simple', %s)
                       ) AS score
                FROM policy_chunks
                WHERE to_tsvector('simple', title || ' ' || section || ' ' || content)
                      @@ plainto_tsquery('simple', %s)
                ORDER BY score DESC, chunk_id
                LIMIT %s
                """,
                (query, query, limit),
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
                WHERE vector_dims(embedding) = %s
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
                SELECT leave_type, available_days, as_of_date
                FROM leave_balances
                WHERE employee_id = %s
                ORDER BY leave_type
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
                      AND status = 'pending_manager_review'
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
                     business_days, reason, validation_summary, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (proposal_id) DO UPDATE SET
                    employee_id = EXCLUDED.employee_id,
                    action_type = EXCLUDED.action_type,
                    leave_type = EXCLUDED.leave_type,
                    start_date = EXCLUDED.start_date,
                    end_date = EXCLUDED.end_date,
                    business_days = EXCLUDED.business_days,
                    reason = EXCLUDED.reason,
                    validation_summary = EXCLUDED.validation_summary,
                    expires_at = EXCLUDED.expires_at
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
                ),
            )

    def get_proposal(self, proposal_id: str) -> tuple[str, ActionProposal] | None:
        with self.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT employee_id, proposal_id, action_type, leave_type, start_date, end_date,
                       business_days, reason, validation_summary, expires_at
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
            expiry = proposal["expires_at"]
            if expiry <= datetime.now(timezone.utc):
                raise ConflictError("proposal expired")
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
                SELECT request_id, leave_type, start_date, end_date, business_days, status, created_at
                FROM leave_requests
                WHERE employee_id = %s
                ORDER BY created_at, request_id
                """,
                (employee_id,),
            ).fetchall()
        return [LeaveRequestView(**row) for row in rows]

    def create_ticket(self, employee_id: str, category: str, summary: str) -> str:
        ticket_id = f"T-{uuid4().hex[:12]}"
        with self.pool.connection() as connection:
            connection.execute(
                """
                INSERT INTO tickets (ticket_id, employee_id, category, summary)
                VALUES (%s, %s, %s, %s)
                """,
                (ticket_id, employee_id, category, redact(summary)),
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
                    COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY NULLIF(payload->'usage'->>'latency_ms', '')::double precision), 0.0) AS p95_latency_ms,
                    COALESCE(SUM(jsonb_array_length(CASE WHEN jsonb_typeof(payload->'tool_calls') = 'array' THEN payload->'tool_calls' ELSE '[]'::jsonb END)), 0) AS tool_calls
                FROM traces
                """
            ).fetchone()
        total = int(row["total_traces"])
        errors = int(row["error_count"])
        p95_latency = float(row["p95_latency_ms"]) if row["p95_latency_ms"] is not None else 0.0
        tool_calls = int(row["tool_calls"]) if row["tool_calls"] is not None else 0
        return {
            "run_count": total,
            "total_traces": total,
            "error_count": errors,
            "error_rate": errors / total if total else 0.0,
            "p95_latency_ms": p95_latency,
            "tool_calls": tool_calls,
        }
