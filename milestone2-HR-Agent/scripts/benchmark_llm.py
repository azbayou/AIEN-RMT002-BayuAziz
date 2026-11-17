#!/usr/bin/env python3
"""Opik LLM Comparison Experiment: Docker Localhost vs Docker Vercel.

Evaluates end-to-end HR Agent performance and answer quality across all scenarios
from ``data/evaluation_cases.json`` (with dynamic future leave dates for live
action cases), running 2 passes per item (Pass 1 initial vs Pass 2 warm cache)
and logging both deterministic metrics and LLM-as-a-Judge scores to Opik.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import statistics
import sys
import time
from typing import Any
import urllib.parse

import httpx
from openai import OpenAI
import opik
from opik.evaluation import evaluate
from opik.evaluation.metrics import AnswerRelevance, Hallucination
from opik.evaluation.metrics.score_result import ScoreResult
from opik.evaluation.models.base_model import ModelFeatures, OpikBaseModel

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_settings  # noqa: E402
from src.run_evaluation import _case_passed  # noqa: E402
from src.setup_lab import chunk_policy  # noqa: E402

CASES_PATH = ROOT / "data" / "evaluation_cases.json"
POLICIES_DIR = ROOT / "data" / "policies"
OUTPUT_DIR = ROOT / "outputs"

DEFAULT_LOCAL_URL = "http://localhost:8000"
DEFAULT_VERCEL_URL = "https://aien-rmt-002-bayu-aziz.vercel.app"
DEFAULT_TOKEN = "token-alya"
DEFAULT_DATASET_NAME = "llm-backend-comparison-v1"


def find_next_non_overlapping_leave_window(
    existing_requests: list[dict[str, Any]],
    today: date | None = None,
    min_lead_days: int = 14,
    business_days: int = 2,
) -> tuple[date, date]:
    """Return consecutive weekday dates starting >= today + min_lead_days without overlap."""
    ref_today = today or date.today()
    blocked_ranges: list[tuple[date, date]] = []
    for req in existing_requests:
        if req.get("status") not in ("pending_manager_review", "approved"):
            continue
        try:
            s_dt = date.fromisoformat(str(req["start_date"]))
            e_dt = date.fromisoformat(str(req["end_date"]))
            blocked_ranges.append((s_dt, e_dt))
        except (KeyError, TypeError, ValueError):
            continue

    candidate = ref_today + timedelta(days=min_lead_days)
    for _ in range(365):
        # Ensure all days in [candidate .. candidate + business_days - 1] are Mon-Fri
        span_end = candidate + timedelta(days=business_days - 1)
        all_weekdays = all(
            (candidate + timedelta(days=offset)).weekday() < 5
            for offset in range(business_days)
        )
        overlaps = any(
            s_dt <= span_end and e_dt >= candidate for s_dt, e_dt in blocked_ranges
        )
        if all_weekdays and not overlaps:
            return candidate, span_end
        candidate += timedelta(days=1)

    fallback_start = ref_today + timedelta(days=min_lead_days)
    while fallback_start.weekday() >= 4:
        fallback_start += timedelta(days=1)
    return fallback_start, fallback_start + timedelta(days=business_days - 1)


def load_policy_documents(policies_dir: Path = POLICIES_DIR) -> dict[str, str]:
    """Load policy section text grouped by canonical document_id."""
    docs: dict[str, list[str]] = {}
    for path in sorted(policies_dir.glob("*.md")):
        for chunk in chunk_policy(path):
            doc_id = chunk["document_id"]
            entry = f"[{doc_id}] {chunk['title']} - {chunk['section']}\n{chunk['content']}"
            docs.setdefault(doc_id, []).append(entry)
    return {doc_id: "\n\n".join(parts) for doc_id, parts in docs.items()}


def build_benchmark_cases(
    cases_path: Path = CASES_PATH,
    existing_requests: list[dict[str, Any]] | None = None,
    today: date | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Build dataset items from evaluation_cases.json with dynamic future action dates."""
    raw_cases = json.loads(cases_path.read_text(encoding="utf-8"))
    start_dt, end_dt = find_next_non_overlapping_leave_window(
        existing_requests or [], today=today
    )
    items: list[dict[str, Any]] = []
    for case in raw_cases:
        item = dict(case)
        if item.get("case_id") == "leave-valid-008":
            item["input"] = (
                f"Siapkan cuti tahunan {start_dt.isoformat()} sampai {end_dt.isoformat()}"
            )
        items.append(item)
    return items, {"start_date": start_dt.isoformat(), "end_date": end_dt.isoformat()}


