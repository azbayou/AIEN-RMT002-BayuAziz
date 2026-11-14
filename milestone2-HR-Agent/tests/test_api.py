from __future__ import annotations

from fastapi.testclient import TestClient

from src.repository import MemoryRepository


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


def test_tickets_flow_and_permissions(client: TestClient, repository: MemoryRepository) -> None:
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


