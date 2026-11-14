#!/usr/bin/env python3
"""Database latency and concurrency benchmark comparing Local PostgreSQL and NeonDB.

Integrated with Comet Opik Evaluation / Experiments:
- Workspace: azbayou
- Project: Milestone 2 - HR Agent
- Dataset: db-benchmark-suite
- Experiments: db-local-postgres vs db-neondb-cloud (Side-by-Side Visual Comparison)

Workloads:
- R1: Connection handshake overhead (raw connect) vs ConnectionPool acquisition overhead.
- R1: Read latencies (token_hash lookup, personas & balances join, policy_chunks vector & lexical search).
- R1: Write latencies (traces JSONB insert, action_proposals insert).
- R2: Concurrency & Tail Latency Distribution (concurrent workloads reporting p50, p90, p95, p99).
- R3: Test Isolation & Data Cleanup (all benchmark writes use [BENCHMARK_TEST] prefix and are 100% cleaned up).
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import random
import statistics
import sys
import time
from typing import Any
import urllib.parse
import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

try:
    import opik
    from opik.evaluation import evaluate
    from opik.evaluation.metrics.score_result import ScoreResult

    HAS_OPIK = True
except ImportError:
    HAS_OPIK = False
    ScoreResult = None

DEFAULT_LOCAL_URL = os.getenv("LOCAL_DATABASE_URL", "")
DEFAULT_NEON_URL = os.getenv("DATABASE_URL", "")

DEFAULT_OPIK_API_KEY = os.getenv("OPIK_API_KEY", "")
DEFAULT_OPIK_WORKSPACE = "azbayou"
DEFAULT_OPIK_PROJECT = "Milestone 2 - HR Agent"
DEFAULT_DATASET_NAME = "db-benchmark-suite"

SAMPLE_TOKEN_HASH = "c90e5a12e7da750f330c78f3d3845a05b10001d8f6b56c218150ae0782b2215e"
TEST_EMPLOYEE_ID = "EMP-001"

OPIK_BENCHMARK_ITEMS: list[dict[str, Any]] = [
    {
        "workload_id": "raw_connect",
        "workload_name": "Raw Connection Handshake",
        "category": "connection",
        "description": "Measures raw connection establishment (TCP + TLS + SCRAM-SHA-256 + ping + close)",
        "iterations": 30,
    },
    {
        "workload_id": "pool_acquisition",
        "workload_name": "Connection Pool Acquisition",
        "category": "connection",
        "description": "Measures connection acquisition latency from a pre-warmed psycopg_pool",
        "iterations": 60,
    },
    {
        "workload_id": "read_token_lookup",
        "workload_name": "Single-row Auth Token Lookup",
        "category": "read",
        "description": "SELECT employee record by token_hash index scan",
        "iterations": 30,
    },
    {
        "workload_id": "read_personas_balances_join",
        "workload_name": "Personas & Leave Balances Join",
        "category": "read",
        "description": "SELECT employees JOIN leave_balances query",
        "iterations": 30,
    },
    {
        "workload_id": "search_vector_cosine",
        "workload_name": "Vector Similarity Search",
        "category": "search",
        "description": "pgvector 1536-dimensional cosine distance (<=>) search on policy_chunks",
        "iterations": 30,
    },
    {
        "workload_id": "search_lexical_tsquery",
        "workload_name": "Lexical Full-Text Search",
        "category": "search",
        "description": "tsvector ts_rank full-text search (@@) on policy_chunks",
        "iterations": 30,
    },
    {
        "workload_id": "write_trace_jsonb",
        "workload_name": "Trace JSONB Insert",
        "category": "write",
        "description": "INSERT into traces with structured JSONB audit payload and WAL commit",
        "iterations": 30,
    },
    {
        "workload_id": "write_action_proposal",
        "workload_name": "Action Proposal Insert",
        "category": "write",
        "description": "INSERT into action_proposals with relational columns and WAL commit",
        "iterations": 30,
    },
    {
        "workload_id": "concurrency_c5",
        "workload_name": "Concurrency Load (5 Workers)",
        "category": "concurrency",
        "description": "ThreadPoolExecutor concurrency with 5 workers running 50 mixed tasks",
        "concurrency_level": 5,
        "total_tasks": 50,
    },
    {
        "workload_id": "concurrency_c10",
        "workload_name": "Concurrency Load (10 Workers)",
        "category": "concurrency",
        "description": "ThreadPoolExecutor concurrency with 10 workers running 100 mixed tasks",
        "concurrency_level": 10,
        "total_tasks": 100,
    },
]


def compute_stats(latencies_ms: list[float]) -> dict[str, Any]:
    """Calculate descriptive statistics and percentiles (p50, p90, p95, p99)."""
    if not latencies_ms:
        return {
            "count": 0,
            "min_ms": 0.0,
            "max_ms": 0.0,
            "mean_ms": 0.0,
            "std_ms": 0.0,
            "p50_ms": 0.0,
            "p90_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
        }
    s = sorted(latencies_ms)
    n = len(s)

    def percentile(p: float) -> float:
        if n == 1:
            return s[0]
        k = (n - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return s[int(k)]
        return s[int(f)] * (c - k) + s[int(c)] * (k - f)

    mean_val = statistics.mean(latencies_ms)
    std_val = statistics.stdev(latencies_ms) if n > 1 else 0.0

    return {
        "count": n,
        "min_ms": round(s[0], 3),
        "max_ms": round(s[-1], 3),
        "mean_ms": round(mean_val, 3),
        "std_ms": round(std_val, 3),
        "p50_ms": round(percentile(50.0), 3),
        "p90_ms": round(percentile(90.0), 3),
        "p95_ms": round(percentile(95.0), 3),
        "p99_ms": round(percentile(99.0), 3),
    }


def get_sample_embedding(pool: ConnectionPool) -> tuple[str, int]:
    """Fetch an existing embedding vector and dimension from policy_chunks."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT embedding::text AS emb, vector_dims(embedding) AS dims FROM policy_chunks LIMIT 1"
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError("No policy_chunks found to sample embedding vector from.")
            return str(row["emb"]), int(row["dims"])


