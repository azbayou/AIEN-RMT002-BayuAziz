from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from engine.api import control_plane
from engine.api.main import app


class _DummyResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://dbc-118afc22-e599.cloud.databricks.com")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=request,
                response=response,
            )


class _FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class _FakeDatabricksConn:
    def __enter__(self) -> _FakeDatabricksConn:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def execute(self, sql: str) -> _FakeCursor:
        if "AVG(average_order_value)" in sql:
            return _FakeCursor([(90, 10000, 15102816.79, 13561301.58, 1509.79, 0.2269, 0.7548, 0.0001)])
        if "GROUP BY sales_channel" in sql:
            return _FakeCursor([
                ("WEB", 2507, 3473000.22, 413887.11),
                ("STORE", 2517, 3386261.46, 363409.34),
                ("MOBILE_APP", 2494, 3375258.14, 377163.93),
                ("MARKETPLACE", 2482, 3326781.76, 394779.83),
            ])
        if "LIMIT 7" in sql:
            return _FakeCursor([
                ("2026-09-19", 103, 124333.06),
                ("2026-09-18", 106, 145606.82),
            ])
        if "ops.pipeline_runs" in sql:
            return _FakeCursor([("run-1", 158770, 135805, 1)])
        return _FakeCursor([
            (f"check_{i}", "gold_validation", True, '{"ok": true}') for i in range(9)
        ])


def _set_local_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABRICKS_HOST", "https://dbc-118afc22-e599.cloud.databricks.com")
    monkeypatch.setenv("DATABRICKS_TOKEN", "test-databricks-secret-value")
    monkeypatch.setenv("DATABRICKS_JOB_ID", "1033864740434224")
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "d3c4e4657744978e")
    monkeypatch.setenv("DATABRICKS_ORG_ID", "7474648823106559")
    monkeypatch.setenv("DATABRICKS_CATALOG", "retail_analytics")
    monkeypatch.delenv("DEMO_PASSCODE", raising=False)


def _assert_no_secrets(payload_text: str, extra_secrets: tuple[str, ...] = ()) -> None:
    assert "dapia" not in payload_text.lower()
    for env_key in ("DATABRICKS_TOKEN", "DEMO_PASSCODE"):
        value = os.getenv(env_key, "").strip()
        if value:
            assert value not in payload_text
    for secret in extra_secrets:
        if secret:
            assert secret not in payload_text


def test_root_serves_modern_ui_without_leaking_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    live_token = os.getenv("DATABRICKS_TOKEN", "").strip()
    client = TestClient(app)

    root_res = client.get("/")
    assert root_res.status_code == 200
    assert "text/html" in root_res.headers.get("content-type", "")
    html = root_res.text

    for marker in (
        "retail_analytics",
        "Medallion",
        "/assets/styles.css",
        "/assets/data.js",
        "/assets/app.js",
        "authModal",
    ):
        assert marker in html

    assert "Press Start 2P" not in html
    assert "scanline" not in html.lower()

    status_res = client.get("/v1/control/status")
    assert status_res.status_code == 200
    metrics_res = client.get("/v1/control/metrics")
    assert metrics_res.status_code == 200

    for text in (html, status_res.text, metrics_res.text):
        _assert_no_secrets(text, extra_secrets=(live_token,))

    _set_local_env(monkeypatch)
    monkeypatch.setenv("DEMO_PASSCODE", "secret123")
    locked_status = client.get("/v1/control/status")
    _assert_no_secrets(
        locked_status.text,
        extra_secrets=(live_token, "test-databricks-secret-value", "secret123"),
    )


def test_static_assets_served() -> None:
    live_token = os.getenv("DATABRICKS_TOKEN", "").strip()
    client = TestClient(app)

    css_res = client.get("/assets/styles.css")
    assert css_res.status_code == 200
    assert len(css_res.text.strip()) > 0
    assert "text/css" in css_res.headers.get("content-type", "")

    for js_path in ("/assets/data.js", "/assets/app.js"):
        js_res = client.get(js_path)
        assert js_res.status_code == 200
        assert len(js_res.text.strip()) > 0
        assert "javascript" in js_res.headers.get("content-type", "")
        _assert_no_secrets(js_res.text, extra_secrets=(live_token,))


