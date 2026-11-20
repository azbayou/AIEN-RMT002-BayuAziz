"""Strict tool schemas and identity-bound execution."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from typing import Any

from .config import Settings
from .contracts import (
    ActionProposal,
    AnalyticsQueryArgs,
    AuthContext,
    CalendarArgs,
    PrepareLeaveArgs,
    SearchPolicyArgs,
    TicketArgs,
)
from .domain import (
    compute_earliest_annual_leave_date,
    get_annual_leave_lead_days,
    get_sick_leave_doc_threshold,
    validate_leave_request,
)
from .repository import Repository
from .retrieval import RetrievalService
from .security import redact


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "search_hr_policy",
        "description": "Cari kebijakan HR yang relevan.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 2, "maxLength": 500},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "required": ["query", "top_k"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_my_leave_balance",
        "description": "Ambil saldo cuti milik pegawai yang terautentikasi.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "prepare_leave_request",
        "description": "Siapkan proposal cuti tanpa membuat request sampai dikonfirmasi.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "format": "date"},
                "end_date": {"type": "string", "format": "date"},
                "leave_type": {"type": "string", "enum": ["annual", "sick", "parental"]},
                "reason": {"type": ["string", "null"], "maxLength": 300},
            },
            "required": ["start_date", "end_date", "leave_type", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "create_hr_ticket",
        "description": "Buat tiket eskalasi HR untuk pegawai terautentikasi.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["policy_question", "leave_exception", "technical_issue", "privacy"],
                },
                "summary": {"type": "string", "minLength": 5, "maxLength": 500},
            },
            "required": ["category", "summary"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_calendar", #tambahan tool untuk menampilkan kalender
        "description": "Ambil daftar tanggal kalender, nama hari, dan status hari kerja atau akhir pekan mulai dari hari ini.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 1, "maximum": 30},
            },
            "required": ["days"],
            "additionalProperties": False,
        },
    },
]


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
            "low_balance_threshold": {
                "type": "integer",
                "minimum": 1,
                "maximum": 30,
            },
        },
        "required": ["metric_focus", "low_balance_threshold"],
        "additionalProperties": False,
    },
}


def get_tools_for_role(role: str) -> list[dict[str, Any]]:
    if role in ("manager", "monitoring_admin"):
        return [*TOOL_SCHEMAS, MANAGER_ANALYTICS_TOOL_SCHEMA]
    return list(TOOL_SCHEMAS)


class ToolExecutor:
    def __init__(self, repository: Repository, retrieval: RetrievalService, settings: Settings, today_factory=None) -> None:
        self.repository = repository
        self.retrieval = retrieval
        self.settings = settings
        self.today_factory = today_factory

    def _resolve_today(self) -> date:
        """Resolve effective system date for validation and calendar lookups."""
        return self.today_factory() if self.today_factory else (self.settings.reference_date or date.today())

    def _lookup_leave_policy_text(self, leave_type: str, today: date | None = None) -> str | None:
        """Retrieve relevant policy text for dynamic leave validation rules."""
        active_today = today or self._resolve_today()
        doc_map = {
            "annual": "HR-LEAVE-001",
            "sick": "HR-LEAVE-002",
            "parental": "HR-LEAVE-003",
        }
        doc_id = doc_map.get(leave_type)
        if doc_id and hasattr(self.repository, "get_policy_document_text"):
            try:
                text = self.repository.get_policy_document_text(doc_id, as_of=active_today)
                if text:
                    return text
            except Exception:
                pass

        queries = {
            "sick": "cuti sakit dokumen pendukung surat dokter",
            "annual": "pengajuan cuti tahunan paling lambat hari kerja",
            "parental": "cuti orang tua kelayakan proses",
        }
        query = queries.get(leave_type)
        if not query:
            return None
        try:
            chunks = self.retrieval.search(query, top_k=2)
            return "\n".join(c.content for c in chunks) if chunks else None
        except Exception:
            return None

    def _build_leave_proposal(self, args: PrepareLeaveArgs, auth: AuthContext) -> ActionProposal:
        """Run deterministic domain validation and construct an unconfirmed leave proposal."""
        today = self._resolve_today()
        policy_text = self._lookup_leave_policy_text(args.leave_type, today=today)
        days, summary = validate_leave_request(
            args,
            self.repository.get_balances(auth.employee_id),
            self.repository.has_overlap(auth.employee_id, args.start_date, args.end_date),
            today,
            policy_text=policy_text,
        )
        threshold = get_sick_leave_doc_threshold(policy_text)
        requires_att = (args.leave_type == "sick" and days > threshold)
        return ActionProposal(
            proposal_id=f"AP-{uuid4().hex[:12]}",
            leave_type=args.leave_type,
            start_date=args.start_date,
            end_date=args.end_date,
            business_days=days,
            reason=args.reason,
            validation_summary=summary,
            expires_at=datetime.now(timezone.utc)
            + timedelta(minutes=self.settings.proposal_ttl_minutes),
            requires_attachment=requires_att,
        )

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        auth: AuthContext,
        defer_tickets: bool = False,
    ) -> tuple[Any, ActionProposal | None]:
        if name == "search_hr_policy":
            args = SearchPolicyArgs.model_validate(arguments)
            return self.retrieval.search(args.query, args.top_k), None
        if name == "get_my_leave_balance":
            if arguments:
                raise ValueError("get_my_leave_balance tidak menerima argumen")
            return self.repository.get_balances(auth.employee_id), None
        if name == "get_calendar":
            args = CalendarArgs.model_validate(arguments)
            today = self._resolve_today()
            annual_text = (
                self.repository.get_policy_document_text("HR-LEAVE-001", as_of=today)
                if hasattr(self.repository, "get_policy_document_text")
                else None
            )
            sick_text = (
                self.repository.get_policy_document_text("HR-LEAVE-002", as_of=today)
                if hasattr(self.repository, "get_policy_document_text")
                else None
            )
            lead_days = get_annual_leave_lead_days(annual_text)
            earliest_annual = compute_earliest_annual_leave_date(today, lead_days)
            sick_threshold = get_sick_leave_doc_threshold(sick_text)
            day_names = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
            items = []
            for offset in range(args.days + 1):
                current = today + timedelta(days=offset)
                items.append(
                    {
                        "date": current.isoformat(),
                        "day_name": day_names[current.weekday()],
                        "is_business_day": current.weekday() < 5,
                        "can_book_annual_leave": current.weekday() < 5 and current >= earliest_annual,
                    }
                )
            return {
                "today": today.isoformat(),
                "today_day_name": day_names[today.weekday()],
                "annual_lead_days": lead_days,
                "earliest_annual_leave_date": earliest_annual.isoformat(),
                "sick_doc_threshold": sick_threshold,
                "calendar": items,
            }, None
        if name == "prepare_leave_request":
            args = PrepareLeaveArgs.model_validate(arguments)
            proposal = self._build_leave_proposal(args, auth)
            self.repository.save_proposal(auth.employee_id, proposal)
            return proposal, proposal
        if name == "create_hr_ticket":
            args = TicketArgs.model_validate(arguments)
            if not defer_tickets:
                return self.repository.create_ticket(auth.employee_id, args.category, args.summary), None
            clean_summary = redact(args.summary)
            ticket_id: str | None = None
            if hasattr(self.repository, "list_tickets"):
                try:
                    for existing in self.repository.list_tickets(auth.employee_id):
                        if (
                            existing.get("category") == args.category
                            and existing.get("summary") == clean_summary
                            and existing.get("status") != "done"
                        ):
                            ticket_id = str(existing["ticket_id"])
                            break
                except Exception:
                    ticket_id = None
            return {
                "ticket_id": ticket_id or f"T-{uuid4().hex[:12]}",
                "category": args.category,
                "summary": clean_summary,
                "status": "pending",
                "staged": True,
            }, None
        if name == "get_team_hr_analytics":
            if auth.role not in ("manager", "monitoring_admin"):
                from .domain import DomainError
                raise DomainError("akses analitik hanya diizinkan untuk Manager atau HR Admin")
            args = AnalyticsQueryArgs.model_validate(arguments)
            return self.repository.get_hr_analytics(auth, args.metric_focus, low_balance_threshold=args.low_balance_threshold), None
        raise ValueError(f"unknown tool: {name}")