def benchmark_raw_connect(dsn: str, iterations: int) -> list[float]:
    """Measure raw connection handshake overhead (TCP + TLS + auth + ping + close)."""
    latencies: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)
    return latencies


def benchmark_pool_acquisition(pool: ConnectionPool, iterations: int) -> list[float]:
    """Measure connection pool acquisition overhead on a pre-warmed pool."""
    latencies: list[float] = []
    # Warmup
    for _ in range(2):
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()

    for _ in range(iterations):
        t0 = time.perf_counter()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)
    return latencies


def benchmark_single_row_lookup(pool: ConnectionPool, iterations: int) -> list[float]:
    """Benchmark SELECT token_hash authentication lookup."""
    latencies: list[float] = []
    query = """
        SELECT employee_id, display_name, role, department, manager_id
        FROM employees
        WHERE token_hash = %s
    """
    for _ in range(iterations):
        t0 = time.perf_counter()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (SAMPLE_TOKEN_HASH,))
                cur.fetchone()
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)
    return latencies


def benchmark_join_query(pool: ConnectionPool, iterations: int) -> list[float]:
    """Benchmark SELECT employees JOIN leave_balances query."""
    latencies: list[float] = []
    query = """
        SELECT e.employee_id, e.username, e.display_name, e.role, e.department,
               b.leave_type, b.available_days
        FROM employees e
        JOIN leave_balances b ON e.employee_id = b.employee_id
        ORDER BY e.employee_id, b.leave_type
    """
    for _ in range(iterations):
        t0 = time.perf_counter()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                cur.fetchall()
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)
    return latencies


def benchmark_vector_search(
    pool: ConnectionPool, sample_emb: str, dims: int, iterations: int
) -> list[float]:
    """Benchmark pgvector cosine similarity search on policy_chunks."""
    latencies: list[float] = []
    query = """
        SELECT chunk_id, document_id, title, section, version, effective_date, content,
               1 - (embedding <=> %s::vector) AS score
        FROM policy_chunks
        WHERE vector_dims(embedding) = %s AND effective_date <= CURRENT_DATE
        ORDER BY embedding <=> %s::vector, chunk_id
        LIMIT 5
    """
    for _ in range(iterations):
        t0 = time.perf_counter()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (sample_emb, dims, sample_emb))
                cur.fetchall()
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)
    return latencies


def benchmark_lexical_search(pool: ConnectionPool, iterations: int) -> list[float]:
    """Benchmark tsvector full-text similarity search on policy_chunks."""
    latencies: list[float] = []
    tsquery = "cuti | tahunan | sakit | permohonan"
    query = """
        SELECT chunk_id, document_id, title, section, version, effective_date, content,
               ts_rank(
                   to_tsvector('simple', title || ' ' || section || ' ' || content),
                   to_tsquery('simple', %s)
               ) AS score
        FROM policy_chunks
        WHERE effective_date <= CURRENT_DATE
          AND to_tsvector('simple', title || ' ' || section || ' ' || content)
              @@ to_tsquery('simple', %s)
        ORDER BY score DESC, chunk_id
        LIMIT 5
    """
    for _ in range(iterations):
        t0 = time.perf_counter()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (tsquery, tsquery))
                cur.fetchall()
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)
    return latencies


