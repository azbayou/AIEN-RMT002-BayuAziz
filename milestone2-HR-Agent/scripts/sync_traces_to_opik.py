"""Sync historical traces from NeonDB to Opik Cloud with proper usage and token metrics."""
from __future__ import annotations

import json
import os
import psycopg
import opik
from src.config import get_settings
from src.repository import _connect_db


def sync() -> None:
    settings = get_settings()
    if not settings.opik_api_key:
        print("OPIK_API_KEY tidak ditemukan di environment.")
        return

    os.environ["OPIK_API_KEY"] = settings.opik_api_key
    os.environ["OPIK_WORKSPACE"] = settings.opik_workspace or "azbayou"
    os.environ["OPIK_PROJECT_NAME"] = settings.opik_project_name or "Milestone 2 - HR Agent"

    client = opik.Opik(
        project_name=settings.opik_project_name,
        workspace=settings.opik_workspace,
        api_key=settings.opik_api_key,
        _use_batching=True,
    )

    with _connect_db(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT trace_id, employee_id, payload, created_at
                FROM traces
                ORDER BY created_at ASC;
            """)
            rows = cur.fetchall()

    print(f"Menyinkronkan {len(rows)} traces ke Opik Cloud ({settings.opik_workspace} / {settings.opik_project_name})...")
    total_in = 0
    total_out = 0

    for row in rows:
        trace_id = row["trace_id"]
        emp_id = row["employee_id"]
        payload = row["payload"] or {}
        created_at = row["created_at"]
        payload_data = json.loads(payload) if isinstance(payload, str) else payload
        usage = payload_data.get("usage") or {}
        in_tok = int(usage.get("input_tokens") or 0)
        out_tok = int(usage.get("output_tokens") or 0)
        outcome = payload_data.get("outcome") or "answered"
        # Tarif GPT-6 Luna: $0.10/1M in, $0.50/1M out
        cost = round((in_tok * 0.10 + out_tok * 0.50) / 1_000_000, 6)
        total_in += in_tok
        total_out += out_tok

        # Buat trace di Opik
        trace_obj = client.trace(
            name="HR Agent Turn",
            project_name=settings.opik_project_name,
            start_time=created_at,
            end_time=created_at,
            metadata={
                "db_trace_id": trace_id,
                "employee_id": emp_id,
                "outcome": outcome,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "total_tokens": in_tok + out_tok,
                "cost": cost,
            },
            tags=[outcome],
        )

        # Buat span LLM dengan OpenAI-formatted usage untuk kalkulasi token & cost Opik
        trace_obj.span(
            name="llm:respond",
            type="llm",
            start_time=created_at,
            end_time=created_at,
            model=settings.agent_model or "gpt-6-luna",
            provider="openai",
            usage={
                "prompt_tokens": in_tok,
                "completion_tokens": out_tok,
                "total_tokens": in_tok + out_tok,
            },
            total_cost=cost,
        )

    print("Mengirim data batch ke server Opik...")
    client.flush()
    print("Selesai! Seluruh log historis berhasil disinkronkan ke Opik Cloud.")
    print(f"- Total Traces: {len(rows)}")
    print(f"- Total Input Tokens (Prompt Tokens): {total_in:,}")
    print(f"- Total Output Tokens (Completion Tokens): {total_out:,}")
    print(f"- Total Estimasi Biaya (Cost): ${round((total_in * 0.10 + total_out * 0.50) / 1_000_000, 6)} USD")


if __name__ == "__main__":
    sync()
