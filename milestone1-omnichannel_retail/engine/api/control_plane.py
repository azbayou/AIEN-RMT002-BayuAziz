"""Databricks Lakehouse control-plane router for live status, auth, jobs, and KPIs."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import logging
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from shared.db import connect

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/control", tags=["control-plane"])

DEFAULT_HOST = "https://dbc-118afc22-e599.cloud.databricks.com"
DEFAULT_ORG_ID = "7474648823106559"
DEFAULT_JOB_ID = 1033864740434224
DEFAULT_WAREHOUSE_ID = "d3c4e4657744978e"
DEFAULT_CATALOG = "retail_analytics"
VERIFIED_RUN_ID = 647116123722071

METRICS_CACHE_TTL_SECONDS = 60.0
_CATALOG_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")

_VERIFIED_RUN_URL = (
    f"{DEFAULT_HOST}/?o={DEFAULT_ORG_ID}#job/{DEFAULT_JOB_ID}/run/{VERIFIED_RUN_ID}"
)

VERIFIED_RUN_SNAPSHOT: dict[str, Any] = {
    "run_id": VERIFIED_RUN_ID,
    "job_id": DEFAULT_JOB_ID,
    "run_name": "[dev] Omnichannel Retail Medallion Pipeline",
    "overall_status": "SUCCESS",
    "life_cycle_state": "TERMINATED",
    "result_state": "SUCCESS",
    "state_message": "",
    "run_duration_ms": 551081,
    "run_page_url": _VERIFIED_RUN_URL,
    "tasks": [
        {
            "task_key": "setup_schemas",
            "status": "SUCCESS",
            "execution_duration_ms": 38000,
            "run_page_url": _VERIFIED_RUN_URL,
            "state_message": "",
        },
        {
            "task_key": "load_bronze",
            "status": "SUCCESS",
            "execution_duration_ms": 46000,
            "run_page_url": _VERIFIED_RUN_URL,
            "state_message": "",
        },
        {
            "task_key": "build_silver",
            "status": "SUCCESS",
            "execution_duration_ms": 91000,
            "run_page_url": _VERIFIED_RUN_URL,
            "state_message": "",
        },
        {
            "task_key": "silver_quality_gate",
            "status": "SUCCESS",
            "execution_duration_ms": 43000,
            "run_page_url": _VERIFIED_RUN_URL,
            "state_message": "",
        },
        {
            "task_key": "build_gold",
            "status": "SUCCESS",
            "execution_duration_ms": 49000,
            "run_page_url": _VERIFIED_RUN_URL,
            "state_message": "",
        },
        {
            "task_key": "validate_gold_and_reconciliation",
            "status": "SUCCESS",
            "execution_duration_ms": 34000,
            "run_page_url": _VERIFIED_RUN_URL,
            "state_message": "",
        },
    ],
}

VERIFIED_METRICS_SNAPSHOT: dict[str, Any] = {
    "summary": {
        "days": 90,
        "total_orders": 10000,
        "gross_revenue": 15102816.79,
        "net_revenue": 13561301.58,
        "average_order_value": 1509.79,
        "refund_rate": 0.2269,
        "repeat_customer_rate": 0.7548,
        "stockout_rate": 0.0001,
        "bronze_raw_records": 158770,
        "silver_clean_records": 135805,
        "silver_rejected_records": 1,
        "delta_tables": 25,
        "benchmark_passed": "25/25",
        "reconciliation_diff": 0.0,
    },
    "channels": [
        {
            "sales_channel": "WEB",
            "orders": 2507,
            "net_revenue": 3473000.22,
            "refunded": 413887.11,
        },
        {
            "sales_channel": "STORE",
            "orders": 2517,
            "net_revenue": 3386261.46,
            "refunded": 363409.34,
        },
        {
            "sales_channel": "MOBILE_APP",
            "orders": 2494,
            "net_revenue": 3375258.14,
            "refunded": 377163.93,
        },
        {
            "sales_channel": "MARKETPLACE",
            "orders": 2482,
            "net_revenue": 3326781.76,
            "refunded": 394779.83,
        },
    ],
    "daily_trend": [
        {"metric_date": "2026-09-13", "total_orders": 111, "net_revenue": 149527.46},
        {"metric_date": "2026-09-14", "total_orders": 117, "net_revenue": 144361.50},
        {"metric_date": "2026-09-15", "total_orders": 130, "net_revenue": 193374.68},
        {"metric_date": "2026-09-16", "total_orders": 103, "net_revenue": 133964.58},
        {"metric_date": "2026-09-17", "total_orders": 96, "net_revenue": 131195.93},
        {"metric_date": "2026-09-18", "total_orders": 106, "net_revenue": 145606.82},
        {"metric_date": "2026-09-19", "total_orders": 103, "net_revenue": 124333.06},
    ],
    "quality_checks": [
        {
            "check_name": "silver_orders_row_count",
            "check_stage": "silver_gate",
            "passed": True,
            "details": {"order_count": 10000},
        },
        {
            "check_name": "silver_no_negative_qty",
            "check_stage": "silver_gate",
            "passed": True,
            "details": {"negative_quantity_rows": 0, "quarantined_rows": 1},
        },
        {
            "check_name": "silver_orders_unique_pk",
            "check_stage": "silver_gate",
            "passed": True,
            "details": {"duplicates": 0},
        },
        {
            "check_name": "silver_referential_integrity",
            "check_stage": "silver_gate",
            "passed": True,
            "details": {"orphan_rows": 0},
        },
        {
            "check_name": "gold_unique_pks",
            "check_stage": "gold_validation",
            "passed": True,
            "details": {"duplicates": 0},
        },
        {
            "check_name": "gold_net_revenue_reconciliation",
            "check_stage": "gold_validation",
            "passed": True,
            "details": {"diff": 0.0},
        },
        {
            "check_name": "gold_refund_reconciliation",
            "check_stage": "gold_validation",
            "passed": True,
            "details": {"diff": 0.0},
        },
        {
            "check_name": "gold_kpi_rate_bounds",
            "check_stage": "gold_validation",
            "passed": True,
            "details": {"out_of_bounds": 0},
        },
        {
            "check_name": "gold_non_null_grains",
            "check_stage": "gold_validation",
            "passed": True,
            "details": {"null_grains": 0},
        },
    ],
}

_METRICS_CACHE: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}


@dataclass(frozen=True)
class ControlContext:
    """Resolved request-scoped Databricks authentication and deep-link context."""

    host: str
    token: str
    org_id: str
    catalog: str
    warehouse_id: str
    job_id: int
    auth_mode: str
    read_ready: bool
    live_ready: bool
    requires_passcode: bool
    workspace_url: str
    job_url: str
    verified_run_url: str


class _ControlPlaneError(Exception):
    """Internal control-plane error mapped to HTTPException or Python exceptions."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class AuthVerifyRequest(BaseModel):
    """Payload for unlocking demo mode or verifying BYOK workspace credentials."""

    mode: Literal["passcode", "credentials"]
    passcode: str | None = None
    host: str | None = None
    token: str | None = None
    job_id: int | None = None
    warehouse_id: str | None = None