def benchmark_insert_trace(
    pool: ConnectionPool, session_id: str, iterations: int
) -> list[float]:
    """Benchmark INSERT into traces with JSONB payload and test tag."""
    latencies: list[float] = []
    query = """
        INSERT INTO traces (trace_id, employee_id, payload)
        VALUES (%s, %s, %s)
    """
    for i in range(iterations):
        trace_id = f"[BENCHMARK_TEST]:{session_id}:seq_trace_{i}"
        payload = {
            "test_marker": "[BENCHMARK_TEST]",
            "session_id": session_id,
            "iteration": i,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": f"Benchmark prompt message {i}"},
                {"role": "assistant", "content": "Benchmark assistant response text with metadata."},
            ],
            "usage": {"prompt_tokens": 120, "completion_tokens": 45, "total_tokens": 165},
            "status": "completed",
        }
        t0 = time.perf_counter()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (trace_id, TEST_EMPLOYEE_ID, Jsonb(payload)))
            conn.commit()
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)
    return latencies


def benchmark_insert_action_proposal(
    pool: ConnectionPool, session_id: str, iterations: int
) -> list[float]:
    """Benchmark INSERT into action_proposals with test tag."""
    latencies: list[float] = []
    query = """
        INSERT INTO action_proposals
            (proposal_id, employee_id, action_type, leave_type, start_date, end_date,
             business_days, reason, validation_summary, expires_at, requires_attachment)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    start_d = date(2026, 12, 1)
    end_d = date(2026, 12, 3)
    expires = datetime.now(timezone.utc) + timedelta(minutes=15)
    for i in range(iterations):
        prop_id = f"[BENCHMARK_TEST]:{session_id}:seq_prop_{i}"
        t0 = time.perf_counter()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query,
                    (
                        prop_id,
                        TEST_EMPLOYEE_ID,
                        "submit_leave",
                        "annual",
                        start_d,
                        end_d,
                        3,
                        f"Benchmark annual leave test proposal {i}",
                        ["[BENCHMARK_TEST]", f"iter_{i}"],
                        expires,
                        False,
                    ),
                )
            conn.commit()
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)
    return latencies


def benchmark_concurrency(
    pool: ConnectionPool,
    sample_emb: str,
    dims: int,
    session_id: str,
    concurrency_level: int,
    total_tasks: int,
) -> dict[str, Any]:
    """Measure latency and throughput under concurrent multi-threaded load.

    Simulates realistic application mix:
    - 25% authenticate token lookup
    - 25% join personas & balances
    - 20% vector similarity search
    - 15% lexical full-text search
    - 15% trace JSONB write
    """
    all_latencies: list[float] = []
    breakdown_latencies: dict[str, list[float]] = {
        "auth_lookup": [],
        "personas_join": [],
        "vector_search": [],
        "lexical_search": [],
        "trace_insert": [],
    }

    op_choices = [
        "auth_lookup",
        "personas_join",
        "vector_search",
        "lexical_search",
        "trace_insert",
    ]
    op_weights = [0.25, 0.25, 0.20, 0.15, 0.15]

    def worker_task(task_idx: int) -> tuple[str, float]:
        op = random.choices(op_choices, weights=op_weights, k=1)[0]
        t0 = time.perf_counter()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                if op == "auth_lookup":
                    cur.execute(
                        "SELECT employee_id, display_name FROM employees WHERE token_hash = %s",
                        (SAMPLE_TOKEN_HASH,),
                    )
                    cur.fetchone()
                elif op == "personas_join":
                    cur.execute(
                        """
                        SELECT e.employee_id, b.leave_type, b.available_days
                        FROM employees e
                        JOIN leave_balances b ON e.employee_id = b.employee_id
                        """
                    )
                    cur.fetchall()
                elif op == "vector_search":
                    cur.execute(
                        """
                        SELECT chunk_id, 1 - (embedding <=> %s::vector) AS score
                        FROM policy_chunks
                        WHERE vector_dims(embedding) = %s AND effective_date <= CURRENT_DATE
                        ORDER BY embedding <=> %s::vector, chunk_id
                        LIMIT 3
                        """,
                        (sample_emb, dims, sample_emb),
                    )
                    cur.fetchall()
                elif op == "lexical_search":
                    tsq = "cuti | tahunan"
                    cur.execute(
                        """
                        SELECT chunk_id
                        FROM policy_chunks
                        WHERE effective_date <= CURRENT_DATE
                          AND to_tsvector('simple', title || ' ' || section || ' ' || content)
                              @@ to_tsquery('simple', %s)
                        LIMIT 3
                        """,
                        (tsq,),
                    )
                    cur.fetchall()
                elif op == "trace_insert":
                    t_id = f"[BENCHMARK_TEST]:{session_id}:conc_{concurrency_level}_{task_idx}"
                    payload = {
                        "test_marker": "[BENCHMARK_TEST]",
                        "concurrency": concurrency_level,
                        "task_idx": task_idx,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    cur.execute(
                        "INSERT INTO traces (trace_id, employee_id, payload) VALUES (%s, %s, %s)",
                        (t_id, TEST_EMPLOYEE_ID, Jsonb(payload)),
                    )
                    conn.commit()
        t1 = time.perf_counter()
        return op, (t1 - t0) * 1000.0

    wall_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency_level) as executor:
        futures = [executor.submit(worker_task, i) for i in range(total_tasks)]
        for f in as_completed(futures):
            op, lat = f.result()
            all_latencies.append(lat)
            breakdown_latencies[op].append(lat)
    wall_duration = time.perf_counter() - wall_start

    overall_stats = compute_stats(all_latencies)
    throughput_rps = round(total_tasks / wall_duration, 2) if wall_duration > 0 else 0.0

    breakdown_stats = {
        op: compute_stats(lats) for op, lats in breakdown_latencies.items() if lats
    }

    return {
        "concurrency_level": concurrency_level,
        "total_tasks": total_tasks,
        "wall_duration_sec": round(wall_duration, 3),
        "throughput_rps": throughput_rps,
        "overall": overall_stats,
        "breakdown": breakdown_stats,
    }


def cleanup_test_data(pool: ConnectionPool) -> tuple[int, int]:
    """Clean up all [BENCHMARK_TEST] records and return (deleted_traces, deleted_proposals)."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM traces WHERE trace_id LIKE '[BENCHMARK_TEST]%'")
            del_traces = cur.rowcount
            cur.execute(
                "DELETE FROM action_proposals WHERE proposal_id LIKE '[BENCHMARK_TEST]%'"
            )
            del_proposals = cur.rowcount
        conn.commit()

        # Verification: Assert exactly 0 remaining
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS cnt FROM traces WHERE trace_id LIKE '[BENCHMARK_TEST]%'")
            rem_traces = cur.fetchone()["cnt"]
            cur.execute(
                "SELECT count(*) AS cnt FROM action_proposals WHERE proposal_id LIKE '[BENCHMARK_TEST]%'"
            )
            rem_proposals = cur.fetchone()["cnt"]

        if rem_traces != 0 or rem_proposals != 0:
            raise AssertionError(
                f"Cleanup verification failed! Remaining traces: {rem_traces}, proposals: {rem_proposals}"
            )

    return del_traces, del_proposals


