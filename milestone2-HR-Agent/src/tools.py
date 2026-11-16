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
    get_sick_leave_doc_threshold,
    validate_leave_request,
)
from .repository import Repository
from .retrieval import RetrievalService


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
        "name": "get_calendar",
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

    def _lookup_leave_policy_text(self, leave_type: str) -> str | None:
        """Retrieve relevant policy text for dynamic leave validation rules."""
        queries = {
            "sick": "cuti sakit dokumen pendukung surat dokter",
            "annual": "pengajuan cuti tahunan paling lambat hari kerja",
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
        policy_text = self._lookup_leave_policy_text(args.leave_type)
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

    def execute(self, name: str, arguments: dict[str, Any], auth: AuthContext) -> tuple[Any, ActionProposal | None]:
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
            day_names = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
            items = []
            for offset in range(args.days + 1):
                current = today + timedelta(days=offset)
                items.append(
                    {
                        "date": current.isoformat(),
                        "day_name": day_names[current.weekday()],
                        "is_business_day": current.weekday() < 5,
                    }
                )
            return {
                "today": today.isoformat(),
                "today_day_name": day_names[today.weekday()],
                "calendar": items,
            }, None
        if name == "prepare_leave_request":
            args = PrepareLeaveArgs.model_validate(arguments)
            proposal = self._build_leave_proposal(args, auth)
            self.repository.save_proposal(auth.employee_id, proposal)
            return proposal, proposal
        if name == "create_hr_ticket":
            args = TicketArgs.model_validate(arguments)
            return self.repository.create_ticket(auth.employee_id, args.category, args.summary), None
        if name == "get_team_hr_analytics":
            if auth.role not in ("manager", "monitoring_admin"):
                from .domain import DomainError
                raise DomainError("akses analitik hanya diizinkan untuk Manager atau HR Admin")
            args = AnalyticsQueryArgs.model_validate(arguments)
            return self.repository.get_hr_analytics(auth, args.metric_focus, low_balance_threshold=args.low_balance_threshold), None
        raise ValueError(f"unknown tool: {name}")