def test_control_status_local_env_and_locked_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_local_env(monkeypatch)
    client = TestClient(app)

    local_res = client.get("/v1/control/status")
    assert local_res.status_code == 200
    local_data = local_res.json()
    assert local_data["connected"] is True
    assert local_data["auth_mode"] == "local_env"
    assert local_data["read_ready"] is True
    assert local_data["live_ready"] is True
    assert local_data["requires_passcode"] is False
    assert local_data["job_id"] == 1033864740434224
    assert local_data["latest_verified_run_id"] == 647116123722071
    assert "dbc-118afc22-e599" in local_data["workspace_url"]
    assert "dbc-118afc22-e599" in local_data["job_url"]
    assert "1033864740434224" in local_data["job_url"]
    assert "1033864740434224" in local_data["latest_verified_run_url"]

    monkeypatch.setenv("DEMO_PASSCODE", "secret123")
    locked_res = client.get("/v1/control/status")
    assert locked_res.status_code == 200
    locked_data = locked_res.json()
    assert locked_data["auth_mode"] == "locked"
    assert locked_data["read_ready"] is True
    assert locked_data["live_ready"] is False
    assert locked_data["requires_passcode"] is True
    assert "dbc-118afc22-e599" in locked_data["workspace_url"]
    assert "1033864740434224" in locked_data["job_url"]

    monkeypatch.delenv("DATABRICKS_HOST", raising=False)
    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
    monkeypatch.delenv("DEMO_PASSCODE", raising=False)
    sim_res = client.get("/v1/control/status")
    assert sim_res.status_code == 200
    sim_data = sim_res.json()
    assert sim_data["auth_mode"] == "simulation_only"
    assert sim_data["read_ready"] is False
    assert sim_data["live_ready"] is False
    assert sim_data["requires_passcode"] is False