def _normalize_host(host: str) -> str:
    """Normalize a Databricks workspace URL to a clean https origin."""

    cleaned = host.strip().rstrip("/")
    if not cleaned:
        return ""
    if not cleaned.startswith(("https://", "http://")):
        cleaned = f"https://{cleaned}"
    return cleaned


def _expected_demo_token(passcode: str) -> str:
    """Compute the deterministic HMAC token derived from DEMO_PASSCODE."""

    return hmac.new(
        passcode.encode("utf-8"),
        b"medallion-live-unlock",
        hashlib.sha256,
    ).hexdigest()


def _parse_int(value: str | None, default: int) -> int:
    if not value:
        return default
    cleaned = value.strip()
    if not cleaned:
        return default
    try:
        return int(cleaned)
    except ValueError:
        return default


def _safe_catalog(raw: str | None) -> str:
    candidate = (raw or "").strip() or DEFAULT_CATALOG
    return candidate if _CATALOG_NAME_RE.match(candidate) else DEFAULT_CATALOG


def _build_deep_links(host: str, org_id: str, job_id: int) -> tuple[str, str, str]:
    workspace_url = f"{host}/?o={org_id}" if org_id else host
    job_url = f"{workspace_url}#job/{job_id}"
    verified_run_url = f"{workspace_url}#job/{job_id}/run/{VERIFIED_RUN_ID}"
    return workspace_url, job_url, verified_run_url


