"""Sync historical traces from NeonDB to Opik Cloud with proper usage and token metrics."""
from __future__ import annotations

import json
import os
import opik
from psycopg.rows import dict_row
from src.config import get_settings
from src.domain import estimate_cost
from src.security import connect_db, stable_safety_id


def sync() -> None:
    settings = get_settings()
    if not settings.opik_api_key:
        print("OPIK_API_KEY tidak ditemukan di environment.")
        return
    if not settings.database_url:
        print("DATABASE_URL tidak ditemukan di environment.")
        return

    os.environ["OPIK_API_KEY"] = settings.opik_api_key
    if settings.opik_workspace:
        os.environ["OPIK_WORKSPACE"] = settings.opik_workspace
    if settings.opik_project_name:
        os.environ["OPIK_PROJECT_NAME"] = settings.opik_project_name

    client = opik.Opik(
        project_name=settings.opik_project_name,
        workspace=settings.opik_workspace,
        api_key=settings.opik_api_key,
        _use_batching=True,
    )

    with connect_db(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT trace_id, employee_id, payload, created_at
                FROM traces
                ORDER BY created_at ASC;
            """)
            rows = cur.fetchall()

    print(
        f"Menyinkronkan {len(rows)} traces ke Opik Cloud ({settings.opik_workspace or 'default'} / {settings.opik_project_name})..."
    )
    total_in = 0
    total_out = 0

    for row in rows:
        trace_id = row["trace_id"]
        emp_id = row["employee_id"]
        safety_id = stable_safety_id(emp_id)
        payload = row["payload"] or {}
        created_at = row["created_at"]
        payload_data = json.loads(payload) if isinstance(payload, str) else payload
        usage = payload_data.get("usage") or {}
        in_tok = int(usage.get("input_tokens") or 0)
        out_tok = int(usage.get("output_tokens") or 0)
        outcome = payload_data.get("outcome") or "answered"
        raw_cost = estimate_cost(
            in_tok,
            out_tok,
            settings.input_cost_per_1m,
            settings.output_cost_per_1m,
        )
        cost = round(raw_cost, 6) if raw_cost is not None else None
        total_in += in_tok
        total_out += out_tok

        trace_metadata = {
            "db_trace_id": trace_id,
            "safety_identifier": safety_id,
            "outcome": outcome,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "total_tokens": in_tok + out_tok,
        }
        if cost is not None:
            trace_metadata["cost"] = cost

        # Buat trace di Opik
        trace_obj = client.trace(
            name="HR Agent Turn",
            project_name=settings.opik_project_name,
            start_time=created_at,
            end_time=created_at,
            metadata=trace_metadata,
            tags=[outcome],
        )

        # Buat span LLM dengan OpenAI-formatted usage untuk kalkulasi token & cost Opik
        span_kwargs = {
            "name": "llm:respond",
            "type": "llm",
            "start_time": created_at,
            "end_time": created_at,
            "model": settings.agent_model or "agent",
            "provider": "openai",
            "usage": {
                "prompt_tokens": in_tok,
                "completion_tokens": out_tok,
                "total_tokens": in_tok + out_tok,
            },
        }
        if cost is not None:
            span_kwargs["total_cost"] = cost
        trace_obj.span(**span_kwargs)

    print("Mengirim data batch ke server Opik...")
    client.flush()
    print("Selesai! Seluruh log historis berhasil disinkronkan ke Opik Cloud.")
    print(f"- Total Traces: {len(rows)}")
    print(f"- Total Input Tokens (Prompt Tokens): {total_in:,}")
    print(f"- Total Output Tokens (Completion Tokens): {total_out:,}")
    total_raw_cost = estimate_cost(
        total_in,
        total_out,
        settings.input_cost_per_1m,
        settings.output_cost_per_1m,
    )
    if total_raw_cost is not None:
        print(f"- Total Estimasi Biaya (Cost): ${round(total_raw_cost, 6)} USD")
    else:
        print("- Total Estimasi Biaya (Cost): N/A (INPUT_COST_PER_1M / OUTPUT_COST_PER_1M belum dikonfigurasi)")


if __name__ == "__main__":
    sync()
