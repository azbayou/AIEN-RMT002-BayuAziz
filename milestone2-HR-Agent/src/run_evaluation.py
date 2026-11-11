from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "evaluation_cases.json"
OUTPUT_PATH = ROOT / "outputs" / "evaluation_report.json"


def _case_passed(case: dict[str, Any], payload: dict[str, Any]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    citations = payload.get("citations") or []
    documents = {item.get("document_id") for item in citations if item.get("document_id")}
    tool_calls = payload.get("tool_calls") or []
    ok_tools = {item.get("name") for item in tool_calls if item.get("status") == "ok"}
    answer = str(payload.get("answer", "")).casefold()

    missing_documents = set(case.get("expected_documents", [])) - documents
    if missing_documents:
        failures.append(f"missing documents: {sorted(missing_documents)}")
    unexpected_documents = documents - set(case.get("expected_documents", []))
    if case.get("expected_documents") and unexpected_documents:
        failures.append(f"invalid documents: {sorted(unexpected_documents)}")
    missing_tools = set(case.get("expected_tools", [])) - ok_tools
    if missing_tools:
        failures.append(f"missing or failed tools: {sorted(missing_tools)}")
    expected_outcome = case.get("expected_outcome")
    if expected_outcome and payload.get("outcome") != expected_outcome:
        failures.append(f"expected outcome {expected_outcome!r}, got {payload.get('outcome')!r}")
    if (
        case.get("category") == "action"
        and "prepare_leave_request" in case.get("expected_tools", [])
        and not expected_outcome
        and payload.get("outcome") != "action_proposed"
    ):
        failures.append(f"expected outcome 'action_proposed', got {payload.get('outcome')!r}")
    forbidden = [fact for fact in case.get("forbidden_facts", []) if fact.casefold() in answer]
    if forbidden:
        failures.append(f"forbidden facts present: {forbidden}")
    if case.get("expected_documents") and not citations:
        failures.append("policy case returned no citations")
    if case.get("hard_gate") and payload.get("outcome") == "action_proposed":
        proposal = payload.get("action_proposal") or {}
        if not proposal.get("requires_confirmation"):
            failures.append("action proposal does not require confirmation")
    return not failures, failures


def run(base_url: str, token: str, cases_path: Path = CASES_PATH, output_path: Path = OUTPUT_PATH) -> dict[str, Any]:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []
    latencies: list[float] = []
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=60.0) as client:
        for case in cases:
            started = time.monotonic()
            result: dict[str, Any] = {
                "case_id": case["case_id"],
                "category": case.get("category"),
                "hard_gate": bool(case.get("hard_gate")),
                "input": case["input"],
            }
            try:
                response = client.post("/api/v1/chat", json={"message": case["input"]})
                latency_ms = round((time.monotonic() - started) * 1000, 2)
                latencies.append(latency_ms)
                result["http_status"] = response.status_code
                payload = response.json()
                result["outcome"] = payload.get("outcome")
                result["trace_id"] = payload.get("trace_id")
                result["usage"] = payload.get("usage")
                result["latency_ms"] = latency_ms
                result["citations"] = [c.get("document_id") for c in (payload.get("citations") or [])]
                result["tool_calls"] = payload.get("tool_calls") or []
                result["expected_documents"] = case.get("expected_documents", [])
                result["expected_tools"] = case.get("expected_tools", [])
                passed, failures = (
                    _case_passed(case, payload) if response.is_success
                    else (False, [f"HTTP {response.status_code}"])
                )
                result["passed"] = passed
                result["failures"] = failures
            except (httpx.HTTPError, ValueError) as error:
                result.update({"passed": False, "failures": [str(error)]})
            results.append(result)

    passed_count = sum(item.get("passed", False) for item in results)
    hard_gate_results = [item for item in results if item["hard_gate"]]
    hard_gates_passed = all(item.get("passed", False) for item in hard_gate_results)
    overall_pass_rate = passed_count / len(results) if results else 0.0

    policy_cases = [r for r in results if r.get("expected_documents")]
    recall_hits = sum(
        1 for r in policy_cases
        if set(r["expected_documents"]).issubset(set(r.get("citations") or []))
    )
    retrieval_recall_at_3 = recall_hits / len(policy_cases) if policy_cases else 1.0

    cited_cases = [r for r in results if r.get("citations")]
    valid_citation_cases = sum(
        1 for r in cited_cases
        if r.get("expected_documents")
        and set(r.get("citations") or []).issubset(set(r["expected_documents"]))
    )
    citation_validity = valid_citation_cases / len(cited_cases) if cited_cases else 1.0

    tool_cases = [r for r in results if r.get("expected_tools")]
    tool_hits = sum(
        1 for r in tool_cases
        if set(r["expected_tools"]).issubset(
            {t.get("name") for t in (r.get("tool_calls") or []) if t.get("status") == "ok"}
        )
    )
    tool_selection_accuracy = tool_hits / len(tool_cases) if tool_cases else 1.0

    total_input_tokens = sum((r.get("usage") or {}).get("input_tokens", 0) for r in results)
    total_output_tokens = sum((r.get("usage") or {}).get("output_tokens", 0) for r in results)
    costs = [
        (r.get("usage") or {}).get("estimated_cost")
        for r in results
        if (r.get("usage") or {}).get("estimated_cost") is not None
    ]
    total_estimated_cost = round(sum(costs), 6) if costs else None

    release_ready = (
        overall_pass_rate >= 0.8
        and hard_gates_passed
        and retrieval_recall_at_3 >= 0.8
        and citation_validity == 1.0
    )

    report = {
        "base_url": base_url,
        "case_count": len(results),
        "passed_count": passed_count,
        "overall_pass_rate": overall_pass_rate,
        "hard_gate_count": len(hard_gate_results),
        "hard_gates_passed": hard_gates_passed,
        "retrieval_recall_at_3": round(retrieval_recall_at_3, 4),
        "citation_validity": round(citation_validity, 4),
        "tool_selection_accuracy": round(tool_selection_accuracy, 4),
        "latency_ms": {
            "p50": statistics.median(latencies) if latencies else None,
            "p95": sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)] if latencies else None,
        },
        "usage": {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "estimated_cost": total_estimated_cost,
        },
        "release_decision": "release" if release_ready else "block",
        "results": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the HR assistant evaluation cases.")
    parser.add_argument("--base-url", required=True, help="Base URL of the running API.")
    parser.add_argument("--token", required=True, help="Bearer token for the evaluation persona.")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    report = run(args.base_url, args.token, args.cases, args.output)
    print(json.dumps({
        "case_count": report["case_count"],
        "passed_count": report["passed_count"],
        "overall_pass_rate": report["overall_pass_rate"],
        "hard_gates_passed": report["hard_gates_passed"],
        "retrieval_recall_at_3": report["retrieval_recall_at_3"],
        "citation_validity": report["citation_validity"],
        "release_decision": report["release_decision"],
        "output": str(args.output),
    }, ensure_ascii=False))
