from pathlib import Path

import httpx
import streamlit as st

import ui.api_client as api_client
import ui.policy_rag as policy_rag
from ui_contract import API_PATHS, load_personas, select_persona


def test_supplied_personas_match_public_identity_contract() -> None:
    personas = load_personas(Path(__file__).resolve().parents[1] / "demo_personas.json")
    assert {item["employee_id"] for item in personas} == {"EMP-001", "EMP-002", "ADM-001"}
    assert len({item["demo_token"] for item in personas}) == len(personas)


def test_persona_change_clears_prior_response_and_confirmation_key() -> None:
    state = {
        "active_employee_id": "EMP-001",
        "last_chat": {"answer": "Alya's answer"},
        "idem_AP-OLD": "same-key",
        "pending_sick_attachment": {"filename": "surat_dokter_alya.pdf", "content_base64": "JVBERi0="},
        "uploaded_file_obj": object(),
        "dlg_sick_doc_uploader": "uploaded",
        "pending_assistant_query": "Ajukan cuti sakit",
        "pending_sick_att_AP-1": {"filename": "old.png"},
    }
    select_persona(state, {"employee_id": "EMP-002"})
    assert state == {"active_employee_id": "EMP-002"}


def test_supplied_ui_uses_documented_api_paths() -> None:
    assert API_PATHS["chat"] == "/api/v1/chat"
    assert API_PATHS["confirm"].format(proposal_id="AP-1") == "/api/v1/action-proposals/AP-1/confirm"
    assert API_PATHS["personas"] == "/api/v1/auth/personas"
    assert API_PATHS["policy_rules"] == "/api/v1/policies/rules"
    assert API_PATHS["leave_balances"] == "/api/v1/leave-balances/me"
    assert API_PATHS["tickets"] == "/api/v1/tickets"
    assert API_PATHS["ticket_status"].format(ticket_id="TKT-1") == "/api/v1/tickets/TKT-1/status"


def test_ensure_api_running_skips_remote_urls_and_probes_local(monkeypatch) -> None:
    assert api_client._is_local_api_url("http://localhost:8000") is True
    assert api_client._is_local_api_url("http://127.0.0.1:8000") is True
    assert api_client._is_local_api_url("http://0.0.0.0:8000") is True
    assert api_client._is_local_api_url("https://aien-rmt-002-bayu-aziz.vercel.app") is False
    assert api_client._is_local_api_url("https://api.example.com") is False

    fake_state: dict = {}
    monkeypatch.setattr(st, "session_state", fake_state)
    monkeypatch.setattr(api_client, "API_URL", "https://aien-rmt-002-bayu-aziz.vercel.app")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.get should not be called for remote API URLs")

    monkeypatch.setattr(api_client.httpx, "get", fail_if_called)
    api_client.ensure_api_running()
    assert "FASTAPI_DAEMON_STARTED" not in fake_state

    captured: dict = {}

    class OkResp:
        status_code = 200

    def fake_local_get(url: str, timeout: float = 0):
        captured["url"] = url
        captured["timeout"] = timeout
        return OkResp()

    monkeypatch.setattr(api_client, "API_URL", "http://localhost:8000")
    monkeypatch.setattr(api_client.httpx, "get", fake_local_get)
    api_client.ensure_api_running()
    assert captured == {"url": "http://localhost:8000/healthz", "timeout": 3.0}
    assert fake_state.get("FASTAPI_DAEMON_STARTED") is True


def _clear_policy_rag_caches() -> None:
    for fn in (
        policy_rag._fetch_policy_rules_cached,
        policy_rag._query_agent_for_lead_days,
        policy_rag.get_parental_leave_policy_summary,
        policy_rag.get_annual_leave_entitlement_from_policy,
        policy_rag._query_agent_for_sick_threshold,
    ):
        if hasattr(fn, "clear"):
            fn.clear()


def test_policy_rag_fetches_api_rules_and_falls_back_in_memory(monkeypatch) -> None:
    _clear_policy_rag_caches()
    monkeypatch.setattr(policy_rag, "API_URL", "http://unit-test-api")

    class RulesResp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "annual_lead_days": 5,
                "sick_doc_threshold": 3,
                "annual_entitlement_days": 14,
                "policy_summaries": {"parental": {"summary": "Ringkasan parental dari API"}},
            }

    monkeypatch.setattr(policy_rag.httpx, "get", lambda url, timeout=5.0: RulesResp())
    assert policy_rag.get_annual_leave_lead_days_from_policy() == 5
    assert policy_rag.get_sick_leave_doc_threshold_from_policy() == 3
    assert policy_rag.get_annual_leave_entitlement_from_policy() == 14
    parental = policy_rag.get_parental_leave_policy_summary("")
    assert parental["source"] == "policy_rules_api"
    assert "Ringkasan parental dari API" in parental["summary"]

    # When API is unreachable and no token is available, safe in-memory defaults apply (no disk reads)
    _clear_policy_rag_caches()

    def offline_get(url: str, timeout: float = 5.0):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(policy_rag.httpx, "get", offline_get)
    assert policy_rag.get_annual_leave_lead_days_from_policy("") == 3
    assert policy_rag.get_sick_leave_doc_threshold_from_policy("") == 2
    assert policy_rag.get_annual_leave_entitlement_from_policy("") == 12
    fallback_parental = policy_rag.get_parental_leave_policy_summary("")
    assert fallback_parental["source"] == "policy_rules_api"

    # When /policies/rules fails but token is provided, falls back to /api/v1/chat RAG
    _clear_policy_rag_caches()

    class ChatResp:
        status_code = 200

        def json(self) -> dict:
            return {"answer": "Pengajuan cuti tahunan minimal H-4 sebelum tanggal mulai."}

    monkeypatch.setattr(policy_rag.httpx, "post", lambda url, headers, json, timeout: ChatResp())
    assert policy_rag.get_annual_leave_lead_days_from_policy(token="token-alya") == 4