# ==============================================================================
# Opik Evaluation & Experiment Integration
# ==============================================================================

def get_or_create_benchmark_dataset(
    client: opik.Opik, dataset_name: str
) -> Any:
    """Ensure benchmark dataset exists in Opik with canonical benchmark items."""
    dataset = client.get_or_create_dataset(
        name=dataset_name,
        description="Empirical Performance Benchmark Suite: Local PostgreSQL vs NeonDB Cloud",
    )
    # Check if dataset items need to be seeded or refreshed
    if dataset.dataset_items_count != len(OPIK_BENCHMARK_ITEMS):
        print(f"Syncing {len(OPIK_BENCHMARK_ITEMS)} benchmark items to Opik dataset '{dataset_name}'...")
        if dataset.dataset_items_count > 0:
            if hasattr(dataset, "clear"):
                dataset.clear()
            elif hasattr(dataset, "delete_items") and hasattr(dataset, "get_items"):
                items = dataset.get_items()
                ids_to_del = [
                    item.get("id") if isinstance(item, dict) else getattr(item, "id", None)
                    for item in items
                ]
                valid_ids = [i for i in ids_to_del if i is not None]
                if valid_ids:
                    dataset.delete_items(valid_ids)
            elif hasattr(dataset, "clear_items"):
                dataset.clear_items()
        dataset.insert(OPIK_BENCHMARK_ITEMS)
        print(f"Dataset '{dataset_name}' seeded successfully ({dataset.dataset_items_count} items).")
    return dataset


def cleanup_old_experiments(client: opik.Opik, experiment_names: list[str]) -> None:
    """Remove previous experiments with exact matching names to allow clean reruns."""
    for exp_name in experiment_names:
        try:
            exps = client.get_experiments_by_name(exp_name)
            target_ids = [
                e.get("id") if isinstance(e, dict) else getattr(e, "id", None)
                for e in exps
                if (e.get("name") if isinstance(e, dict) else getattr(e, "name", None)) == exp_name
            ]
            target_ids = [tid for tid in target_ids if tid is not None]
            if target_ids:
                client._rest_client.experiments.delete_experiments_by_id(ids=target_ids)
                print(f"Cleaned up {len(target_ids)} prior experiment(s) with name '{exp_name}'")
        except Exception:
            pass