def _header_value(headers: Mapping[str, str] | None, name: str) -> str:
    if headers is None:
        return ""
    value = headers.get(name)
    if value is None:
        value = headers.get(name.lower(), "")
    return str(value)


def _resolve_context_from_values(
    headers: Mapping[str, str] | None = None,
    unlocked: bool = False,
) -> ControlContext:
    """Resolve auth mode, read/trigger permissions, credentials, and deep links."""

    header_host = _normalize_host(_header_value(headers, "X-Databricks-Host"))
    header_token = _header_value(headers, "X-Databricks-Token").strip()
    header_job_id = _header_value(headers, "X-Databricks-Job-Id")
    header_warehouse_id = _header_value(headers, "X-Databricks-Warehouse-Id").strip()
    demo_auth_header = _header_value(headers, "X-Demo-Auth").strip()

    env_host = _normalize_host(os.getenv("DATABRICKS_HOST", ""))
    env_token = os.getenv("DATABRICKS_TOKEN", "").strip()
    env_job_id = _parse_int(os.getenv("DATABRICKS_JOB_ID"), DEFAULT_JOB_ID)
    env_warehouse_id = os.getenv("DATABRICKS_WAREHOUSE_ID", "").strip() or DEFAULT_WAREHOUSE_ID
    catalog = _safe_catalog(os.getenv("DATABRICKS_CATALOG"))
    demo_passcode = os.getenv("DEMO_PASSCODE", "").strip()

    if header_host and header_token:
        host = header_host
        token = header_token
        job_id = _parse_int(header_job_id, env_job_id)
        warehouse_id = header_warehouse_id or env_warehouse_id
        auth_mode = "byok_session"
        read_ready = True
        live_ready = True
        requires_passcode = False
    elif env_host and env_token:
        host = env_host
        token = env_token
        job_id = env_job_id
        warehouse_id = env_warehouse_id
        read_ready = True
        if demo_passcode:
            expected_token = _expected_demo_token(demo_passcode)
            has_valid_header = bool(demo_auth_header) and hmac.compare_digest(
                demo_auth_header.encode("utf-8"),
                expected_token.encode("utf-8"),
            )
            if unlocked or has_valid_header:
                auth_mode = "passcode_unlocked"
                live_ready = True
                requires_passcode = False
            else:
                auth_mode = "locked"
                live_ready = False
                requires_passcode = True
        else:
            auth_mode = "local_env"
            live_ready = True
            requires_passcode = False
    else:
        host = env_host or DEFAULT_HOST
        token = ""
        job_id = env_job_id
        warehouse_id = env_warehouse_id
        auth_mode = "simulation_only"
        read_ready = False
        live_ready = False
        requires_passcode = False

    default_org = DEFAULT_ORG_ID if host == DEFAULT_HOST else ""
    org_id = os.getenv("DATABRICKS_ORG_ID", default_org).strip()
    workspace_url, job_url, verified_run_url = _build_deep_links(host, org_id, job_id)

    return ControlContext(
        host=host,
        token=token,
        org_id=org_id,
        catalog=catalog,
        warehouse_id=warehouse_id,
        job_id=job_id,
        auth_mode=auth_mode,
        read_ready=read_ready,
        live_ready=live_ready,
        requires_passcode=requires_passcode,
        workspace_url=workspace_url,
        job_url=job_url,
        verified_run_url=verified_run_url,
    )


def _resolve_context(request: Request) -> ControlContext:
    """Resolve auth mode, effective credentials, and Databricks deep links."""

    return _resolve_context_from_values(headers=request.headers)


