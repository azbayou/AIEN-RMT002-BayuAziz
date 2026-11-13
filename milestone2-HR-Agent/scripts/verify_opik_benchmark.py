#!/usr/bin/env python3
"""Programmatic verification of Opik dataset and benchmark experiments."""
from __future__ import annotations

import json
import os
import sys
from typing import Any
import urllib.parse

import opik

DEFAULT_OPIK_API_KEY = "8cBiKdJSLxbIknOM4S1Zg5HR2"
DEFAULT_OPIK_WORKSPACE = "azbayou"
DEFAULT_OPIK_PROJECT = "Milestone 2 - HR Agent"
DEFAULT_DATASET_NAME = "db-benchmark-suite"


def verify_opik_benchmark(
    api_key: str = DEFAULT_OPIK_API_KEY,
    workspace: str = DEFAULT_OPIK_WORKSPACE,
    project_name: str = DEFAULT_OPIK_PROJECT,
    dataset_name: str = DEFAULT_DATASET_NAME,
) -> dict[str, Any]:
    print(f"Connecting to Opik at workspace='{workspace}', project='{project_name}'...")
    os.environ["OPIK_API_KEY"] = api_key
    os.environ["OPIK_WORKSPACE"] = workspace
    os.environ["OPIK_PROJECT_NAME"] = project_name

    client = opik.Opik(
        api_key=api_key,
        workspace=workspace,
        project_name=project_name,
    )

    # 1. Verify Dataset
    print(f"\n[1/3] Verifying Opik dataset '{dataset_name}'...")
    dataset = client.get_dataset(name=dataset_name)
    assert dataset is not None, f"Dataset '{dataset_name}' not found in project '{project_name}'!"
    items_count = dataset.dataset_items_count
    print(f"  ✓ Dataset found: id={dataset.id}, name='{dataset.name}', items={items_count}")
    assert items_count >= 10, f"Expected at least 10 dataset items, found {items_count}"

    # 2. Verify Experiments
    print(f"\n[2/3] Verifying experiments 'db-local-postgres' and 'db-neondb-cloud'...")
    required_experiments = ["db-local-postgres", "db-neondb-cloud"]
    exp_details = {}

    for exp_name in required_experiments:
        try:
            exps = client.get_experiments_by_name(exp_name)
            matching = sorted(
                [e for e in exps if e.name == exp_name],
                key=lambda e: str(getattr(e, "created_at", "")),
            )
        except Exception as e:
            if "not found" in str(e).lower() or "ExperimentNotFound" in type(e).__name__:
                matching = []
            else:
                raise
        assert len(matching) > 0, f"Experiment '{exp_name}' not found in Opik project '{project_name}'!"
        exp = matching[-1]  # Latest experiment
        print(f"  ✓ Found experiment '{exp.name}': id={exp.id}")
        exp_details[exp_name] = exp

    # 3. Verify Metric Payloads
    print(f"\n[3/3] Verifying metric payloads in experiments...")
    required_metrics = ["latency_p50", "latency_p95", "latency_p99", "query_duration", "status_score"]

    for exp_name, exp in exp_details.items():
        # Fetch experiment items
        exp_items = exp.get_items()
        assert len(exp_items) > 0, f"No items recorded for experiment '{exp_name}'"
        print(f"  ✓ Experiment '{exp_name}' has {len(exp_items)} recorded item(s)")

        # Verify scores on items
        found_metrics = set()
        for item in exp_items:
            scores = None
            if isinstance(item, dict):
                scores = item.get("feedback_scores") or item.get("scores")
            else:
                scores = getattr(item, "feedback_scores", None) or getattr(item, "scores", None)

            if scores:
                for score in scores:
                    s_name = score.get("name") if isinstance(score, dict) else getattr(score, "name", None)
                    if s_name:
                        found_metrics.add(s_name)

        print(f"    Feedback metrics logged for '{exp_name}': {sorted(found_metrics)}")
        for m in required_metrics:
            assert m in found_metrics, f"Metric '{m}' missing from experiment '{exp_name}'!"
        print(f"    ✓ All required metrics {required_metrics} verified for '{exp_name}'.")

    local_id = exp_details["db-local-postgres"].id
    neon_id = exp_details["db-neondb-cloud"].id
    compare_param = urllib.parse.quote(json.dumps([local_id, neon_id]))
    compare_url = (
        f"https://www.comet.com/opik/{workspace}/experiments/{dataset.id}/compare?"
        f"experiments={compare_param}"
    )

    print("\n" + "=" * 80)
    print("ALL OPIK BENCHMARK ARTIFACTS VERIFIED SUCCESSFULLY!")
    print(f"Dataset:     {dataset.name} ({dataset.id})")
    print(f"Local Exp:   db-local-postgres ({local_id})")
    print(f"Neon Exp:    db-neondb-cloud ({neon_id})")
    print(f"Compare URL: {compare_url}")
    print("=" * 80)

    return {
        "status": "verified",
        "dataset_id": dataset.id,
        "local_exp_id": local_id,
        "neon_exp_id": neon_id,
        "compare_url": compare_url,
    }


if __name__ == "__main__":
    try:
        verify_opik_benchmark()
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌ Verification Assertion Failed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected Verification Error: {e}", file=sys.stderr)
        sys.exit(1)
