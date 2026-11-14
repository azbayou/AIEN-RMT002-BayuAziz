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
    PrepareLeaveArgs,
    SearchPolicyArgs,
    TicketArgs,
)
from .domain import (
    get_annual_leave_lead_days,
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

    def execute(self, name: str, arguments: dict[str, Any], auth: AuthContext) -> tuple[Any, ActionProposal | None]:
        if name == "search_hr_policy":
            args = SearchPolicyArgs.model_validate(arguments)
            return self.retrieval.search(args.query, args.top_k), None
        if name == "get_my_leave_balance":
            if arguments:
                raise ValueError("get_my_leave_balance tidak menerima argumen")
            return self.repository.get_balances(auth.employee_id), None
        if name == "prepare_leave_request":
            args = PrepareLeaveArgs.model_validate(arguments)
            today = self.today_factory() if self.today_factory else date.today()
            policy_text = None
            if args.leave_type == "sick":
                try:
                    # Query PostgreSQL vector & lexical index via RAG
                    chunks = self.retrieval.search("cuti sakit dokumen pendukung surat dokter", top_k=2)
                    if chunks:
                        policy_text = "\n".join(c.content for c in chunks)
                except Exception:
                    policy_text = None
            elif args.leave_type == "annual":
                try:
                    # Query PostgreSQL vector & lexical index via RAG
                    chunks = self.retrieval.search("pengajuan cuti tahunan paling lambat hari kerja", top_k=2)
                    if chunks:
                        policy_text = "\n".join(c.content for c in chunks)
                except Exception:
                    policy_text = None

            days, summary = validate_leave_request(
                args,
                self.repository.get_balances(auth.employee_id),
                self.repository.has_overlap(auth.employee_id, args.start_date, args.end_date),
                today,
                policy_text=policy_text,
            )
            threshold = get_sick_leave_doc_threshold(policy_text)
            requires_att = (args.leave_type == "sick" and days > threshold)
            proposal = ActionProposal(
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