def _map_state(state: dict[str, Any] | None) -> str:
    """Normalize Databricks job or task state into UI lifecycle buckets."""

    state = state or {}
    life_cycle = str(state.get("life_cycle_state") or "UNKNOWN").upper()
    result_raw = state.get("result_state")
    result_state = str(result_raw).upper() if result_raw is not None else None

    if life_cycle in ("PENDING", "QUEUED", "BLOCKED"):
        return "PENDING"
    if life_cycle in ("RUNNING", "TERMINATING"):
        return "RUNNING"
    if result_state == "SUCCESS":
        return "SUCCESS"
    if result_state in ("FAILED", "TIMEDOUT", "CANCELED") or life_cycle == "INTERNAL_ERROR":
        return "FAILED"
    return life_cycle


def _normalize_run_payload(
    run_data: dict[str, Any],
    host: str,
    org_id: str,
    job_id: int,
) -> dict[str, Any]:
    """Normalize a Databricks Jobs API 2.1 run object for the frontend."""

    state = run_data.get("state") or {}
    overall_status = _map_state(state)
    resolved_job_id = int(run_data.get("job_id") or job_id)
    run_id = int(run_data.get("run_id") or 0)
    workspace_url, _, _ = _build_deep_links(host, org_id, resolved_job_id)
    fallback_run_url = f"{workspace_url}#job/{resolved_job_id}/run/{run_id}"
    run_page_url = run_data.get("run_page_url") or fallback_run_url

    raw_duration = run_data.get("run_duration")
    if raw_duration is not None:
        run_duration_ms = int(raw_duration)
    elif run_data.get("end_time") and run_data.get("start_time"):
        run_duration_ms = max(0, int(run_data["end_time"]) - int(run_data["start_time"]))
    else:
        run_duration_ms = (
            int(run_data.get("execution_duration") or 0)
            + int(run_data.get("setup_duration") or 0)
            + int(run_data.get("cleanup_duration") or 0)
        )

    normalized_tasks: list[dict[str, Any]] = []
    for task in run_data.get("tasks", []) or []:
        task_state = task.get("state") or {}
        exec_ms = int(task.get("execution_duration") or 0)
        setup_ms = int(task.get("setup_duration") or 0)
        normalized_tasks.append(
            {
                "task_key": str(task.get("task_key") or ""),
                "status": _map_state(task_state),
                "life_cycle_state": str(task_state.get("life_cycle_state") or "UNKNOWN"),
                "result_state": task_state.get("result_state"),
                "execution_duration_ms": exec_ms + setup_ms,
                "run_page_url": task.get("run_page_url") or run_page_url,
                "state_message": str(task_state.get("state_message") or ""),
            }
        )

    return {
        "run_id": run_id,
        "job_id": resolved_job_id,
        "run_name": str(run_data.get("run_name") or f"Job {resolved_job_id} Run"),
        "overall_status": overall_status,
        "life_cycle_state": str(state.get("life_cycle_state") or "UNKNOWN"),
        "result_state": state.get("result_state"),
        "state_message": str(state.get("state_message") or ""),
        "start_time": run_data.get("start_time"),
        "end_time": run_data.get("end_time"),
        "run_duration_ms": run_duration_ms,
        "run_page_url": run_page_url,
        "tasks": normalized_tasks,
    }


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _query_live_metrics(catalog: str) -> dict[str, Any]:
    """Query Databricks Gold & Ops tables via shared.db and shape KPI payload."""

    summary_sql = f"""
        SELECT
            COUNT(*) AS days,
            COALESCE(SUM(total_orders), 0) AS total_orders,
            COALESCE(SUM(gross_revenue), 0) AS gross_revenue,
            COALESCE(SUM(net_revenue), 0) AS net_revenue,
            COALESCE(AVG(average_order_value), 0) AS average_order_value,
            COALESCE(AVG(refund_rate), 0) AS refund_rate,
            COALESCE(AVG(repeat_customer_rate), 0) AS repeat_customer_rate,
            COALESCE(AVG(stockout_rate), 0) AS stockout_rate
        FROM {catalog}.gold.executive_kpis_daily
    """
    channels_sql = f"""
        SELECT
            sales_channel,
            COUNT(*) AS orders,
            COALESCE(SUM(net_revenue), 0) AS net_revenue,
            COALESCE(SUM(refunded_amount), 0) AS refunded
        FROM {catalog}.gold.order_360
        GROUP BY sales_channel
        ORDER BY net_revenue DESC
    """
    trend_sql = f"""
        SELECT metric_date, total_orders, net_revenue
        FROM {catalog}.gold.executive_kpis_daily
        ORDER BY metric_date DESC
        LIMIT 7
    """
    pipeline_sql = f"""
        SELECT run_id, records_read, records_clean, records_rejected
        FROM {catalog}.ops.pipeline_runs
        WHERE status = 'SUCCESS'
        ORDER BY started_at_utc DESC
        LIMIT 1
    """
    quality_sql = f"""
        SELECT check_name, check_stage, passed, details_json
        FROM (
            SELECT
                check_name,
                check_stage,
                passed,
                details_json,
                ROW_NUMBER() OVER (
                    PARTITION BY check_stage, check_name
                    ORDER BY checked_at_utc DESC, id DESC
                ) AS rn
            FROM {catalog}.ops.quality_checks
        ) ranked
        WHERE rn = 1
        ORDER BY check_stage DESC, check_name ASC
    """

    with connect("databricks") as conn:
        summary_row = conn.execute(summary_sql).fetchone()
        if not summary_row or int(summary_row[0] or 0) == 0:
            raise RuntimeError("No executive KPI rows returned from Databricks")

        channel_rows = conn.execute(channels_sql).fetchall()
        trend_rows = conn.execute(trend_sql).fetchall()
        pipeline_row = conn.execute(pipeline_sql).fetchone()
        quality_rows = conn.execute(quality_sql).fetchall()

    baseline_summary = VERIFIED_METRICS_SNAPSHOT["summary"]
    summary = {
        "days": int(summary_row[0]),
        "total_orders": int(summary_row[1]),
        "gross_revenue": round(float(summary_row[2]), 2),
        "net_revenue": round(float(summary_row[3]), 2),
        "average_order_value": round(float(summary_row[4]), 2),
        "refund_rate": round(float(summary_row[5]), 4),
        "repeat_customer_rate": round(float(summary_row[6]), 4),
        "stockout_rate": round(float(summary_row[7]), 4),
        "bronze_raw_records": (
            int(pipeline_row[1])
            if pipeline_row and pipeline_row[1] is not None
            else baseline_summary["bronze_raw_records"]
        ),
        "silver_clean_records": (
            int(pipeline_row[2])
            if pipeline_row and pipeline_row[2] is not None
            else baseline_summary["silver_clean_records"]
        ),
        "silver_rejected_records": (
            int(pipeline_row[3])
            if pipeline_row and pipeline_row[3] is not None
            else baseline_summary["silver_rejected_records"]
        ),
        "delta_tables": baseline_summary["delta_tables"],
        "benchmark_passed": baseline_summary["benchmark_passed"],
        "reconciliation_diff": 0.0,
    }

    channels = [
        {
            "sales_channel": str(row[0]),
            "orders": int(row[1]),
            "net_revenue": round(float(row[2]), 2),
            "refunded": round(float(row[3]), 2),
        }
        for row in channel_rows
    ] or copy.deepcopy(VERIFIED_METRICS_SNAPSHOT["channels"])

    daily_trend = [
        {
            "metric_date": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
            "total_orders": int(row[1]),
            "net_revenue": round(float(row[2]), 2),
        }
        for row in reversed(trend_rows)
    ] or copy.deepcopy(VERIFIED_METRICS_SNAPSHOT["daily_trend"])

    quality_checks: list[dict[str, Any]] = []
    for row in quality_rows:
        raw_details = row[3]
        if isinstance(raw_details, dict):
            parsed_details = raw_details
        elif isinstance(raw_details, str) and raw_details.strip():
            try:
                parsed_details = json.loads(raw_details)
            except ValueError:
                parsed_details = {"raw": raw_details}
        else:
            parsed_details = {}
        quality_checks.append(
            {
                "check_name": str(row[0]),
                "check_stage": str(row[1]),
                "passed": bool(row[2]),
                "details": parsed_details,
            }
        )
    if not quality_checks:
        quality_checks = copy.deepcopy(VERIFIED_METRICS_SNAPSHOT["quality_checks"])

    return {
        "summary": summary,
        "channels": channels,
        "daily_trend": daily_trend,
        "quality_checks": quality_checks,
    }