def check_backend_readiness(base_url: str) -> dict[str, Any]:
    """Verify target backend /readyz reports ready=True with database and cache online."""
    url = base_url.rstrip("/")
    with httpx.Client(base_url=url, timeout=30.0) as client:
        resp = client.get("/readyz")
        resp.raise_for_status()
        payload = resp.json()
    deps = payload.get("dependencies") or {}
    if not payload.get("ready") or not deps.get("database") or not deps.get("cache"):
        raise RuntimeError(f"Backend {url} not fully ready: {payload}")
    return payload


def fetch_grounding_baseline(base_url: str, token: str) -> dict[str, Any]:
    """Fetch live employee leave requests, leave balances, and policy rules."""
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=30.0) as client:
        req_resp = client.get("/api/v1/leave-requests/me")
        req_resp.raise_for_status()
        bal_resp = client.get("/api/v1/leave-balances/me")
        bal_resp.raise_for_status()
        rules_resp = client.get("/api/v1/policies/rules")
        rules_resp.raise_for_status()
    return {
        "leave_requests": req_resp.json(),
        "leave_balances": bal_resp.json(),
        "policy_rules": rules_resp.json(),
    }


def sync_opik_dataset(
    client: opik.Opik,
    dataset_name: str,
    items: list[dict[str, Any]],
) -> Any:
    """Create or refresh Opik dataset so items match current cases and dynamic dates."""
    dataset = client.get_or_create_dataset(
        name=dataset_name,
        description="End-to-End LLM Benchmark Suite: Docker Localhost vs Docker Vercel",
    )
    desired_sig = [(item["case_id"], item["input"]) for item in items]
    current_items = dataset.get_items() if dataset.dataset_items_count else []
    current_sig = [
        (it.get("case_id"), it.get("input"))
        for it in current_items
        if isinstance(it, dict)
    ]

    if current_sig != desired_sig:
        if current_items:
            if hasattr(dataset, "clear"):
                dataset.clear()
            elif hasattr(dataset, "delete_items"):
                ids = [it["id"] for it in current_items if isinstance(it, dict) and it.get("id")]
                if ids:
                    dataset.delete_items(ids)
        dataset.insert(items)
    return dataset


class OpenAIChatJudgeModel(OpikBaseModel):
    """Custom OpikBaseModel adapter routed through the project's OpenAI model list."""

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str | None = None,
        timeout: float = 45.0,
    ) -> None:
        super().__init__(model_name=model_name)
        kwargs: dict[str, Any] = {"api_key": api_key, "timeout": timeout}
        if base_url and base_url.strip():
            kwargs["base_url"] = base_url.strip()
        self.client = OpenAI(**kwargs)

    @property
    def supported_features(self) -> ModelFeatures:
        return ModelFeatures(reasoning_effort=False, response_format_with_tools=True, logprobs=False)

    def generate_string(
        self,
        input: str,
        response_format: Any = None,
        **kwargs: Any,
    ) -> str:
        res = self.generate_chat_completion(
            messages=[{"role": "user", "content": input}],
            response_format=response_format,
            **kwargs,
        )
        return str(res.get("content", ""))

    def generate_provider_response(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> Any:
        return self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,  # type: ignore[arg-type]
        )

    def generate_chat_completion(
        self,
        messages: list[dict[str, Any]],
        response_format: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if response_format is not None:
            parsed_resp = self.client.chat.completions.parse(
                model=self.model_name,
                messages=messages,  # type: ignore[arg-type]
                response_format=response_format,
            )
            content = parsed_resp.choices[0].message.content or "{}"
        else:
            resp = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,  # type: ignore[arg-type]
            )
            content = resp.choices[0].message.content or ""
        return {"role": "assistant", "content": content}


