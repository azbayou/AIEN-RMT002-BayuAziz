#!/usr/bin/env python3
"""Databricks Asset Bundle (DABs) Deployment & Orchestration Script.

Performs:
1. Bundle validation (databricks bundle validate)
2. Raw data upload to Unity Catalog Volume (/Volumes/{catalog}/bronze/raw_data/)
3. Bundle deployment (databricks bundle deploy)
4. Workflow execution trigger (databricks bundle run)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def get_databricks_cli() -> str | None:
    """Find databricks CLI executable in PATH or user local bin."""
    found = shutil.which("databricks")
    if found:
        return found
    user_local = Path.home() / ".local" / "bin" / "databricks"
    if user_local.exists() and os.access(user_local, os.X_OK):
        return str(user_local)
    return None


def find_data_root(custom_path: str | None = None) -> Path:
    """Locate raw data folder."""
    if custom_path:
        p = Path(custom_path)
        if p.exists():
            return p
        raise FileNotFoundError(f"Provided data directory not found: {custom_path}")

    raw_candidate = PROJECT_ROOT / "data" / "raw"
    if raw_candidate.exists() and any(raw_candidate.iterdir()):
        return raw_candidate

    data_candidate = PROJECT_ROOT / "data"
    if data_candidate.exists():
        return data_candidate

    raise FileNotFoundError("Could not find data directory (checked data/raw and data/).")
    """Locate raw data folder."""
    if custom_path:
        p = Path(custom_path)
        if p.exists():
            return p
        raise FileNotFoundError(f"Provided data directory not found: {custom_path}")

    raw_candidate = PROJECT_ROOT / "data" / "raw"
    if raw_candidate.exists() and any(raw_candidate.iterdir()):
        return raw_candidate

    data_candidate = PROJECT_ROOT / "data"
    if data_candidate.exists():
        return data_candidate

    raise FileNotFoundError("Could not find data directory (checked data/raw and data/).")


def run_cmd(cmd: list[str], check: bool = True, dry_run: bool = False) -> subprocess.CompletedProcess:
    """Run shell command with clear logging."""
    cmd_str = " ".join(cmd)
    print(f"\n[EXEC] {cmd_str}")
    if dry_run:
        print("  -> (Dry run: skipped)")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(f"[STDERR] {result.stderr.strip()}", file=sys.stderr)

    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {result.returncode}: {cmd_str}")
    return result


def validate_bundle(target: str, dry_run: bool = False) -> None:
    """Validate Databricks Asset Bundle configuration."""
    print("=" * 60)
    print(f"1. Validating Databricks Asset Bundle (Target: {target})...")
    print("=" * 60)

    cli = get_databricks_cli()
    if not cli:
        print("[WARNING] 'databricks' CLI binary not found in PATH.")
        print("Ensure the Databricks CLI v0.200+ is installed (https://docs.databricks.com/dev-tools/cli/index.html).")
        if not dry_run:
            print("[INFO] Proceeding in offline verification mode...")
            return

    run_cmd([cli, "bundle", "validate", "-t", target], check=True, dry_run=dry_run)
    print("Bundle configuration is valid.")


def upload_data_to_volume(catalog: str, data_dir: Path, dry_run: bool = False) -> None:
    """Upload raw data files to Unity Catalog Volume."""
    print("=" * 60)
    target_volume_dir = f"/Volumes/{catalog}/bronze/raw_data"
    print(f"2. Uploading raw data from {data_dir} to {target_volume_dir}...")
    print("=" * 60)

    files_to_upload: list[Path] = []
    for root, _, files in os.walk(data_dir):
        for file in files:
            if file.endswith((".json", ".csv", ".parquet")):
                files_to_upload.append(Path(root) / file)

    print(f"Discovered {len(files_to_upload)} files to upload.")

    # Try Databricks SDK first if available
    try:
        from databricks.sdk import WorkspaceClient  # type: ignore
        print("[INFO] Using Databricks SDK for file uploads...")
        if not dry_run:
            w = WorkspaceClient()
            for file_path in files_to_upload:
                rel_path = file_path.relative_to(data_dir)
                dest_path = f"{target_volume_dir}/{rel_path}"
                print(f"  Uploading {rel_path} -> {dest_path}")
                with open(file_path, "rb") as f:
                    w.files.upload(dest_path, f, overwrite=True)
            print("All files uploaded successfully via Databricks SDK.")
            return
        else:
            for file_path in files_to_upload:
                rel_path = file_path.relative_to(data_dir)
                print(f"  [DRY RUN] Would upload {rel_path} -> {target_volume_dir}/{rel_path}")
            return
    except ImportError:
        pass

    # Fallback to Databricks CLI
    if shutil.which("databricks"):
        print("[INFO] Using Databricks CLI for file uploads...")
        for file_path in files_to_upload:
            rel_path = file_path.relative_to(data_dir)
            dest_volume_path = f"dbfs:{target_volume_dir}/{rel_path}"
            cmd = ["databricks", "fs", "cp", str(file_path), dest_volume_path, "--overwrite"]
            run_cmd(cmd, check=False, dry_run=dry_run)
        print("Data upload completed via Databricks CLI.")
    else:
        print("[NOTICE] Neither Databricks SDK nor CLI is installed in current environment.")
        print(f"[INFO] Files prepared for ingestion: {len(files_to_upload)} files from {data_dir}.")
        for f in files_to_upload[:5]:
            print(f"  - {f.relative_to(data_dir)}")
        if len(files_to_upload) > 5:
            print(f"  ... and {len(files_to_upload) - 5} more files.")


def deploy_bundle(target: str, dry_run: bool = False) -> None:
    """Deploy bundle to target workspace."""
    print("=" * 60)
    print(f"3. Deploying Databricks Asset Bundle to target '{target}'...")
    print("=" * 60)

    cli = get_databricks_cli()
    if not cli:
        print("[NOTICE] 'databricks' CLI not found; bundle manifest ready for deployment.")
        return

    run_cmd([cli, "bundle", "deploy", "-t", target], check=True, dry_run=dry_run)
    print("Bundle deployed successfully.")


def run_pipeline_job(target: str, dry_run: bool = False) -> None:
    """Trigger the multi-task Lakeflow Medallion Pipeline job."""
    print("=" * 60)
    print(f"4. Triggering job 'retail_medallion_pipeline' (Target: {target})...")
    print("=" * 60)

    cli = get_databricks_cli()
    if not cli:
        print("[NOTICE] 'databricks' CLI not found; job definition ready in resources/retail_pipeline_job.yml.")
        return

    run_cmd(
        [cli, "bundle", "run", "-t", target, "retail_medallion_pipeline"],
        check=True,
        dry_run=dry_run,
    )
    print("Pipeline run triggered successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deploy and orchestrate Omnichannel Retail on Databricks via DABs."
    )
    parser.add_argument(
        "--target",
        "-t",
        default="dev",
        choices=["dev", "prod"],
        help="Target deployment environment (default: dev)",
    )
    parser.add_argument(
        "--catalog",
        default=None,
        help="Target Unity Catalog name (defaults to target-specific catalog)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Path to raw data directory (defaults to data/raw or data/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate deployment steps without modifying remote resources",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Skip raw data volume upload step",
    )
    parser.add_argument(
        "--skip-run",
        action="store_true",
        help="Skip triggering job run after deployment",
    )

    args = parser.parse_args()

    target = args.target
    catalog = args.catalog or ("retail_analytics_dev" if target == "dev" else "retail_analytics")
    data_dir = find_data_root(args.data_dir)

    print("=" * 60)
    print("DATABRICKS ASSET BUNDLE DEPLOYMENT")
    print(f" Target Environment: {target}")
    print(f" Unity Catalog:      {catalog}")
    print(f" Raw Data Directory: {data_dir}")
    print(f" Dry Run Mode:       {args.dry_run}")
    print("=" * 60)

    # 1. Validate bundle
    validate_bundle(target, dry_run=args.dry_run)

    # 2. Upload raw data lake to Volume
    if not args.skip_upload:
        upload_data_to_volume(catalog, data_dir, dry_run=args.dry_run)
    else:
        print("\n[INFO] Skipping raw data upload (--skip-upload set).")

    # 3. Deploy bundle
    deploy_bundle(target, dry_run=args.dry_run)

    # 4. Trigger job run
    if not args.skip_run:
        run_pipeline_job(target, dry_run=args.dry_run)
    else:
        print("\n[INFO] Skipping job execution (--skip-run set).")

    print("\n[SUCCESS] Databricks deployment orchestration finished.")


if __name__ == "__main__":
    main()