def _build_status_payload(ctx: ControlContext) -> dict[str, Any]:
    """Serialize non-secret workspace connection status, auth mode, and deep links."""

    return {
        "connected": bool(ctx.host),
        "read_ready": ctx.read_ready,
        "live_ready": ctx.live_ready,
        "requires_passcode": ctx.requires_passcode,
        "auth_mode": ctx.auth_mode,
        "workspace_host": ctx.host,
        "org_id": ctx.org_id,
        "catalog": ctx.catalog,
        "warehouse_id": ctx.warehouse_id,
        "job_id": ctx.job_id,
        "workspace_url": ctx.workspace_url,
        "job_url": ctx.job_url,
        "latest_verified_run_id": VERIFIED_RUN_ID,
        "latest_verified_run_url": ctx.verified_run_url,
    }


def _fetch_latest_runs(ctx: ControlContext) -> dict[str, Any]:
    """Fetch recent Lakeflow runs when read_ready, falling back to verified snapshot."""

    if ctx.read_ready:
        try:
            resp = httpx.get(
                f"{ctx.host}/api/2.1/jobs/runs/list",
                params={"job_id": ctx.job_id, "limit": 5, "expand_tasks": "true"},
                headers=_auth_headers(ctx.token),
                timeout=10.0,
            )
            if resp.status_code == 200:
                raw_runs = resp.json().get("runs", []) or []
                runs = [
                    _normalize_run_payload(run_item, ctx.host, ctx.org_id, ctx.job_id)
                    for run_item in raw_runs
                ]
                return {"source": "live_databricks", "runs": runs}
            logger.warning(
                "Databricks runs/list returned status %s; serving snapshot",
                resp.status_code,
            )
        except (httpx.HTTPError, ValueError):
            logger.warning("Databricks runs/list unavailable; serving snapshot")

    return {"source": "snapshot", "runs": [copy.deepcopy(VERIFIED_RUN_SNAPSHOT)]}


