"""Omnichannel Retail Medallion Pipeline Airflow DAG."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

try:
    from airflow import DAG
    from airflow.exceptions import AirflowException
    from airflow.operators.python import PythonOperator
except ImportError:
    class AirflowException(Exception):
        pass
    DAG = None
    PythonOperator = None
from shared.db import connect

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data" / "raw" if (PROJECT_ROOT / "data" / "raw").exists() else PROJECT_ROOT / "data"


def task_validate_raw(**context) -> str:
    """1. Validasi keberadaan folder data dan manifest (jika ada), generate run_id."""
    run_id = f"run_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    print(f"Validating raw data for run: {run_id} using {DATA_ROOT}")

    required_folders = ["operational", "events", "inventory", "reference"]
    missing = [folder for folder in required_folders if not (DATA_ROOT / folder).exists()]
    if missing:
        raise AirflowException(f"Folder raw data tidak lengkap: {missing}")

    # Validasi checksum manifest jika file manifest.json ada
    manifest_path = DATA_ROOT / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if "files" in manifest and isinstance(manifest["files"], dict):
                for rel_path, expected_hash in manifest["files"].items():
                    target_file = DATA_ROOT / rel_path
                    if target_file.exists():
                        actual_hash = hashlib.sha256(target_file.read_bytes()).hexdigest()
                        if actual_hash != expected_hash:
                            raise AirflowException(
                                f"Checksum mismatch untuk file {rel_path}: expected {expected_hash}, got {actual_hash}"
                            )
            print(f"[{run_id}] Manifest validation passed.")
        except Exception as e:
            if isinstance(e, AirflowException):
                raise
            print(f"Warning: Manifest validation error: {e}")

    ti = context.get("ti")
    if ti:
        ti.xcom_push(key="pipeline_run_id", value=run_id)
    return run_id


def task_initialize_schema(**context) -> None:
    """2. Inisialisasi schema ops, bronze, silver, dan gold serta catat initial pipeline_runs."""
    ti = context.get("ti")
    run_id = ti.xcom_pull(task_ids="validate_raw", key="pipeline_run_id") if ti else None
    if not run_id:
        run_id = f"run_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"

    schema_files = [
        PROJECT_ROOT / "database" / "schemas" / "ops.sql",
        PROJECT_ROOT / "database" / "schemas" / "bronze.sql",
        PROJECT_ROOT / "database" / "schemas" / "silver.sql",
        PROJECT_ROOT / "database" / "schemas" / "gold.sql",
    ]
    with connect("local") as conn:
        for sql_file in schema_files:
            if sql_file.exists():
                print(f"Applying {sql_file.name}...")
                conn.execute(sql_file.read_text(encoding="utf-8"))

        conn.execute(
            """
            INSERT INTO ops.pipeline_runs (run_id, started_at_utc, status, current_stage)
            VALUES (%s, %s, 'RUNNING', 'initialize_schema')
            ON CONFLICT (run_id) DO UPDATE SET status = 'RUNNING', current_stage = 'initialize_schema'
            """,
            (run_id, datetime.now(UTC))
        )
        conn.commit()
    print(f"[{run_id}] Schema initialized and ops.pipeline_runs entry created.")


def task_load_bronze(**context) -> None:
    """3. Muat seluruh raw data ke Bronze."""
    from pipelines.bronze.build_bronze import load_bronze
    ti = context.get("ti")
    run_id = ti.xcom_pull(task_ids="validate_raw", key="pipeline_run_id") if ti else None
    if not run_id:
        raise AirflowException("Missing pipeline_run_id in XCom")
    load_bronze(run_id, target="local")


def task_build_silver(**context) -> None:
    """4. Transformasi data ke Silver (Clean vs Reject)."""
    from pipelines.silver.build_silver import build_silver
    ti = context.get("ti")
    run_id = ti.xcom_pull(task_ids="validate_raw", key="pipeline_run_id") if ti else None
    if not run_id:
        raise AirflowException("Missing pipeline_run_id in XCom")
    build_silver(run_id, target="local")


def task_quality_gate(**context) -> None:
    """5. Quality Gate: Cek kelayakan data sebelum lanjut ke Gold."""
    from pipelines.quality.checks import run_silver_quality_gate
    ti = context.get("ti")
    run_id = ti.xcom_pull(task_ids="validate_raw", key="pipeline_run_id") if ti else None
    if not run_id:
        raise AirflowException("Missing pipeline_run_id in XCom")
    try:
        run_silver_quality_gate(run_id, target="local")
    except Exception as e:
        with connect("local") as conn:
            conn.execute(
                "UPDATE ops.pipeline_runs SET status = 'FAILED', error_message = %s, current_stage = 'quality_gate' WHERE run_id = %s",
                (str(e), run_id)
            )
            conn.commit()
        raise AirflowException(f"Quality gate gagal: {e}") from e


def task_build_gold(**context) -> None:
    """6. Transformasi data ke Gold layer."""
    from pipelines.gold.build_gold import build_gold
    ti = context.get("ti")
    run_id = ti.xcom_pull(task_ids="validate_raw", key="pipeline_run_id") if ti else None
    if not run_id:
        raise AirflowException("Missing pipeline_run_id in XCom")
    build_gold(run_id, target="local")


def task_validate_gold_and_record_metadata(**context) -> None:
    """7. Validasi final Gold layer, rekonsiliasi metric, dan catat status SUCCESS di ops.pipeline_runs."""
    from pipelines.quality.checks import run_gold_validation_and_reconciliation
    ti = context.get("ti")
    run_id = ti.xcom_pull(task_ids="validate_raw", key="pipeline_run_id") if ti else None
    if not run_id:
        raise AirflowException("Missing pipeline_run_id in XCom")

    try:
        run_gold_validation_and_reconciliation(run_id, target="local")
        with connect("local") as conn:
            conn.execute(
                """
                UPDATE ops.pipeline_runs
                SET status = 'SUCCESS',
                    current_stage = 'completed',
                    completed_at_utc = %s
                WHERE run_id = %s
                """,
                (datetime.now(UTC), run_id)
            )
            conn.commit()
        print(f"[{run_id}] Pipeline berhasil diselesaikan dengan sukses!")
    except Exception as e:
        with connect("local") as conn:
            conn.execute(
                """
                UPDATE ops.pipeline_runs
                SET status = 'FAILED',
                    error_message = %s,
                    current_stage = 'validate_gold'
                WHERE run_id = %s
                """,
                (str(e), run_id)
            )
            conn.commit()
        raise AirflowException(f"Gold validation and reconciliation gagal: {e}") from e


if DAG is not None:
    # Definisi DAG
    with DAG(
        dag_id="omnichannel_retail_pipeline",
        start_date=datetime(2026, 1, 1, tzinfo=UTC),
        schedule=None,
        catchup=False,
        default_args={"owner": "student", "retries": 0},
        tags=["retail", "medallion", "bronze", "silver", "gold"],
    ) as dag:

        t_validate_raw = PythonOperator(
            task_id="validate_raw", python_callable=task_validate_raw
        )
        t_initialize_schema = PythonOperator(
            task_id="initialize_schema", python_callable=task_initialize_schema
        )
        t_load_bronze = PythonOperator(
            task_id="load_bronze", python_callable=task_load_bronze
        )
        t_build_silver = PythonOperator(
            task_id="build_silver", python_callable=task_build_silver
        )
        t_quality_gate = PythonOperator(
            task_id="quality_gate", python_callable=task_quality_gate
        )
        t_build_gold = PythonOperator(
            task_id="build_gold", python_callable=task_build_gold
        )
        t_validate_gold_and_record_metadata = PythonOperator(
            task_id="validate_gold_and_record_metadata",
            python_callable=task_validate_gold_and_record_metadata,
        )

        (
            t_validate_raw
            >> t_initialize_schema
            >> t_load_bronze
            >> t_build_silver
            >> t_quality_gate
            >> t_build_gold
            >> t_validate_gold_and_record_metadata
        )
else:
    dag = None