def test_passcode_auth_verify_and_unlock_status(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_local_env(monkeypatch)
    monkeypatch.setenv("DEMO_PASSCODE", "secret123")
    client = TestClient(app)

    bad_res = client.post("/v1/control/auth/verify", json={"mode": "passcode", "passcode": "nope"})
    assert bad_res.status_code == 401

    good_res = client.post(
        "/v1/control/auth/verify",
        json={"mode": "passcode", "passcode": "secret123"},
    )
    assert good_res.status_code == 200
    verify_data = good_res.json()
    expected_token = hmac.new(
        b"secret123",
        b"medallion-live-unlock",
        hashlib.sha256,
    ).hexdigest()
    assert verify_data["authenticated"] is True
    assert verify_data["auth_mode"] == "passcode_unlocked"
    assert verify_data["demo_token"] == expected_token

    unlocked_res = client.get(
        "/v1/control/status",
        headers={"X-Demo-Auth": verify_data["demo_token"]},
    )
    assert unlocked_res.status_code == 200
    unlocked_data = unlocked_res.json()
    assert unlocked_data["auth_mode"] == "passcode_unlocked"
    assert unlocked_data["live_ready"] is True
    assert unlocked_data["requires_passcode"] is False

    still_locked = client.get("/v1/control/status", headers={"X-Demo-Auth": "wrong-hmac-token"})
    assert still_locked.status_code == 200
    assert still_locked.json()["live_ready"] is False
    assert still_locked.json()["requires_passcode"] is True


def test_credentials_auth_verify_mocks_scim_and_byok_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_local_env(monkeypatch)
    monkeypatch.setenv("DEMO_PASSCODE", "secret123")

    captured: list[tuple[str, dict[str, Any]]] = []

    def fake_get(url: str, **kwargs: Any) -> _DummyResponse:
        captured.append((url, kwargs))
        if url.endswith("/api/2.0/preview/scim/v2/Me"):
            auth_header = (kwargs.get("headers") or {}).get("Authorization", "")
            if auth_header == "Bearer valid-pat-token":
                return _DummyResponse(200, {"userName": "architect@retail.dev"})
            return _DummyResponse(401, {"error": "unauthorized"})
        raise AssertionError(f"Unexpected httpx.get URL: {url}")

    monkeypatch.setattr(httpx, "get", fake_get)
    client = TestClient(app)

    missing_res = client.post(
        "/v1/control/auth/verify",
        json={"mode": "credentials", "host": "", "token": ""},
    )
    assert missing_res.status_code == 400

    rejected_res = client.post(
        "/v1/control/auth/verify",
        json={
            "mode": "credentials",
            "host": "dbc-custom.cloud.databricks.com/",
            "token": "bad-token",
        },
    )
    assert rejected_res.status_code == 401

    ok_res = client.post(
        "/v1/control/auth/verify",
        json={
            "mode": "credentials",
            "host": "dbc-custom.cloud.databricks.com/",
            "token": "valid-pat-token",
        },
    )
    assert ok_res.status_code == 200
    ok_data = ok_res.json()
    assert ok_data["authenticated"] is True
    assert ok_data["auth_mode"] == "byok_session"
    assert ok_data["host"] == "https://dbc-custom.cloud.databricks.com"
    assert ok_data["user_name"] == "architect@retail.dev"
    assert captured[-1][0] == "https://dbc-custom.cloud.databricks.com/api/2.0/preview/scim/v2/Me"

    byok_status = client.get(
        "/v1/control/status",
        headers={
            "X-Databricks-Host": "dbc-custom.cloud.databricks.com/",
            "X-Databricks-Token": "valid-pat-token",
        },
    )
    assert byok_status.status_code == 200
    status_data = byok_status.json()
    assert status_data["auth_mode"] == "byok_session"
    assert status_data["live_ready"] is True
    assert status_data["requires_passcode"] is False
    assert status_data["workspace_host"] == "https://dbc-custom.cloud.databricks.com"


def test_jobs_run_auth_guard_concurrent_guard_and_trigger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_local_env(monkeypatch)
    monkeypatch.setenv("DEMO_PASSCODE", "secret123")
    client = TestClient(app)

    locked_res = client.post("/v1/control/jobs/run")
    assert locked_res.status_code == 401

    monkeypatch.delenv("DEMO_PASSCODE", raising=False)
    active_runs: list[dict[str, Any]] = [
        {
            "run_id": 911223344,
            "run_page_url": "https://dbc-118afc22-e599.cloud.databricks.com/?o=7474648823106559#job/1033864740434224/run/911223344",
        }
    ]
    run_now_calls: list[dict[str, Any]] = []

    def fake_get(url: str, **kwargs: Any) -> _DummyResponse:
        if url.endswith("/api/2.1/jobs/runs/list"):
            params = kwargs.get("params") or {}
            assert str(params.get("active_only")).lower() == "true"
            return _DummyResponse(200, {"runs": active_runs})
        if url.endswith("/api/2.1/jobs/runs/get"):
            return _DummyResponse(
                200,
                {
                    "run_id": 777888999,
                    "run_page_url": "https://dbc-118afc22-e599.cloud.databricks.com/?o=7474648823106559#job/1033864740434224/run/777888999",
                },
            )
        raise AssertionError(f"Unexpected httpx.get URL: {url}")

    def fake_post(url: str, **kwargs: Any) -> _DummyResponse:
        if url.endswith("/api/2.1/jobs/run-now"):
            run_now_calls.append(kwargs.get("json") or {})
            return _DummyResponse(200, {"run_id": 777888999})
        raise AssertionError(f"Unexpected httpx.post URL: {url}")

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "post", fake_post)

    guard_res = client.post("/v1/control/jobs/run")
    assert guard_res.status_code == 200
    guard_data = guard_res.json()
    assert guard_data["triggered"] is False
    assert guard_data["already_running"] is True
    assert guard_data["run_id"] == 911223344
    assert len(run_now_calls) == 0

    active_runs.clear()
    trigger_res = client.post("/v1/control/jobs/run")
    assert trigger_res.status_code == 200
    trigger_data = trigger_res.json()
    assert trigger_data["triggered"] is True
    assert trigger_data["already_running"] is False
    assert trigger_data["run_id"] == 777888999
    assert trigger_data["job_id"] == 1033864740434224
    assert len(run_now_calls) == 1
    assert run_now_calls[0]["job_id"] == 1033864740434224