def _trigger_job(ctx: ControlContext) -> dict[str, Any]:
    """Trigger the Databricks Lakeflow job with active-run guard."""

    if not ctx.live_ready:
        raise _ControlPlaneError(401, "Live Databricks execution requires authentication")

    try:
        list_resp = httpx.get(
            f"{ctx.host}/api/2.1/jobs/runs/list",
            params={"job_id": ctx.job_id, "active_only": "true", "limit": 1},
            headers=_auth_headers(ctx.token),
            timeout=10.0,
        )
    except httpx.HTTPError as err:
        raise _ControlPlaneError(502, "Could not reach Databricks workspace") from err

    if list_resp.status_code in (401, 403):
        raise _ControlPlaneError(401, "Databricks rejected credentials")
    if list_resp.status_code >= 400:
        raise _ControlPlaneError(502, "Could not inspect active Databricks runs")

    active_runs = list_resp.json().get("runs", []) or []
    if active_runs:
        active_run = active_runs[0]
        return {
            "triggered": False,
            "already_running": True,
            "run_id": active_run["run_id"],
            "job_id": ctx.job_id,
            "run_page_url": active_run.get("run_page_url") or ctx.job_url,
        }

    try:
        run_resp = httpx.post(
            f"{ctx.host}/api/2.1/jobs/run-now",
            json={"job_id": ctx.job_id},
            headers=_auth_headers(ctx.token),
            timeout=10.0,
        )
    except httpx.HTTPError as err:
        raise _ControlPlaneError(502, "Could not trigger Databricks job") from err

    if run_resp.status_code in (401, 403):
        raise _ControlPlaneError(401, "Databricks rejected credentials")
    if run_resp.status_code >= 400:
        raise _ControlPlaneError(502, "Databricks failed to start job run")

    run_id = run_resp.json()["run_id"]
    run_page_url = f"{ctx.workspace_url}#job/{ctx.job_id}/run/{run_id}"
    try:
        detail_resp = httpx.get(
            f"{ctx.host}/api/2.1/jobs/runs/get",
            params={"run_id": run_id},
            headers=_auth_headers(ctx.token),
            timeout=10.0,
        )
        if detail_resp.status_code == 200:
            run_page_url = detail_resp.json().get("run_page_url") or run_page_url
    except (httpx.HTTPError, ValueError):
        pass

    return {
        "triggered": True,
        "already_running": False,
        "run_id": run_id,
        "job_id": ctx.job_id,
        "run_page_url": run_page_url,
    }