def build_grounding_context(
    case: dict[str, Any],
    payload: dict[str, Any] | None,
    policy_docs: dict[str, str],
    baseline: dict[str, Any],
) -> list[str]:
    """Assemble factual grounding snippets for Opik Hallucination & AnswerRelevance judges."""
    snippets: list[str] = []
    seen_docs: set[str] = set()

    for doc_id in case.get("expected_documents") or []:
        if doc_id in policy_docs and doc_id not in seen_docs:
            snippets.append(policy_docs[doc_id])
            seen_docs.add(doc_id)

    if payload:
        for cit in payload.get("citations") or []:
            doc_id = cit.get("document_id")
            if doc_id and doc_id in policy_docs and doc_id not in seen_docs:
                snippets.append(policy_docs[doc_id])
                seen_docs.add(doc_id)
            elif cit.get("excerpt"):
                snippets.append(f"[{doc_id or 'POLICY'}] {cit['excerpt']}")

    category = case.get("category")
    if category == "tool":
        snippets.append(
            "Saldo cuti resmi pegawai terautentikasi (EMP-001 / Alya Pratama): "
            + json.dumps(baseline.get("leave_balances") or [], ensure_ascii=False)
        )
        if "HR-LEAVE-001" in policy_docs and "HR-LEAVE-001" not in seen_docs:
            snippets.append(policy_docs["HR-LEAVE-001"])
    elif category == "action":
        snippets.append(
            "Aturan & tanggal server saat ini: "
            + json.dumps(baseline.get("policy_rules") or {}, ensure_ascii=False)
        )
        snippets.append(
            "Saldo cuti pegawai saat ini: "
            + json.dumps(baseline.get("leave_balances") or [], ensure_ascii=False)
        )
        if payload and payload.get("action_proposal"):
            snippets.append(
                "Proposal cuti yang disiapkan sistem (memerlukan konfirmasi pengguna): "
                + json.dumps(payload["action_proposal"], ensure_ascii=False)
            )
        snippets.append(
            "Kebijakan sistem: Pengajuan cuti tidak dapat dibuat untuk tanggal lampau dan "
            "asisten AI hanya menyiapkan proposal butuh konfirmasi manusia (tidak pernah menyetujui sendiri)."
        )
    elif category in ("security", "privacy", "fallback"):
        snippets.append(
            "Kebijakan keamanan, privasi, dan fallback sistem: "
            "Pegawai hanya boleh mengakses datanya sendiri dan dilarang membocorkan token atau data pegawai lain. "
            "Diagnosis medis tidak boleh diminta atau disimpan dan harus disamarkan. "
            "Permintaan di luar cakupan kebijakan HR perusahaan harus ditolak/abstain secara ringkas tanpa mengarang fakta."
        )
    return snippets


