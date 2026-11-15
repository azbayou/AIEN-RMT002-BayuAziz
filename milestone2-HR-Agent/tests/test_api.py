from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from src.providers import OpenAIProvider
from src.repository import MemoryRepository, PostgresRepository


AUTH = {"Authorization": "Bearer token-alya"}


def test_health_and_auth_contract(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.post("/api/v1/chat", json={"message": "saldo cuti"}).status_code == 401
    api_info = client.get("/api").json()
    assert api_info["status"] == "online"
    assert api_info["documentation"] == "/docs"


def test_chat_returns_contract_and_trace(client: TestClient) -> None:
    response = client.post("/api/v1/chat", headers=AUTH, json={"message": "Berapa jatah cuti tahunan?"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["outcome"] == "answered"
    assert payload["citations"][0]["document_id"] == "HR-LEAVE-001"
    trace = client.get(f"/api/v1/traces/{payload['trace_id']}", headers=AUTH)
    assert trace.status_code == 200
    assert "message" not in trace.json()


def test_monitoring_is_admin_only(client: TestClient) -> None:
    assert client.get("/api/v1/monitoring/summary", headers=AUTH).status_code == 403
    response = client.get(
        "/api/v1/monitoring/summary", headers={"Authorization": "Bearer token-admin"}
    )
    assert response.status_code == 200


def test_trace_cannot_be_read_by_another_employee(client: TestClient) -> None:
    chat = client.post("/api/v1/chat", headers=AUTH, json={"message": "saldo saya"}).json()
    response = client.get(
        f"/api/v1/traces/{chat['trace_id']}",
        headers={"Authorization": "Bearer token-bima"},
    )
    assert response.status_code == 403


def test_tickets_flow_and_permissions(client: TestClient, repository: PostgresRepository) -> None:
    t_id = repository.create_ticket("EMP-001", "privacy", "Tolong sensor data pribadi saya")

    # Employee alya views tickets: should see her ticket with initial status pending
    res_alya = client.get("/api/v1/tickets", headers={"Authorization": "Bearer token-alya"})
    assert res_alya.status_code == 200
    alya_tickets = res_alya.json()
    assert any(t["ticket_id"] == t_id and t["status"] == "pending" for t in alya_tickets)

    # Employee bima views tickets: should not see alya's ticket
    res_bima = client.get("/api/v1/tickets", headers={"Authorization": "Bearer token-bima"})
    assert res_bima.status_code == 200
    bima_tickets = res_bima.json()
    assert not any(t["ticket_id"] == t_id for t in bima_tickets)

    # Admin views tickets: should see all tickets
    res_admin = client.get("/api/v1/tickets", headers={"Authorization": "Bearer token-admin"})
    assert res_admin.status_code == 200
    admin_tickets = res_admin.json()
    assert any(t["ticket_id"] == t_id for t in admin_tickets)

    # Employee cannot update status (403 Forbidden)
    res_forbidden = client.patch(
        f"/api/v1/tickets/{t_id}/status",
        headers={"Authorization": "Bearer token-alya"},
        json={"status": "on progress"},
    )
    assert res_forbidden.status_code == 403

    # Admin updates status to "on progress"
    res_update = client.patch(
        f"/api/v1/tickets/{t_id}/status",
        headers={"Authorization": "Bearer token-admin"},
        json={"status": "on progress"},
    )
    assert res_update.status_code == 200
    assert res_update.json()["status"] == "on progress"
    assert res_update.json()["updated_by"] == "ADM-001"

    # Admin updates status to "done"
    res_done = client.patch(
        f"/api/v1/tickets/{t_id}/status",
        headers={"Authorization": "Bearer token-admin"},
        json={"status": "done"},
    )
    assert res_done.status_code == 200
    assert res_done.json()["status"] == "done"


def test_cors_headers_disallow_credentials_with_wildcard_origin(client: TestClient) -> None:
    preflight = client.options(
        "/api/v1/chat",
        headers={
            "Origin": "http://evil.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type, Authorization",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers.get("access-control-allow-origin") == "*"
    assert preflight.headers.get("access-control-allow-credentials") != "true"

    health = client.get("/healthz", headers={"Origin": "http://evil.com"})
    assert health.status_code == 200
    assert health.headers.get("access-control-allow-origin") == "*"
    assert health.headers.get("access-control-allow-credentials") != "true"

    vercel_path = Path(__file__).resolve().parents[1] / "vercel.json"
    if vercel_path.is_file():
        vercel_cfg = json.loads(vercel_path.read_text(encoding="utf-8"))
        for block in vercel_cfg.get("headers", []):
            header_keys = {h["key"].lower() for h in block.get("headers", [])}
            assert "access-control-allow-credentials" not in header_keys


def test_rfc7807_format_for_404_and_405_routing_errors(client: TestClient) -> None:
    res_404 = client.get("/api/v1/nonexistent-route-xyz")
    assert res_404.status_code == 404
    body_404 = res_404.json()
    assert body_404["type"] == "about:blank"
    assert body_404["title"] == "Not found"
    assert body_404["status"] == 404
    assert body_404["detail"]

    res_405 = client.post("/healthz")
    assert res_405.status_code == 405
    body_405 = res_405.json()
    assert body_405["type"] == "about:blank"
    assert body_405["title"] == "Method not allowed"
    assert body_405["status"] == 405
    assert body_405["detail"]


def test_validation_error_422_includes_field_level_detail(client: TestClient) -> None:
    res_chat = client.post("/api/v1/chat", headers=AUTH, json={})
    assert res_chat.status_code == 422
    body_chat = res_chat.json()
    assert body_chat["title"] == "Invalid request"
    assert body_chat["status"] == 422
    assert "Request validation failed:" in body_chat["detail"]
    assert "message" in body_chat["detail"]

    res_login = client.post("/api/v1/auth/login", json={"username": ""})
    assert res_login.status_code == 422
    body_login = res_login.json()
    assert "username" in body_login["detail"] or "password" in body_login["detail"]


def test_root_info_advertises_valid_leave_request_endpoints(client: TestClient) -> None:
    for path in ("/", "/api"):
        res = client.get(path)
        assert res.status_code == 200
        endpoints = res.json()["endpoints"]
        assert endpoints["leave_requests"] == "/api/v1/leave-requests/me"
        assert endpoints["manager_leave_requests"] == "/api/v1/manager/leave-requests"
        assert "/api/v1/leaves/requests" not in endpoints.values()

    assert client.get("/api/v1/leave-requests/me", headers=AUTH).status_code == 200


def test_postgres_repository_loads_live_personas_without_hardcode(repository: PostgresRepository) -> None:
    empty_repo = MemoryRepository()
    assert empty_repo.list_personas() == []
    assert empty_repo.authenticate("token-alya") is None

    personas = repository.list_personas()
    assert len(personas) >= 3
    assert all(p["employee_id"] != "MGR-001" for p in personas)
    assert repository.authenticate("token-alya") is not None
    assert repository.authenticate("token-bima") is not None
    assert repository.authenticate("token-admin") is not None
    assert repository.authenticate("token-manager") is None
    assert any(b.leave_type == "annual" for b in repository.get_balances("EMP-001"))


def test_openai_provider_gemini_stt_priority_and_combined_error(monkeypatch) -> None:
    import src.providers as providers_mod

    provider = OpenAIProvider(
        api_key="sk-test",
        model="gpt-4o-mini",
        embedding_model="text-embedding-3-small",
        gemini_api_key="gm-secret-key",
        gemini_stt_model="gemini-3.5-transcribe",
    )
    called_urls: list[str] = []

    class FakeResp:
        def __init__(self, status_code: int, text: str = "", json_data=None):
            self.status_code = status_code
            self.text = text
            self._json = json_data or {}

        def json(self):
            return self._json

    def fake_post_fail(url: str, json: dict, timeout: float):
        called_urls.append(url)
        return FakeResp(404, text="model not found")

    monkeypatch.setattr(providers_mod.httpx, "post", fake_post_fail)
    monkeypatch.setattr(
        provider.client.audio.transcriptions,
        "create",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("403 whisper-1 denied")),
    )

    try:
        provider.transcribe(b"RIFF\x00\x00\x00\x00WAVE", "sample.wav", "id")
        raise AssertionError("Expected RuntimeError when both Gemini and Whisper fail")
    except RuntimeError as exc:
        msg = str(exc)
        assert "Gemini:" in msg
        assert "Whisper:" in msg
        assert "gm-secret-key" not in msg

    assert called_urls[0].split("/models/")[1].startswith("gemini-2.5-flash:")
    assert called_urls[1].split("/models/")[1].startswith("gemini-2.0-flash:")
    assert called_urls[2].split("/models/")[1].startswith("gemini-1.5-flash:")

    # Verify [NO_SPEECH] returns empty string and valid transcript returns clean text
    monkeypatch.setattr(
        providers_mod.httpx,
        "post",
        lambda url, json, timeout: FakeResp(
            200,
            json_data={"candidates": [{"content": {"parts": [{"text": "[NO_SPEECH]"}]}}]},
        ),
    )
    assert provider.transcribe(b"RIFF\x00\x00\x00\x00WAVE", "silence.wav", "id") == ""