# Opik Scorer Functions adhering to ScorerFunctionProtocol
def score_latency_p50(dataset_item: dict[str, Any], task_outputs: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    val = float(task_outputs.get("latency_p50", 0.0)) if task_outputs else 0.0
    return ScoreResult(name="latency_p50", value=round(val, 3), reason=f"p50: {val:.2f} ms")


def score_latency_p95(dataset_item: dict[str, Any], task_outputs: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    val = float(task_outputs.get("latency_p95", 0.0)) if task_outputs else 0.0
    return ScoreResult(name="latency_p95", value=round(val, 3), reason=f"p95: {val:.2f} ms")


def score_latency_p99(dataset_item: dict[str, Any], task_outputs: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    val = float(task_outputs.get("latency_p99", 0.0)) if task_outputs else 0.0
    return ScoreResult(name="latency_p99", value=round(val, 3), reason=f"p99: {val:.2f} ms")


def score_query_duration(dataset_item: dict[str, Any], task_outputs: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    val = float(task_outputs.get("query_duration", 0.0)) if task_outputs else 0.0
    return ScoreResult(name="query_duration", value=round(val, 3), reason=f"mean: {val:.2f} ms")


def score_status(dataset_item: dict[str, Any], task_outputs: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    is_success = (task_outputs.get("status") == "success") if task_outputs else False
    return ScoreResult(
        name="status_score",
        value=1.0 if is_success else 0.0,
        reason="SUCCESS (1.0)" if is_success else f"FAILED: {task_outputs.get('error', 'unknown') if task_outputs else 'no output'}",
    )


def run_benchmark_target_with_opik(
    name: str,
    dsn: str,
    iterations: int,
    concurrency_levels: list[int],
    opik_dataset: Any,
    opik_client: Any,
    experiment_name: str,
) -> tuple[dict[str, Any], Any]:
    """Execute target benchmark integrated with Opik evaluation and experiment logging."""
    print(f"\n{'='*70}\nSTARTING BENCHMARK RUN: {name.upper()} ({experiment_name})\n{'='*70}")
    session_id = uuid.uuid4().hex[:10]
    results: dict[str, Any] = {
        "target": name,
        "dsn_masked": dsn.split("@")[-1] if "@" in dsn else dsn,
        "session_id": session_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "concurrency": [],
    }

    # Verify server version
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            results["server_version"] = cur.fetchone()[0]
    print(f"Server version: {results['server_version']}")

    max_pool_size = max(max(concurrency_levels) + 5, 15)
    pool = ConnectionPool(
        conninfo=dsn,
        min_size=2,
        max_size=max_pool_size,
        kwargs={"row_factory": dict_row},
        open=True,
    )

    print("\nEnsuring clean baseline (pre-benchmark cleanup)...")
    pre_traces, pre_props = cleanup_test_data(pool)
    if pre_traces > 0 or pre_props > 0:
        print(f"  Cleaned up prior artifacts: {pre_traces} traces, {pre_props} proposals.")

    try:
        sample_emb, dims = get_sample_embedding(pool)
        results["embedding_dims"] = dims

        # Evaluation task for Opik dataset items
        def benchmark_task(dataset_item: dict[str, Any]) -> dict[str, Any]:
            w_id = dataset_item.get("workload_id")
            w_name = dataset_item.get("workload_name", w_id)
            print(f"  Executing Opik item [{w_id}]: {w_name}...")
            try:
                if w_id == "raw_connect":
                    iters = dataset_item.get("iterations", iterations)
                    lats = benchmark_raw_connect(dsn, iters)
                    stats = compute_stats(lats)
                    results["raw_connect"] = stats
                    return {
                        "workload_id": w_id,
                        "workload_name": w_name,
                        "latency_p50": stats["p50_ms"],
                        "latency_p95": stats["p95_ms"],
                        "latency_p99": stats["p99_ms"],
                        "query_duration": stats["mean_ms"],
                        "status": "success",
                        "stats": stats,
                    }

                elif w_id == "pool_acquisition":
                    iters = dataset_item.get("iterations", iterations * 2)
                    lats = benchmark_pool_acquisition(pool, iters)
                    stats = compute_stats(lats)
                    results["pool_acquisition"] = stats
                    return {
                        "workload_id": w_id,
                        "workload_name": w_name,
                        "latency_p50": stats["p50_ms"],
                        "latency_p95": stats["p95_ms"],
                        "latency_p99": stats["p99_ms"],
                        "query_duration": stats["mean_ms"],
                        "status": "success",
                        "stats": stats,
                    }

                elif w_id == "read_token_lookup":
                    iters = dataset_item.get("iterations", iterations)
                    lats = benchmark_single_row_lookup(pool, iters)
                    stats = compute_stats(lats)
                    results["read_token_lookup"] = stats
                    return {
                        "workload_id": w_id,
                        "workload_name": w_name,
                        "latency_p50": stats["p50_ms"],
                        "latency_p95": stats["p95_ms"],
                        "latency_p99": stats["p99_ms"],
                        "query_duration": stats["mean_ms"],
                        "status": "success",
                        "stats": stats,
                    }

                elif w_id == "read_personas_balances_join":
                    iters = dataset_item.get("iterations", iterations)
                    lats = benchmark_join_query(pool, iters)
                    stats = compute_stats(lats)
                    results["read_personas_balances_join"] = stats
                    return {
                        "workload_id": w_id,
                        "workload_name": w_name,
                        "latency_p50": stats["p50_ms"],
                        "latency_p95": stats["p95_ms"],
                        "latency_p99": stats["p99_ms"],
                        "query_duration": stats["mean_ms"],
                        "status": "success",
                        "stats": stats,
                    }

                elif w_id == "search_vector_cosine":
                    iters = dataset_item.get("iterations", iterations)
                    lats = benchmark_vector_search(pool, sample_emb, dims, iters)
                    stats = compute_stats(lats)
                    results["search_vector_cosine"] = stats
                    return {
                        "workload_id": w_id,
                        "workload_name": w_name,
                        "latency_p50": stats["p50_ms"],
                        "latency_p95": stats["p95_ms"],
                        "latency_p99": stats["p99_ms"],
                        "query_duration": stats["mean_ms"],
                        "status": "success",
                        "stats": stats,
                    }

                elif w_id == "search_lexical_tsquery":
                    iters = dataset_item.get("iterations", iterations)
                    lats = benchmark_lexical_search(pool, iters)
                    stats = compute_stats(lats)
                    results["search_lexical_tsquery"] = stats
                    return {
                        "workload_id": w_id,
                        "workload_name": w_name,
                        "latency_p50": stats["p50_ms"],
                        "latency_p95": stats["p95_ms"],
                        "latency_p99": stats["p99_ms"],
                        "query_duration": stats["mean_ms"],
                        "status": "success",
                        "stats": stats,
                    }

                elif w_id == "write_trace_jsonb":
                    iters = dataset_item.get("iterations", iterations)
                    lats = benchmark_insert_trace(pool, session_id, iters)
                    stats = compute_stats(lats)
                    results["write_trace_jsonb"] = stats
                    return {
                        "workload_id": w_id,
                        "workload_name": w_name,
                        "latency_p50": stats["p50_ms"],
                        "latency_p95": stats["p95_ms"],
                        "latency_p99": stats["p99_ms"],
                        "query_duration": stats["mean_ms"],
                        "status": "success",
                        "stats": stats,
                    }

                elif w_id == "write_action_proposal":
                    iters = dataset_item.get("iterations", iterations)
                    lats = benchmark_insert_action_proposal(pool, session_id, iters)
                    stats = compute_stats(lats)
                    results["write_action_proposal"] = stats
                    return {
                        "workload_id": w_id,
                        "workload_name": w_name,
                        "latency_p50": stats["p50_ms"],
                        "latency_p95": stats["p95_ms"],
                        "latency_p99": stats["p99_ms"],
                        "query_duration": stats["mean_ms"],
                        "status": "success",
                        "stats": stats,
                    }

                elif w_id == "concurrency_c5":
                    c_level = dataset_item.get("concurrency_level", 5)
                    t_tasks = dataset_item.get("total_tasks", 50)
                    c_res = benchmark_concurrency(pool, sample_emb, dims, session_id, c_level, t_tasks)
                    results["concurrency"].append(c_res)
                    ov = c_res["overall"]
                    return {
                        "workload_id": w_id,
                        "workload_name": w_name,
                        "latency_p50": ov["p50_ms"],
                        "latency_p95": ov["p95_ms"],
                        "latency_p99": ov["p99_ms"],
                        "query_duration": ov["mean_ms"],
                        "throughput_rps": c_res["throughput_rps"],
                        "status": "success",
                        "stats": ov,
                    }

                elif w_id == "concurrency_c10":
                    c_level = dataset_item.get("concurrency_level", 10)
                    t_tasks = dataset_item.get("total_tasks", 100)
                    c_res = benchmark_concurrency(pool, sample_emb, dims, session_id, c_level, t_tasks)
                    results["concurrency"].append(c_res)
                    ov = c_res["overall"]
                    return {
                        "workload_id": w_id,
                        "workload_name": w_name,
                        "latency_p50": ov["p50_ms"],
                        "latency_p95": ov["p95_ms"],
                        "latency_p99": ov["p99_ms"],
                        "query_duration": ov["mean_ms"],
                        "throughput_rps": c_res["throughput_rps"],
                        "status": "success",
                        "stats": ov,
                    }

                else:
                    raise ValueError(f"Unknown workload_id: {w_id}")

            except Exception as exc:
                print(f"    ERROR executing [{w_id}]: {exc}")
                return {
                    "workload_id": w_id,
                    "workload_name": w_name,
                    "latency_p50": 0.0,
                    "latency_p95": 0.0,
                    "latency_p99": 0.0,
                    "query_duration": 0.0,
                    "status": "error",
                    "error": str(exc),
                }

        # Run Opik Evaluation
        print(f"\nLaunching Opik Experiment: '{experiment_name}'...")
        eval_result = evaluate(
            dataset=opik_dataset,
            task=benchmark_task,
            scoring_functions=[
                score_latency_p50,
                score_latency_p95,
                score_latency_p99,
                score_query_duration,
                score_status,
            ],
            experiment_name=experiment_name,
            experiment_config={
                "target_database": name,
                "dsn_endpoint": results["dsn_masked"],
                "server_version": results["server_version"],
                "embedding_dimensions": dims,
                "iterations": iterations,
                "concurrency_levels": concurrency_levels,
            },
            experiment_tags=["database-benchmark", name],
            task_threads=1,
            verbose=1,
        )

        results["concurrency"].sort(key=lambda x: x["concurrency_level"])

        results["opik_experiment"] = {
            "experiment_id": eval_result.experiment_id,
            "experiment_name": eval_result.experiment_name,
            "experiment_url": eval_result.experiment_url,
        }

    finally:
        print("\nExecuting test isolation data cleanup & verification...")
        del_traces, del_props = cleanup_test_data(pool)
        results["cleanup"] = {
            "deleted_traces": del_traces,
            "deleted_action_proposals": del_props,
            "remaining_test_records": 0,
            "verified": True,
        }
        print(
            f"  Successfully deleted {del_traces} test traces and {del_props} test proposals. "
            f"Verified 0 remaining test records."
        )
        pool.close()

    results["completed_at"] = datetime.now(timezone.utc).isoformat()
    return results, eval_result


def print_comparison_table(
    local_res: dict[str, Any], neon_res: dict[str, Any], compare_url: str | None = None
) -> None:
    """Print human-readable comparative summary table to stdout."""
    print("\n" + "=" * 94)
    print(f"{'DATABASE LATENCY & CONCURRENCY BENCHMARK SUMMARY':^94}")
    print("=" * 94)

    header = f"{'Metric / Workload':<36} | {'Local PG (p50 / mean)':<26} | {'NeonDB (p50 / mean)':<26}"
    print(header)
    print("-" * 94)

    metrics = [
        ("Raw Connect Handshake", "raw_connect"),
        ("Pool Connection Acquisition", "pool_acquisition"),
        ("Read: Token Hash Lookup", "read_token_lookup"),
        ("Read: Personas + Balances Join", "read_personas_balances_join"),
        ("Search: Vector (pgvector cosine)", "search_vector_cosine"),
        ("Search: Lexical (tsvector)", "search_lexical_tsquery"),
        ("Write: Trace JSONB Insert", "write_trace_jsonb"),
        ("Write: Action Proposal Insert", "write_action_proposal"),
    ]

    for label, key in metrics:
        l_stat = local_res.get(key, {})
        n_stat = neon_res.get(key, {})
        l_str = f"{l_stat.get('p50_ms', 0):.2f}ms / {l_stat.get('mean_ms', 0):.2f}ms"
        n_str = f"{n_stat.get('p50_ms', 0):.2f}ms / {n_stat.get('mean_ms', 0):.2f}ms"
        print(f"{label:<36} | {l_str:<26} | {n_str:<26}")

    print("-" * 94)
    print(f"{'CONCURRENCY & TAIL LATENCIES (OVERALL)':^94}")
    print("-" * 94)
    print(
        f"{'Concurrency Load':<22} | {'Throughput (rps)':<18} | {'p50 (ms)':<10} | {'p90 (ms)':<10} | {'p95 (ms)':<10} | {'p99 (ms)':<10}"
    )
    print("-" * 94)

    for l_c in local_res.get("concurrency", []):
        c_lvl = l_c["concurrency_level"]
        t_rps = l_c["throughput_rps"]
        ov = l_c["overall"]
        print(
            f"Local (c={c_lvl:<2})             | {t_rps:<18.1f} | {ov['p50_ms']:<10.2f} | {ov['p90_ms']:<10.2f} | {ov['p95_ms']:<10.2f} | {ov['p99_ms']:<10.2f}"
        )

    for n_c in neon_res.get("concurrency", []):
        c_lvl = n_c["concurrency_level"]
        t_rps = n_c["throughput_rps"]
        ov = n_c["overall"]
        print(
            f"NeonDB (c={c_lvl:<2})            | {t_rps:<18.1f} | {ov['p50_ms']:<10.2f} | {ov['p90_ms']:<10.2f} | {ov['p95_ms']:<10.2f} | {ov['p99_ms']:<10.2f}"
        )

    if compare_url:
        print("=" * 94)
        print(f"OPIK VISUAL SIDE-BY-SIDE EXPERIMENT COMPARISON URL:")
        print(f"  {compare_url}")
    print("=" * 94)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Empirical Latency & Concurrency Benchmark: Local PostgreSQL vs NeonDB with Opik Experiments"
    )
    parser.add_argument("--local-url", default=DEFAULT_LOCAL_URL, help="Local PostgreSQL DSN")
    parser.add_argument("--neon-url", default=DEFAULT_NEON_URL, help="NeonDB DSN")
    parser.add_argument(
        "--target",
        choices=["both", "local", "neon"],
        default="both",
        help="Target database(s) to benchmark",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=30,
        help="Number of iterations for sequential benchmarks (default: 30)",
    )
    parser.add_argument(
        "--concurrency",
        type=str,
        default="5,10",
        help="Comma-separated concurrency worker levels (default: 5,10)",
    )
    parser.add_argument(
        "--output",
        default="scripts/benchmark_results.json",
        help="Output JSON results file path",
    )
    parser.add_argument(
        "--dataset-name",
        default=DEFAULT_DATASET_NAME,
        help="Opik evaluation dataset name",
    )
    parser.add_argument(
        "--opik-api-key",
        default=os.getenv("OPIK_API_KEY", DEFAULT_OPIK_API_KEY),
        help="Opik API Key",
    )
    parser.add_argument(
        "--opik-workspace",
        default=os.getenv("OPIK_WORKSPACE", DEFAULT_OPIK_WORKSPACE),
        help="Opik Workspace",
    )
    parser.add_argument(
        "--opik-project",
        default=os.getenv("OPIK_PROJECT_NAME", DEFAULT_OPIK_PROJECT),
        help="Opik Project Name",
    )
    parser.add_argument(
        "--no-opik",
        action="store_true",
        help="Disable Opik Evaluation / Experiments integration",
    )

    args = parser.parse_args()
    concurrency_levels = [int(x.strip()) for x in args.concurrency.split(",") if x.strip()]

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    benchmark_meta = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "iterations": args.iterations,
        "concurrency_levels": concurrency_levels,
    }

    full_results: dict[str, Any] = {"metadata": benchmark_meta}

    use_opik = HAS_OPIK and not args.no_opik

    opik_client = None
    opik_dataset = None
    compare_url = None

    if use_opik:
        # Set Opik environment variables for evaluate()
        os.environ["OPIK_API_KEY"] = args.opik_api_key
        os.environ["OPIK_WORKSPACE"] = args.opik_workspace
        os.environ["OPIK_PROJECT_NAME"] = args.opik_project

        opik_client = opik.Opik(
            api_key=args.opik_api_key,
            workspace=args.opik_workspace,
            project_name=args.opik_project,
        )
        print(f"Connecting to Opik (workspace: '{args.opik_workspace}', project: '{args.opik_project}')...")
        opik_dataset = get_or_create_benchmark_dataset(opik_client, args.dataset_name)

        # Cleanup existing experiments if rerunning
        exp_names = []
        if args.target in ("both", "local"):
            exp_names.append("db-local-postgres")
        if args.target in ("both", "neon"):
            exp_names.append("db-neondb-cloud")
        cleanup_old_experiments(opik_client, exp_names)

    local_eval = None
    neon_eval = None

    if args.target in ("both", "local"):
        if use_opik:
            local_res, local_eval = run_benchmark_target_with_opik(
                "local_postgres",
                args.local_url,
                args.iterations,
                concurrency_levels,
                opik_dataset,
                opik_client,
                "db-local-postgres",
            )
        else:
            raise NotImplementedError("Opik integration is required.")
        full_results["local_postgres"] = local_res

    if args.target in ("both", "neon"):
        if use_opik:
            neon_res, neon_eval = run_benchmark_target_with_opik(
                "neondb",
                args.neon_url,
                args.iterations,
                concurrency_levels,
                opik_dataset,
                opik_client,
                "db-neondb-cloud",
            )
        else:
            raise NotImplementedError("Opik integration is required.")
        full_results["neondb"] = neon_res

    if use_opik and opik_dataset:
        full_results["opik"] = {
            "workspace": args.opik_workspace,
            "project_name": args.opik_project,
            "dataset_name": args.dataset_name,
            "dataset_id": opik_dataset.id,
            "experiments": {},
        }
        if local_eval:
            full_results["opik"]["experiments"]["local_postgres"] = {
                "name": local_eval.experiment_name,
                "id": local_eval.experiment_id,
                "url": local_eval.experiment_url,
            }
        if neon_eval:
            full_results["opik"]["experiments"]["neondb"] = {
                "name": neon_eval.experiment_name,
                "id": neon_eval.experiment_id,
                "url": neon_eval.experiment_url,
            }

        if local_eval and neon_eval:
            compare_params = urllib.parse.quote(
                json.dumps([local_eval.experiment_id, neon_eval.experiment_id])
            )
            compare_url = (
                f"https://www.comet.com/opik/{args.opik_workspace}/experiments/"
                f"{opik_dataset.id}/compare?experiments={compare_params}"
            )
            full_results["opik"]["compare_url"] = compare_url

    if args.target == "both":
        print_comparison_table(
            full_results["local_postgres"], full_results["neondb"], compare_url=compare_url
        )

    # Save results to JSON
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(full_results, f, indent=2)
    print(f"\nRaw benchmark results successfully saved to: {output_path}")


if __name__ == "__main__":
    main()