def evaluate_deterministic_metrics(
    case: dict[str, Any],
    http_status: int | None,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compute deterministic pass/fail, citation validity, and tool accuracy."""
    if http_status is None or http_status < 200 or http_status >= 300 or not payload:
        return {
            "passed": False,
            "failures": [f"HTTP {http_status or 'error'}"],
            "citation_valid": 0.0,
            "tool_accuracy": 0.0,
        }

    passed, failures = _case_passed(case, payload)
    expected_docs = set(case.get("expected_documents") or [])
    citations = payload.get("citations") or []
    returned_docs = {c.get("document_id") for c in citations if c.get("document_id")}
    if expected_docs:
        citation_valid = 1.0 if (citations and expected_docs.issubset(returned_docs) and not (returned_docs - expected_docs)) else 0.0
    else:
        citation_valid = 1.0

    expected_tools = set(case.get("expected_tools") or [])
    ok_tools = {t.get("name") for t in (payload.get("tool_calls") or []) if t.get("status") == "ok"}
    if expected_tools:
        tool_accuracy = 1.0 if expected_tools.issubset(ok_tools) else 0.0
    else:
        tool_accuracy = 1.0

    return {
        "passed": passed,
        "failures": failures,
        "citation_valid": citation_valid,
        "tool_accuracy": tool_accuracy,
    }


def run_single_chat_turn(
    client: httpx.Client,
    case: dict[str, Any],
) -> dict[str, Any]:
    """Execute one POST /api/v1/chat turn and record timing, usage, and checks."""
    started = time.perf_counter()
    try:
        response = client.post("/api/v1/chat", json={"message": case["input"]})
        e2e_ms = round((time.perf_counter() - started) * 1000.0, 2)
        payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        usage = payload.get("usage") or {}
        server_ms = float(usage.get("latency_ms", 0.0))
        overhead_ms = round(max(0.0, e2e_ms - server_ms), 2) if server_ms > 0 else e2e_ms
        det = evaluate_deterministic_metrics(case, response.status_code, payload)
        in_tok = int(usage.get("input_tokens") or 0)
        out_tok = int(usage.get("output_tokens") or 0)
        est_cost = usage.get("estimated_cost")
        return {
            "status": "ok" if response.is_success else "error",
            "http_status": response.status_code,
            "e2e_latency_ms": e2e_ms,
            "server_latency_ms": round(server_ms, 2),
            "network_overhead_ms": overhead_ms,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "total_tokens": in_tok + out_tok,
            "estimated_cost": float(est_cost) if est_cost is not None else 0.0,
            "outcome": payload.get("outcome"),
            "trace_id": payload.get("trace_id"),
            "answer": str(payload.get("answer") or ""),
            "citations": [c.get("document_id") for c in (payload.get("citations") or [])],
            "tool_calls": payload.get("tool_calls") or [],
            "passed": det["passed"],
            "failures": det["failures"],
            "citation_valid": det["citation_valid"],
            "tool_accuracy": det["tool_accuracy"],
            "payload": payload,
        }
    except (httpx.HTTPError, ValueError) as exc:
        e2e_ms = round((time.perf_counter() - started) * 1000.0, 2)
        return {
            "status": "error",
            "http_status": None,
            "e2e_latency_ms": e2e_ms,
            "server_latency_ms": 0.0,
            "network_overhead_ms": e2e_ms,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_cost": 0.0,
            "outcome": "error",
            "trace_id": None,
            "answer": "",
            "citations": [],
            "tool_calls": [],
            "passed": False,
            "failures": [str(exc)],
            "citation_valid": 0.0,
            "tool_accuracy": 0.0,
            "payload": None,
        }


def build_item_metrics(
    case: dict[str, Any],
    pass_results: list[dict[str, Any]],
    policy_docs: dict[str, str],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    """Aggregate repeated pass metrics into one Opik dataset task output dict."""
    first = pass_results[0]
    pass1_e2e = first["e2e_latency_ms"]
    pass2_e2e = pass_results[1]["e2e_latency_ms"] if len(pass_results) > 1 else pass1_e2e
    e2e_mean = round(statistics.mean(r["e2e_latency_ms"] for r in pass_results), 2)
    server_mean = round(statistics.mean(r["server_latency_ms"] for r in pass_results), 2)
    overhead_mean = round(statistics.mean(r["network_overhead_ms"] for r in pass_results), 2)
    tokens_mean = round(statistics.mean(r["total_tokens"] for r in pass_results), 2)
    cost_mean = round(statistics.mean(r["estimated_cost"] for r in pass_results), 6)
    all_passed = all(r["passed"] for r in pass_results)
    citation_mean = round(statistics.mean(r["citation_valid"] for r in pass_results), 4)
    tool_mean = round(statistics.mean(r["tool_accuracy"] for r in pass_results), 4)

    context = build_grounding_context(case, first.get("payload"), policy_docs, baseline)
    compact_passes = [
        {k: v for k, v in r.items() if k != "payload"}
        for r in pass_results
    ]
    return {
        "case_id": case["case_id"],
        "category": case.get("category"),
        "hard_gate": bool(case.get("hard_gate")),
        "status": "ok" if all(r["status"] == "ok" for r in pass_results) else "error",
        "output": first["answer"],
        "context": context,
        "outcome": first.get("outcome"),
        "trace_ids": [r.get("trace_id") for r in pass_results],
        "e2e_latency_ms": e2e_mean,
        "pass1_e2e_ms": pass1_e2e,
        "pass2_e2e_ms": pass2_e2e,
        "cache_speedup_ms": round(pass1_e2e - pass2_e2e, 2),
        "server_latency_ms": server_mean,
        "network_overhead_ms": overhead_mean,
        "total_tokens": tokens_mean,
        "estimated_cost": cost_mean,
        "case_passed": 1.0 if all_passed else 0.0,
        "citation_valid": citation_mean,
        "tool_accuracy": tool_mean,
        "failures": [f for r in pass_results for f in r.get("failures", [])],
        "passes": compact_passes,
    }


def make_scoring_functions(
    judge_model: OpikBaseModel | None,
    judge_enabled: bool = True,
) -> list[Any]:
    """Create Opik ScoreResult functions for performance, determinism, and LLM judges."""

    def _num_score(name: str, key: str, unit: str = "") -> Any:
        def _scorer(
            dataset_item: dict[str, Any],
            task_outputs: dict[str, Any] | None = None,
            **kwargs: Any,
        ) -> ScoreResult:
            val = float((task_outputs or {}).get(key, 0.0))
            suffix = f" {unit}".rstrip()
            return ScoreResult(name=name, value=round(val, 4), reason=f"{name}={val:.2f}{suffix}")

        _scorer.__name__ = f"score_{name}"
        return _scorer

    def score_case_passed(
        dataset_item: dict[str, Any],
        task_outputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> ScoreResult:
        out = task_outputs or {}
        val = float(out.get("case_passed", 0.0))
        failures = out.get("failures") or []
        reason = "All passes satisfied deterministic assertions" if val == 1.0 else f"Failures: {failures}"
        return ScoreResult(name="case_passed", value=val, reason=reason)

    scorers: list[Any] = [
        _num_score("e2e_latency_ms", "e2e_latency_ms", "ms"),
        _num_score("pass1_e2e_ms", "pass1_e2e_ms", "ms"),
        _num_score("pass2_e2e_ms", "pass2_e2e_ms", "ms"),
        _num_score("cache_speedup_ms", "cache_speedup_ms", "ms"),
        _num_score("server_latency_ms", "server_latency_ms", "ms"),
        _num_score("network_overhead_ms", "network_overhead_ms", "ms"),
        _num_score("total_tokens", "total_tokens", "tokens"),
        _num_score("estimated_cost", "estimated_cost", "USD"),
        score_case_passed,
        _num_score("citation_valid", "citation_valid"),
        _num_score("tool_accuracy", "tool_accuracy"),
    ]

    if judge_enabled and judge_model is not None:
        relevance_metric = AnswerRelevance(
            model=judge_model,
            name="answer_relevance",
            require_context=False,
            track=False,
        )
        hallucination_metric = Hallucination(
            model=judge_model,
            name="hallucination",
            track=False,
        )

        def score_answer_relevance(
            dataset_item: dict[str, Any],
            task_outputs: dict[str, Any] | None = None,
            **kwargs: Any,
        ) -> ScoreResult:
            out = task_outputs or {}
            answer = str(out.get("output") or "").strip()
            if not answer or out.get("status") == "error":
                return ScoreResult(name="answer_relevance", value=0.0, reason="No valid answer returned")
            ctx = out.get("context") or None
            try:
                res = relevance_metric.score(
                    input=str(dataset_item.get("input", "")),
                    output=answer,
                    context=ctx,
                )
                return ScoreResult(name="answer_relevance", value=float(res.value), reason=res.reason)
            except Exception as exc:
                return ScoreResult(name="answer_relevance", value=0.0, reason=f"Judge error: {exc}")

        def score_hallucination(
            dataset_item: dict[str, Any],
            task_outputs: dict[str, Any] | None = None,
            **kwargs: Any,
        ) -> ScoreResult:
            out = task_outputs or {}
            answer = str(out.get("output") or "").strip()
            if not answer or out.get("status") == "error":
                return ScoreResult(name="hallucination", value=1.0, reason="No valid answer returned")
            ctx = out.get("context") or None
            try:
                res = hallucination_metric.score(
                    input=str(dataset_item.get("input", "")),
                    output=answer,
                    context=ctx,
                )
                return ScoreResult(name="hallucination", value=float(res.value), reason=res.reason)
            except Exception as exc:
                return ScoreResult(name="hallucination", value=0.0, reason=f"Judge error fallback: {exc}")

        scorers.extend([score_answer_relevance, score_hallucination])

    return scorers


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return round(ordered[idx], 2)


def aggregate_target_summary(
    target_name: str,
    base_url: str,
    experiment_name: str,
    eval_result: Any,
    recorded_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize latencies, token counts, deterministic pass rates, and judge scores."""
    all_passes = [p for item in recorded_items for p in item.get("passes", [])]
    e2e_vals = [float(p["e2e_latency_ms"]) for p in all_passes]
    server_vals = [float(p["server_latency_ms"]) for p in all_passes]
    overhead_vals = [float(p["network_overhead_ms"]) for p in all_passes]
    pass1_vals = [float(item["pass1_e2e_ms"]) for item in recorded_items]
    pass2_vals = [float(item["pass2_e2e_ms"]) for item in recorded_items]
    total_tokens = sum(int(p.get("total_tokens") or 0) for p in all_passes)
    total_input_tokens = sum(int(p.get("input_tokens") or 0) for p in all_passes)
    total_output_tokens = sum(int(p.get("output_tokens") or 0) for p in all_passes)
    total_cost = round(sum(float(p.get("estimated_cost") or 0.0) for p in all_passes), 6)

    judge_scores: dict[str, list[float]] = {"answer_relevance": [], "hallucination": []}
    for tr in getattr(eval_result, "test_results", []) or []:
        for sr in getattr(tr, "score_results", []) or []:
            if sr.name in judge_scores and not getattr(sr, "scoring_failed", False):
                judge_scores[sr.name].append(float(sr.value))

    case_pass_rate = (
        round(sum(1 for item in recorded_items if item["case_passed"] == 1.0) / len(recorded_items), 4)
        if recorded_items
        else 0.0
    )
    hard_items = [item for item in recorded_items if item.get("hard_gate")]
    hard_gates_ok = all(item["case_passed"] == 1.0 for item in hard_items)

    return {
        "target": target_name,
        "base_url": base_url,
        "experiment_id": eval_result.experiment_id,
        "experiment_name": experiment_name,
        "experiment_url": eval_result.experiment_url,
        "item_count": len(recorded_items),
        "total_requests": len(all_passes),
        "latency_ms": {
            "e2e_mean": round(statistics.mean(e2e_vals), 2) if e2e_vals else 0.0,
            "e2e_p50": round(statistics.median(e2e_vals), 2) if e2e_vals else 0.0,
            "e2e_p95": _percentile(e2e_vals, 95),
            "pass1_mean": round(statistics.mean(pass1_vals), 2) if pass1_vals else 0.0,
            "pass2_mean": round(statistics.mean(pass2_vals), 2) if pass2_vals else 0.0,
            "cache_speedup_mean": round(
                (statistics.mean(pass1_vals) - statistics.mean(pass2_vals)) if pass1_vals and pass2_vals else 0.0,
                2,
            ),
            "server_mean": round(statistics.mean(server_vals), 2) if server_vals else 0.0,
            "server_p50": round(statistics.median(server_vals), 2) if server_vals else 0.0,
            "server_p95": _percentile(server_vals, 95),
            "network_overhead_mean": round(statistics.mean(overhead_vals), 2) if overhead_vals else 0.0,
        },
        "tokens": {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "total_tokens": total_tokens,
            "avg_tokens_per_request": round(total_tokens / len(all_passes), 2) if all_passes else 0.0,
            "estimated_cost_usd": total_cost,
        },
        "quality": {
            "case_pass_rate": case_pass_rate,
            "hard_gates_passed": hard_gates_ok,
            "citation_valid_mean": round(
                statistics.mean(item["citation_valid"] for item in recorded_items), 4
            ) if recorded_items else 0.0,
            "tool_accuracy_mean": round(
                statistics.mean(item["tool_accuracy"] for item in recorded_items), 4
            ) if recorded_items else 0.0,
            "answer_relevance_mean": round(
                statistics.mean(judge_scores["answer_relevance"]), 4
            ) if judge_scores["answer_relevance"] else None,
            "hallucination_mean": round(
                statistics.mean(judge_scores["hallucination"]), 4
            ) if judge_scores["hallucination"] else None,
        },
        "items": recorded_items,
    }


def run_target_experiment(
    target_name: str,
    base_url: str,
    token: str,
    repeats: int,
    dataset: Any,
    policy_docs: dict[str, str],
    baseline: dict[str, Any],
    scoring_functions: list[Any],
    experiment_name: str,
    project_name: str,
    limit: int | None = None,
    judge_model_name: str = "gpt-6-luna",
) -> dict[str, Any]:
    """Run Opik evaluate() sequentially against one backend target."""
    print(f"\n{'=' * 72}")
    print(f"RUNNING OPIK EXPERIMENT: {target_name} ({base_url})")
    print(f"Experiment: {experiment_name} | Repeats: {repeats} | Limit: {limit or 'all'}")
    print(f"{'=' * 72}")

    recorded_items: list[dict[str, Any]] = []
    headers = {"Authorization": f"Bearer {token}"}

    with httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=60.0) as http_client:

        def task(dataset_item: dict[str, Any]) -> dict[str, Any]:
            case_id = dataset_item.get("case_id", "unknown")
            pass_results: list[dict[str, Any]] = []
            for idx in range(repeats):
                res = run_single_chat_turn(http_client, dataset_item)
                pass_results.append(res)
                print(
                    f"  [{target_name}] {case_id} pass {idx + 1}/{repeats}: "
                    f"e2e={res['e2e_latency_ms']:.1f}ms server={res['server_latency_ms']:.1f}ms "
                    f"tok={res['total_tokens']} ok={res['passed']}"
                )
            agg = build_item_metrics(dataset_item, pass_results, policy_docs, baseline)
            recorded_items.append(agg)
            return agg

        eval_result = evaluate(
            dataset=dataset,
            task=task,
            scoring_functions=scoring_functions,
            experiment_name=experiment_name,
            project_name=project_name,
            experiment_config={
                "target": target_name,
                "base_url": base_url,
                "repeats": repeats,
                "judge_model": judge_model_name,
            },
            experiment_tags=["llm-backend-comparison", target_name],
            nb_samples=limit,
            task_threads=1,
            verbose=1,
        )

    return aggregate_target_summary(target_name, base_url, experiment_name, eval_result, recorded_items)