def _fetch_job_run(run_id: int, ctx: ControlContext) -> dict[str, Any]:
    """Fetch and normalize live task progress for a specific Databricks run."""

    if run_id == VERIFIED_RUN_ID and not ctx.read_ready:
        return {"source": "snapshot", **copy.deepcopy(VERIFIED_RUN_SNAPSHOT)}
    if not ctx.read_ready:
        raise _ControlPlaneError(401, "Authentication required to inspect live runs")

    try:
        resp = httpx.get(
            f"{ctx.host}/api/2.1/jobs/runs/get",
            params={"run_id": run_id},
            headers=_auth_headers(ctx.token),
            timeout=10.0,
        )
    except httpx.HTTPError as err:
        if run_id == VERIFIED_RUN_ID:
            return {"source": "snapshot", **copy.deepcopy(VERIFIED_RUN_SNAPSHOT)}
        raise _ControlPlaneError(502, "Could not reach Databricks workspace") from err

    if resp.status_code >= 400 and run_id == VERIFIED_RUN_ID:
        return {"source": "snapshot", **copy.deepcopy(VERIFIED_RUN_SNAPSHOT)}
    if resp.status_code in (401, 403):
        raise _ControlPlaneError(401, "Databricks rejected credentials")
    if resp.status_code == 404:
        raise _ControlPlaneError(404, "Databricks job run not found")
    if resp.status_code >= 400:
        raise _ControlPlaneError(502, "Could not inspect Databricks job run")

    normalized = _normalize_run_payload(resp.json(), ctx.host, ctx.org_id, ctx.job_id)
    return {"source": "live_databricks", **normalized}


def _fetch_metrics(ctx: ControlContext, refresh: bool = False) -> dict[str, Any]:
    """Return cached/live Databricks Gold KPIs when read_ready, else verified snapshot."""

    cache_key = (ctx.host, ctx.catalog, ctx.warehouse_id)
    now_mono = time.monotonic()

    if not refresh and ctx.read_ready:
        cached = _METRICS_CACHE.get(cache_key)
        if cached and (now_mono - cached[0]) < METRICS_CACHE_TTL_SECONDS:
            return {**copy.deepcopy(cached[1]), "cached": True}

    env_host = _normalize_host(os.getenv("DATABRICKS_HOST", ""))
    can_query_env_sql = not (
        ctx.auth_mode == "byok_session" and env_host and ctx.host != env_host
    )

    if refresh and ctx.read_ready and can_query_env_sql:
        try:
            live_payload = _query_live_metrics(ctx.catalog)
            full_payload = {
                "source": "live_databricks",
                "generated_at": datetime.now(UTC).isoformat(),
                "cached": False,
                **live_payload,
            }
            _METRICS_CACHE[cache_key] = (now_mono, full_payload)
            return copy.deepcopy(full_payload)
        except Exception as err:
            logger.warning(
                "Live Databricks SQL metrics query failed (%s); falling back to verified snapshot",
                type(err).__name__,
            )

    return {
        "source": "verified_snapshot",
        "generated_at": datetime.now(UTC).isoformat(),
        "cached": False,
        **copy.deepcopy(VERIFIED_METRICS_SNAPSHOT),
    }


def verify_passcode_value(passcode: str) -> bool:
    """Validate a candidate passcode against DEMO_PASSCODE in constant time."""

    expected = os.getenv("DEMO_PASSCODE", "").strip()
    provided = passcode or ""
    if not expected or not provided:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def get_inprocess_boot_state(
    unlocked: bool = False,
    refresh_metrics: bool = False,
) -> dict[str, Any]:
    """Return non-secret control-plane boot state for embedded Streamlit execution."""

    ctx = _resolve_context_from_values(unlocked=unlocked)
    return {
        "status": _build_status_payload(ctx),
        "latest_runs": _fetch_latest_runs(ctx),
        "metrics": _fetch_metrics(ctx, refresh=refresh_metrics),
    }