@pytest.mark.parametrize(
    ("life_cycle_state", "result_state", "task_state", "expected_overall", "expected_task"),
    [
        ("PENDING", None, {"life_cycle_state": "QUEUED"}, "PENDING", "PENDING"),
        ("RUNNING", None, {"life_cycle_state": "RUNNING"}, "RUNNING", "RUNNING"),
        (
            "TERMINATED",
            "SUCCESS",
            {"life_cycle_state": "TERMINATED", "result_state": "SUCCESS"},
            "SUCCESS",
            "SUCCESS",
        ),
        (
            "TERMINATED",
            "FAILED",
            {
                "life_cycle_state": "TERMINATED",
                "result_state": "FAILED",
                "state_message": "Quality gate threshold breached",
            },
            "FAILED",
            "FAILED",
        ),
    ],
)
def test_job_run_status_maps_databricks_lifecycle_and_task_states(
    monkeypatch: pytest.MonkeyPatch,
    life_cycle_state: str,
    result_state: str | None,
    task_state: dict[str, Any],
    expected_overall: str,
    expected_task: str,
) -> None:
    _set_local_env(monkeypatch)

    def fake_get(url: str, **kwargs: Any) -> _DummyResponse:
        assert url.endswith("/api/2.1/jobs/runs/get")
        return _DummyResponse(
            200,
            {
                "run_id": 123456,
                "job_id": 1033864740434224,
                "run_page_url": "https://dbc-118afc22-e599.cloud.databricks.com/?o=7474648823106559#job/1033864740434224/run/123456",
                "state": {
                    "life_cycle_state": life_cycle_state,
                    "result_state": result_state,
                    "state_message": "Simulated state",
                },
                "tasks": [
                    {
                        "task_key": "silver_quality_gate",
                        "state": task_state,
                        "execution_duration": 12000,
                        "setup_duration": 3000,
                        "run_page_url": "https://dbc-118afc22-e599.cloud.databricks.com/?o=7474648823106559#job/1033864740434224/run/123456/tasks/1",
                    }
                ],
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    client = TestClient(app)

    res = client.get("/v1/control/jobs/runs/123456")
    assert res.status_code == 200
    data = res.json()
    assert data["source"] == "live_databricks"
    assert data["overall_status"] == expected_overall
    assert len(data["tasks"]) == 1
    assert data["tasks"][0]["task_key"] == "silver_quality_gate"
    assert data["tasks"][0]["status"] == expected_task
    assert data["tasks"][0]["execution_duration_ms"] >= 12000


def test_verified_run_snapshot_and_locked_run_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABRICKS_HOST", raising=False)
    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
    monkeypatch.delenv("DEMO_PASSCODE", raising=False)
    client = TestClient(app)

    verified_res = client.get("/v1/control/jobs/runs/647116123722071")
    assert verified_res.status_code == 200
    verified_data = verified_res.json()
    assert verified_data["source"] == "snapshot"
    assert verified_data["overall_status"] == "SUCCESS"
    assert len(verified_data["tasks"]) == 6

    unauth_res = client.get("/v1/control/jobs/runs/999999")
    assert unauth_res.status_code == 401

    _set_local_env(monkeypatch)
    monkeypatch.setenv("DEMO_PASSCODE", "secret123")

    def fake_get(url: str, **kwargs: Any) -> _DummyResponse:
        assert url.endswith("/api/2.1/jobs/runs/get")
        return _DummyResponse(
            200,
            {
                "run_id": 999999,
                "job_id": 1033864740434224,
                "state": {"life_cycle_state": "RUNNING"},
                "tasks": [],
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    read_only_res = client.get("/v1/control/jobs/runs/999999")
    assert read_only_res.status_code == 200
    assert read_only_res.json()["source"] == "live_databricks"
    assert read_only_res.json()["overall_status"] == "RUNNING"


def test_control_metrics_snapshot_and_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    control_plane._METRICS_CACHE.clear()
    _set_local_env(monkeypatch)
    client = TestClient(app)

    res = client.get("/v1/control/metrics")
    assert res.status_code == 200
    data = res.json()
    assert data["source"] == "verified_snapshot"
    assert data["summary"]["days"] == 90
    assert data["summary"]["total_orders"] == 10000
    assert len(data["channels"]) == 4
    assert len(data["quality_checks"]) == 9
    assert len(data["daily_trend"]) == 7

    def failing_connect(target: str | None = None) -> Any:
        raise RuntimeError("Simulated Databricks SQL outage")

    monkeypatch.setattr("engine.api.control_plane.connect", failing_connect)
    refresh_res = client.get("/v1/control/metrics?refresh=true")
    assert refresh_res.status_code == 200
    refreshed = refresh_res.json()
    assert refreshed["source"] == "verified_snapshot"
    assert refreshed["summary"]["days"] == 90
    assert refreshed["summary"]["total_orders"] == 10000
    assert len(refreshed["channels"]) == 4
    assert len(refreshed["quality_checks"]) == 9

    monkeypatch.setattr(
        "engine.api.control_plane.connect",
        lambda target=None: _FakeDatabricksConn(),
    )
    live_res = client.get("/v1/control/metrics?refresh=true")
    assert live_res.status_code == 200
    live_data = live_res.json()
    assert live_data["source"] == "live_databricks"
    assert live_data["cached"] is False
    assert live_data["summary"]["days"] == 90
    assert live_data["summary"]["total_orders"] == 10000
    assert len(live_data["channels"]) == 4
    assert len(live_data["quality_checks"]) == 9

    cached_res = client.get("/v1/control/metrics")
    assert cached_res.status_code == 200
    assert cached_res.json()["cached"] is True
    control_plane._METRICS_CACHE.clear()


def test_latest_jobs_live_and_snapshot_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABRICKS_HOST", raising=False)
    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
    monkeypatch.delenv("DEMO_PASSCODE", raising=False)
    client = TestClient(app)

    snap_res = client.get("/v1/control/jobs/latest")
    assert snap_res.status_code == 200
    snap_data = snap_res.json()
    assert snap_data["source"] == "snapshot"
    assert snap_data["runs"][0]["run_id"] == 647116123722071

    _set_local_env(monkeypatch)
    monkeypatch.setenv("DEMO_PASSCODE", "secret123")

    def fake_get(url: str, **kwargs: Any) -> _DummyResponse:
        assert url.endswith("/api/2.1/jobs/runs/list")
        return _DummyResponse(
            200,
            {
                "runs": [
                    {
                        "run_id": 647116123722071,
                        "job_id": 1033864740434224,
                        "state": {"life_cycle_state": "TERMINATED", "result_state": "SUCCESS"},
                        "tasks": [],
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    live_res = client.get("/v1/control/jobs/latest")
    assert live_res.status_code == 200
    live_data = live_res.json()
    assert live_data["source"] == "live_databricks"
    assert live_data["runs"][0]["overall_status"] == "SUCCESS"

    def failing_get(url: str, **kwargs: Any) -> _DummyResponse:
        raise httpx.ConnectError("Databricks unreachable")

    monkeypatch.setattr(httpx, "get", failing_get)
    fallback_res = client.get("/v1/control/jobs/latest")
    assert fallback_res.status_code == 200
    assert fallback_res.json()["source"] == "snapshot"


def test_read_ready_vs_live_ready_and_inprocess_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control_plane._METRICS_CACHE.clear()
    _set_local_env(monkeypatch)
    monkeypatch.setenv("DEMO_PASSCODE", "secret123")

    run_now_calls: list[dict[str, Any]] = []

    def fake_get(url: str, **kwargs: Any) -> _DummyResponse:
        if url.endswith("/api/2.1/jobs/runs/list"):
            params = kwargs.get("params") or {}
            if params.get("active_only"):
                return _DummyResponse(200, {"runs": []})
            return _DummyResponse(
                200,
                {
                    "runs": [
                        {
                            "run_id": 647116123722071,
                            "job_id": 1033864740434224,
                            "state": {"life_cycle_state": "TERMINATED", "result_state": "SUCCESS"},
                            "tasks": [],
                        }
                    ]
                },
            )
        if url.endswith("/api/2.1/jobs/runs/get"):
            return _DummyResponse(
                200,
                {
                    "run_id": 647116123722071,
                    "job_id": 1033864740434224,
                    "state": {"life_cycle_state": "TERMINATED", "result_state": "SUCCESS"},
                    "tasks": [],
                },
            )
        raise AssertionError(f"Unexpected httpx.get URL: {url}")

    def fake_post(url: str, **kwargs: Any) -> _DummyResponse:
        if url.endswith("/api/2.1/jobs/run-now"):
            run_now_calls.append(kwargs.get("json") or {})
            return _DummyResponse(200, {"run_id": 888999})
        raise AssertionError(f"Unexpected httpx.post URL: {url}")

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(
        "engine.api.control_plane.connect",
        lambda target=None: _FakeDatabricksConn(),
    )

    client = TestClient(app)
    status_data = client.get("/v1/control/status").json()
    assert status_data["auth_mode"] == "locked"
    assert status_data["read_ready"] is True
    assert status_data["live_ready"] is False
    assert status_data["requires_passcode"] is True

    assert client.get("/v1/control/jobs/latest").json()["source"] == "live_databricks"
    assert (
        client.get("/v1/control/metrics?refresh=true").json()["source"]
        == "live_databricks"
    )
    assert client.post("/v1/control/jobs/run").status_code == 401

    assert control_plane.verify_passcode_value("secret123") is True
    assert control_plane.verify_passcode_value("wrong") is False

    boot_locked = control_plane.get_inprocess_boot_state(unlocked=False, refresh_metrics=True)
    assert boot_locked["status"]["read_ready"] is True
    assert boot_locked["status"]["live_ready"] is False
    assert boot_locked["status"]["auth_mode"] == "locked"
    assert boot_locked["latest_runs"]["source"] == "live_databricks"
    assert boot_locked["metrics"]["source"] == "live_databricks"
    _assert_no_secrets(
        json.dumps(boot_locked),
        extra_secrets=("test-databricks-secret-value", "secret123"),
    )

    boot_unlocked = control_plane.get_inprocess_boot_state(unlocked=True, refresh_metrics=False)
    assert boot_unlocked["status"]["live_ready"] is True
    assert boot_unlocked["status"]["auth_mode"] == "passcode_unlocked"

    with pytest.raises(PermissionError):
        control_plane.trigger_inprocess_job(unlocked=False)
    assert len(run_now_calls) == 0

    triggered = control_plane.trigger_inprocess_job(unlocked=True)
    assert triggered["triggered"] is True
    assert triggered["run_id"] == 888999
    assert len(run_now_calls) == 1

    run_detail = control_plane.get_inprocess_run_status(647116123722071)
    assert run_detail["source"] == "live_databricks"
    assert run_detail["overall_status"] == "SUCCESS"
    control_plane._METRICS_CACHE.clear()