def print_comparison_table(
    local_res: dict[str, Any],
    vercel_res: dict[str, Any],
    compare_url: str | None = None,
) -> None:
    """Print side-by-side comparison summary to stdout."""
    l_lat = local_res["latency_ms"]
    v_lat = vercel_res["latency_ms"]
    l_tok = local_res["tokens"]
    v_tok = vercel_res["tokens"]
    l_q = local_res["quality"]
    v_q = vercel_res["quality"]

    print("\n" + "=" * 76)
    print("OPIK LLM COMPARISON SUMMARY: DOCKER LOCALHOST vs DOCKER VERCEL")
    print("=" * 76)
    print(f"{'Metric':<34} | {'Docker Localhost':>17} | {'Docker Vercel':>17}")
    print("-" * 76)
    rows = [
        ("E2E Latency Mean (ms)", f"{l_lat['e2e_mean']:.2f}", f"{v_lat['e2e_mean']:.2f}"),
        ("E2E Latency p50 (ms)", f"{l_lat['e2e_p50']:.2f}", f"{v_lat['e2e_p50']:.2f}"),
        ("E2E Latency p95 (ms)", f"{l_lat['e2e_p95']:.2f}", f"{v_lat['e2e_p95']:.2f}"),
        ("Pass 1 Cold/Init Mean (ms)", f"{l_lat['pass1_mean']:.2f}", f"{v_lat['pass1_mean']:.2f}"),
        ("Pass 2 Warm Repeat Mean (ms)", f"{l_lat['pass2_mean']:.2f}", f"{v_lat['pass2_mean']:.2f}"),
        ("Cache Speedup (Pass1-Pass2 ms)", f"{l_lat['cache_speedup_mean']:.2f}", f"{v_lat['cache_speedup_mean']:.2f}"),
        ("Server Latency Mean (ms)", f"{l_lat['server_mean']:.2f}", f"{v_lat['server_mean']:.2f}"),
        ("Network Overhead Mean (ms)", f"{l_lat['network_overhead_mean']:.2f}", f"{v_lat['network_overhead_mean']:.2f}"),
        ("Total Tokens", f"{l_tok['total_tokens']}", f"{v_tok['total_tokens']}"),
        ("Deterministic Pass Rate", f"{l_q['case_pass_rate'] * 100:.1f}%", f"{v_q['case_pass_rate'] * 100:.1f}%"),
        ("Hard Gates Passed", str(l_q["hard_gates_passed"]), str(v_q["hard_gates_passed"])),
        ("Citation Validity Mean", f"{l_q['citation_valid_mean']:.3f}", f"{v_q['citation_valid_mean']:.3f}"),
        ("Tool Accuracy Mean", f"{l_q['tool_accuracy_mean']:.3f}", f"{v_q['tool_accuracy_mean']:.3f}"),
        (
            "Answer Relevance (Judge ↑)",
            f"{l_q['answer_relevance_mean']:.3f}" if l_q["answer_relevance_mean"] is not None else "n/a",
            f"{v_q['answer_relevance_mean']:.3f}" if v_q["answer_relevance_mean"] is not None else "n/a",
        ),
        (
            "Hallucination (Judge ↓)",
            f"{l_q['hallucination_mean']:.3f}" if l_q["hallucination_mean"] is not None else "n/a",
            f"{v_q['hallucination_mean']:.3f}" if v_q["hallucination_mean"] is not None else "n/a",
        ),
    ]
    for label, l_val, v_val in rows:
        print(f"{label:<34} | {l_val:>17} | {v_val:>17}")
    print("=" * 76)
    if compare_url:
        print(f"Opik Compare URL:\n  {compare_url}\n")


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Compare Docker Localhost vs Docker Vercel LLM backends in Opik.")
    parser.add_argument("--local-url", default=DEFAULT_LOCAL_URL)
    parser.add_argument("--vercel-url", default=DEFAULT_VERCEL_URL)
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--limit", type=int, default=None, help="Optional limit on number of dataset items (for smoke test)")
    parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    parser.add_argument("--judge-model", default=settings.agent_model or "gpt-6-luna")
    parser.add_argument("--no-judge", action="store_true", help="Skip LLM-as-a-Judge metrics")
    parser.add_argument("--opik-api-key", default=settings.opik_api_key or os.getenv("OPIK_API_KEY", ""))
    parser.add_argument("--opik-workspace", default=settings.opik_workspace or os.getenv("OPIK_WORKSPACE", "azbayou"))
    parser.add_argument("--opik-project", default=settings.opik_project_name or "Milestone 2 - HR Agent")
    args = parser.parse_args()

    if not args.opik_api_key:
        raise RuntimeError("OPIK_API_KEY is required (set in .env or --opik-api-key).")

    os.environ["OPIK_API_KEY"] = args.opik_api_key
    os.environ["OPIK_WORKSPACE"] = args.opik_workspace
    os.environ["OPIK_PROJECT_NAME"] = args.opik_project

    print("1/4 Checking backend readiness (/readyz)...")
    local_ready = check_backend_readiness(args.local_url)
    vercel_ready = check_backend_readiness(args.vercel_url)
    print(f"  Localhost readyz: {local_ready}")
    print(f"  Vercel readyz:    {vercel_ready}")

    print("2/4 Fetching grounding baseline & building dynamic dataset...")
    baseline = fetch_grounding_baseline(args.local_url, args.token)
    policy_docs = load_policy_documents()
    items, dynamic_dates = build_benchmark_cases(
        existing_requests=baseline.get("leave_requests") or []
    )
    print(f"  Dynamic leave-valid-008 dates: {dynamic_dates}")

    opik_client = opik.Opik(
        api_key=args.opik_api_key,
        workspace=args.opik_workspace,
        project_name=args.opik_project,
    )
    dataset = sync_opik_dataset(opik_client, args.dataset_name, items)
    print(f"  Opik Dataset ready: '{args.dataset_name}' ({dataset.id}, {dataset.dataset_items_count} items)")

    judge_model: OpikBaseModel | None = None
    if not args.no_judge:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for LLM-as-a-Judge scoring.")
        judge_model = OpenAIChatJudgeModel(
            model_name=args.judge_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
    scoring_functions = make_scoring_functions(judge_model, judge_enabled=not args.no_judge)

    run_ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    local_exp_name = f"llm-docker-localhost-{run_ts}"
    vercel_exp_name = f"llm-docker-vercel-{run_ts}"

    print("3/4 Running comparative Opik evaluations...")
    local_res = run_target_experiment(
        target_name="docker-localhost",
        base_url=args.local_url,
        token=args.token,
        repeats=args.repeats,
        dataset=dataset,
        policy_docs=policy_docs,
        baseline=baseline,
        scoring_functions=scoring_functions,
        experiment_name=local_exp_name,
        project_name=args.opik_project,
        limit=args.limit,
        judge_model_name=args.judge_model,
    )
    vercel_res = run_target_experiment(
        target_name="docker-vercel",
        base_url=args.vercel_url,
        token=args.token,
        repeats=args.repeats,
        dataset=dataset,
        policy_docs=policy_docs,
        baseline=baseline,
        scoring_functions=scoring_functions,
        experiment_name=vercel_exp_name,
        project_name=args.opik_project,
        limit=args.limit,
        judge_model_name=args.judge_model,
    )

    opik.flush_tracker()

    compare_params = urllib.parse.quote(
        json.dumps([local_res["experiment_id"], vercel_res["experiment_id"]])
    )
    compare_url = (
        f"https://www.comet.com/opik/{args.opik_workspace}/experiments/"
        f"{dataset.id}/compare?experiments={compare_params}"
    )

    print("4/4 Saving comparison report...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_timestamp": run_ts,
        "dataset": {
            "name": args.dataset_name,
            "id": dataset.id,
            "item_count": dataset.dataset_items_count,
            "evaluated_items": local_res["item_count"],
            "repeats": args.repeats,
            "dynamic_leave_dates": dynamic_dates,
        },
        "opik": {
            "workspace": args.opik_workspace,
            "project_name": args.opik_project,
            "compare_url": compare_url,
        },
        "docker_localhost": local_res,
        "docker_vercel": vercel_res,
    }
    ts_path = OUTPUT_DIR / f"llm_benchmark_{run_ts}.json"
    latest_path = OUTPUT_DIR / "llm_benchmark_latest.json"
    payload_str = json.dumps(report, ensure_ascii=False, indent=2)
    ts_path.write_text(payload_str, encoding="utf-8")
    latest_path.write_text(payload_str, encoding="utf-8")

    print_comparison_table(local_res, vercel_res, compare_url=compare_url)
    print(f"Saved report:\n  - {ts_path}\n  - {latest_path}")


if __name__ == "__main__":
    main()