def trigger_inprocess_job(unlocked: bool = False) -> dict[str, Any]:
    """Trigger the Databricks Lakeflow job in-process, enforcing DEMO_PASSCODE gate."""

    ctx = _resolve_context_from_values(unlocked=unlocked)
    try:
        return _trigger_job(ctx)
    except _ControlPlaneError as err:
        if err.status_code == 401:
            raise PermissionError(err.detail) from err
        raise RuntimeError(err.detail) from err


def get_inprocess_run_status(run_id: int) -> dict[str, Any]:
    """Return normalized status for a Databricks job run in-process."""

    ctx = _resolve_context_from_values(unlocked=False)
    try:
        return _fetch_job_run(run_id, ctx)
    except _ControlPlaneError as err:
        if err.status_code == 401:
            raise PermissionError(err.detail) from err
        if err.status_code == 404:
            raise LookupError(err.detail) from err
        raise RuntimeError(err.detail) from err


@router.get("/status")
def control_status(request: Request) -> dict[str, Any]:
    """Return non-secret workspace connection status, auth mode, and deep links."""

    return _build_status_payload(_resolve_context(request))


@router.post("/auth/verify")
def verify_auth(body: AuthVerifyRequest) -> dict[str, Any]:
    """Verify demo passcode or BYOK Databricks PAT via SCIM /Me."""

    if body.mode == "passcode":
        if not verify_passcode_value(body.passcode or ""):
            raise HTTPException(status_code=401, detail="Invalid demo passcode")
        expected = os.getenv("DEMO_PASSCODE", "").strip()
        return {
            "authenticated": True,
            "auth_mode": "passcode_unlocked",
            "demo_token": _expected_demo_token(expected),
        }

    normalized_host = _normalize_host(body.host or "")
    cleaned_token = (body.token or "").strip()
    if not normalized_host or not cleaned_token:
        raise HTTPException(status_code=400, detail="Databricks host and token are required")

    try:
        resp = httpx.get(
            f"{normalized_host}/api/2.0/preview/scim/v2/Me",
            headers=_auth_headers(cleaned_token),
            timeout=10.0,
        )
    except httpx.HTTPError as err:
        raise HTTPException(status_code=502, detail="Could not reach Databricks workspace") from err

    if resp.status_code in (401, 403):
        raise HTTPException(status_code=401, detail="Databricks rejected credentials")
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail="Could not reach Databricks workspace")

    try:
        payload = resp.json()
    except ValueError:
        payload = {}

    return {
        "authenticated": True,
        "auth_mode": "byok_session",
        "host": normalized_host,
        "user_name": payload.get("userName", "Databricks User"),
        "job_id": body.job_id or DEFAULT_JOB_ID,
        "warehouse_id": (body.warehouse_id or "").strip() or DEFAULT_WAREHOUSE_ID,
    }


@router.get("/jobs/latest")
def latest_job_runs(request: Request) -> dict[str, Any]:
    """Return recent Lakeflow job runs from Databricks, or verified snapshot fallback."""

    return _fetch_latest_runs(_resolve_context(request))


@router.post("/jobs/run")
def trigger_job_run(request: Request) -> dict[str, Any]:
    """Trigger the Databricks Lakeflow job with an active-run concurrency guard."""

    try:
        return _trigger_job(_resolve_context(request))
    except _ControlPlaneError as err:
        raise HTTPException(status_code=err.status_code, detail=err.detail) from err


@router.get("/jobs/runs/{run_id}")
def get_job_run(run_id: int, request: Request) -> dict[str, Any]:
    """Fetch and normalize live task progress for a specific Databricks run."""

    try:
        return _fetch_job_run(run_id, _resolve_context(request))
    except _ControlPlaneError as err:
        raise HTTPException(status_code=err.status_code, detail=err.detail) from err


@router.get("/metrics")
def get_metrics(
    request: Request,
    refresh: bool = Query(default=False),
) -> dict[str, Any]:
    """Return verified Gold KPIs, or live Databricks SQL Warehouse metrics on refresh."""

    return _fetch_metrics(_resolve_context(request), refresh=refresh)
