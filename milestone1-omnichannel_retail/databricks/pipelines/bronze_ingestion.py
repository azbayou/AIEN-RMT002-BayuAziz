"""PySpark Bronze Ingestion Pipeline for Databricks Unity Catalog.

Reads raw operational, event, inventory, and reference data from Unity Catalog Volume
(/Volumes/{catalog}/bronze/raw_data/) or local fallback, computes SHA-256 checksums,
and ingests raw JSON/CSV records into {catalog}.bronze.raw_records.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
except NameError:
    PROJECT_ROOT = Path.cwd()

KNOWN_ID_COLS: dict[str, str] = {
    "orders.json": "order_id",
    "order_items.json": "order_item_id",
    "order_promotions.json": "source_row_id",
    "customers.json": "customer_id",
    "customer_profiles.json": "source_row_id",
    "customer_addresses.json": "source_row_id",
    "products.json": "product_id",
    "product_categories.json": "source_row_id",
    "promotions.json": "promotion_id",
    "sales_channels.json": "channel_id",
    "stores.json": "store_id",
    "payment_events.json": "event_id",
    "refund_events.json": "event_id",
    "return_events.json": "event_id",
    "support_events.json": "event_id",
    "web_events.json": "event_id",
    "city_reference.json": "city_id",
}


def get_spark_session() -> Any:
    """Retrieve existing SparkSession or initialize one."""
    try:
        from pyspark.sql import SparkSession

        return SparkSession.builder.appName("bronze_ingestion").getOrCreate()
    except ImportError:
        print("Note: pyspark not installed. Running in standalone local inspection mode.")
        return None
    except Exception as exc:
        print(f"Warning: SparkSession could not be initialized: {exc}")
        return None


def resolve_data_root(catalog: str, custom_data_root: str | None = None) -> Path:
    """Resolve data landing path: custom path -> UC Volume -> data/raw -> data."""
    if custom_data_root:
        custom_path = Path(custom_data_root)
        if custom_path.exists():
            return custom_path

    # Check Databricks Unity Catalog Volume path
    volume_path = Path(f"/Volumes/{catalog}/bronze/raw_data")
    if volume_path.exists() and volume_path.is_dir():
        for item in volume_path.rglob("*"):
            if (
                item.is_file()
                and not item.name.startswith(".")
                and item.suffix.lower() in {".json", ".csv", ".jsonl"}
            ):
                return volume_path

    # Local fallback to data/raw
    raw_path = PROJECT_ROOT / "data" / "raw"
    if raw_path.exists() and raw_path.is_dir():
        for item in raw_path.rglob("*"):
            if (
                item.is_file()
                and not item.name.startswith(".")
                and item.suffix.lower() in {".json", ".csv", ".jsonl"}
            ):
                return raw_path

    # Fallback to local data/
    return PROJECT_ROOT / "data"


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 checksum of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def extract_json_row_id(item: dict[str, Any], id_col: str | None) -> str | None:
    """Extract natural or source row ID from JSON record."""
    if id_col and item.get(id_col) is not None:
        return str(item[id_col])
    if item.get("source_row_id") is not None:
        return str(item["source_row_id"])
    if item.get("id") is not None:
        return str(item["id"])
    for k, v in item.items():
        if k.endswith("_id") and v is not None:
            return str(v)
    return None


def extract_csv_row_id(row: dict[str, Any], id_col: str | None) -> str | None:
    """Extract row identifier from CSV record."""
    if id_col and row.get(id_col) is not None:
        return str(row[id_col])
    if row.get("source_row_id") is not None:
        return str(row["source_row_id"])
    if row.get("id") is not None:
        return str(row["id"])
    return None


def discover_files(data_root: Path) -> list[tuple[str, Path]]:
    """Discover all raw files organized by category subfolders."""
    target_categories = ["operational", "events", "inventory", "reference"]
    if data_root.exists() and data_root.is_dir():
        for item in sorted(data_root.iterdir()):
            if (
                item.is_dir()
                and not item.name.startswith(".")
                and item.name not in target_categories
                and item.name != "raw"
            ):
                target_categories.append(item.name)

    files_to_process: list[tuple[str, Path]] = []
    for category in target_categories:
        cat_dir = data_root / category
        if not cat_dir.exists() or not cat_dir.is_dir():
            continue
        for file_path in sorted(cat_dir.rglob("*")):
            if (
                file_path.is_file()
                and not file_path.name.startswith(".")
                and file_path.suffix.lower() in {".json", ".csv", ".jsonl"}
            ):
                files_to_process.append((category, file_path))

    return files_to_process


def run_bronze_ingestion(
    run_id: str,
    catalog: str = "retail_analytics",
    data_root: str | None = None,
    spark: Any = None,
) -> dict[str, int]:
    """Execute Bronze ingestion on Databricks Delta Lake."""
    actual_data_root = resolve_data_root(catalog, data_root)
    print(f"[{run_id}] Starting Databricks Bronze Ingestion from: {actual_data_root}")
    print(f"[{run_id}] Target Catalog: {catalog}")

    if spark is None:
        spark = get_spark_session()

    discovered = discover_files(actual_data_root)
    print(f"[{run_id}] Discovered {len(discovered)} raw files.")

    all_raw_rows: list[tuple[str, str, str, str | None, str]] = []
    ingested_file_rows: list[tuple[str, str, str, int, str, str]] = []
    total_records = 0

    for category, file_path in discovered:
        file_name = file_path.name
        checksum = compute_sha256(file_path)
        id_col = KNOWN_ID_COLS.get(file_name)
        file_records: list[tuple[str, str, str, str | None, str]] = []

        if file_name.endswith(".json") or file_name.endswith(".jsonl"):
            with open(file_path, encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    if isinstance(data, dict):
                        data = [data]
                    elif not isinstance(data, list):
                        data = []
                except json.JSONDecodeError:
                    f.seek(0)
                    data = []
                    for line in f:
                        line_str = line.strip()
                        if line_str:
                            data.append(json.loads(line_str))

                for item in data:
                    if not isinstance(item, dict):
                        continue
                    row_id = extract_json_row_id(item, id_col)
                    file_records.append(
                        (run_id, category, file_name, row_id, json.dumps(item))
                    )

        elif file_name.endswith(".csv"):
            with open(file_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    row_id = extract_csv_row_id(row, id_col)
                    file_records.append(
                        (run_id, category, file_name, row_id, json.dumps(row))
                    )

        rec_count = len(file_records)
        total_records += rec_count
        all_raw_rows.extend(file_records)
        ingested_file_rows.append(
            (run_id, file_name, str(file_path), rec_count, checksum, "LOADED")
        )

    print(f"[{run_id}] Total records collected across all files: {total_records}")

    if spark is not None:
        from pyspark.sql.types import (
            IntegerType,
            StringType,
            StructField,
            StructType,
        )

        # 1. Ingest into {catalog}.bronze.raw_records
        if all_raw_rows:
            from pyspark.sql import functions as F

            raw_schema = StructType([
                StructField("pipeline_run_id", StringType(), False),
                StructField("source_category", StringType(), False),
                StructField("file_name", StringType(), False),
                StructField("source_row_id", StringType(), True),
                StructField("payload", StringType(), False),
            ])
            raw_df = spark.createDataFrame(all_raw_rows, schema=raw_schema)
            raw_df = raw_df.withColumn("loaded_at_utc", F.current_timestamp())
            raw_df.write.format("delta").mode("append").saveAsTable(
                f"{catalog}.bronze.raw_records"
            )
            print(f"[{run_id}] Appended {len(all_raw_rows)} records to {catalog}.bronze.raw_records")

        # 2. Record file metadata to {catalog}.ops.ingested_files
        if ingested_file_rows:
            ops_schema = StructType([
                StructField("run_id", StringType(), False),
                StructField("file_name", StringType(), False),
                StructField("file_path", StringType(), False),
                StructField("record_count", IntegerType(), False),
                StructField("checksum_sha256", StringType(), True),
                StructField("status", StringType(), False),
            ])
            ops_df = spark.createDataFrame(ingested_file_rows, schema=ops_schema)
            ops_df.write.format("delta").mode("append").saveAsTable(
                f"{catalog}.ops.ingested_files"
            )
            print(f"[{run_id}] Logged {len(ingested_file_rows)} files into {catalog}.ops.ingested_files")

        # 3. Upsert execution metadata into {catalog}.ops.pipeline_runs
        spark.sql(f"""
            MERGE INTO {catalog}.ops.pipeline_runs AS target
            USING (SELECT '{run_id}' AS run_id, {total_records} AS records_read) AS source
            ON target.run_id = source.run_id
            WHEN MATCHED THEN
                UPDATE SET target.records_read = source.records_read,
                           target.current_stage = 'bronze'
            WHEN NOT MATCHED THEN
                INSERT (run_id, started_at_utc, status, current_stage, records_read)
                VALUES (source.run_id, current_timestamp(), 'RUNNING', 'bronze', source.records_read)
        """)
        print(f"[{run_id}] Updated {catalog}.ops.pipeline_runs stage to 'bronze'.")

    return {"total_records_read": total_records}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Databricks Bronze Ingestion into Unity Catalog Delta Tables"
    )
    parser.add_argument(
        "--run-id",
        default=os.getenv("PIPELINE_RUN_ID", f"run_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"),
        help="Unique pipeline execution run ID",
    )
    parser.add_argument(
        "--catalog",
        default=os.getenv("DATABRICKS_CATALOG", "retail_analytics"),
        help="Target Unity Catalog name",
    )
    parser.add_argument(
        "--data-root",
        default=None,
        help="Custom raw data folder or volume path override",
    )
    args = parser.parse_args()

    run_bronze_ingestion(
        run_id=args.run_id,
        catalog=args.catalog,
        data_root=args.data_root,
    )


if __name__ == "__main__":
    main()
