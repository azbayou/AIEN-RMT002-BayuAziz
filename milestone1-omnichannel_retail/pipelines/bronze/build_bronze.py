"""Ingesti Raw Data ke Bronze Layer (bronze.raw_records) dan Ops Logging."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.db import connect

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_data_root() -> Path:
    """Tentukan folder data: prioritaskan data/raw jika ada dan berisi data, fallback ke data."""
    raw_path = PROJECT_ROOT / "data" / "raw"
    if raw_path.exists() and raw_path.is_dir():
        for item in raw_path.rglob("*"):
            if (
                item.is_file()
                and not item.name.startswith(".")
                and item.suffix.lower() in {".json", ".csv", ".jsonl"}
            ):
                return raw_path
    return PROJECT_ROOT / "data"


DATA_ROOT = get_data_root()

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


def compute_sha256(file_path: Path) -> str:
    """Hitung checksum file untuk verifikasi idempotency."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def extract_json_row_id(item: dict[str, Any], id_col: str | None) -> str | None:
    """Ekstrak row identifier dari item JSON."""
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
    """Ekstrak row identifier dari row CSV jika tersedia."""
    if id_col and row.get(id_col) is not None:
        return str(row[id_col])
    if row.get("source_row_id") is not None:
        return str(row["source_row_id"])
    if row.get("id") is not None:
        return str(row["id"])
    return None


def discover_source_files(data_root: Path) -> list[tuple[str, Path]]:
    """Temukan seluruh file raw di subfolder kategori secara dinamis."""
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


def load_bronze(
    run_id: str,
    target: str = "local",
    data_root: Path | None = None,
) -> dict[str, int]:
    """Baca seluruh file raw dan simpan payload asli ke bronze.raw_records."""
    global DATA_ROOT
    actual_data_root = Path(data_root) if data_root is not None else get_data_root()
    DATA_ROOT = actual_data_root

    print(f"[{run_id}] Bronze Ingestion Dimulai menggunakan {actual_data_root}...")

    discovered_files = discover_source_files(actual_data_root)
    total_records = 0

    with connect(target) as conn:
        # 1. Pastikan skema dan tabel bronze & ops tersedia
        conn.execute("CREATE SCHEMA IF NOT EXISTS bronze;")
        conn.execute("CREATE SCHEMA IF NOT EXISTS ops;")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bronze.raw_records (
                id BIGSERIAL PRIMARY KEY,
                pipeline_run_id TEXT NOT NULL,
                source_category TEXT NOT NULL,
                file_name TEXT NOT NULL,
                source_row_id TEXT,
                payload JSONB NOT NULL,
                loaded_at_utc TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ops.pipeline_runs (
                run_id TEXT PRIMARY KEY,
                started_at_utc TIMESTAMPTZ NOT NULL,
                completed_at_utc TIMESTAMPTZ,
                status TEXT NOT NULL,
                current_stage TEXT,
                error_message TEXT,
                records_read INTEGER DEFAULT 0,
                records_clean INTEGER DEFAULT 0,
                records_rejected INTEGER DEFAULT 0,
                created_at_utc TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ops.ingested_files (
                id SERIAL PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES ops.pipeline_runs(run_id) ON DELETE CASCADE,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                record_count INTEGER NOT NULL,
                checksum_sha256 TEXT,
                status TEXT NOT NULL,
                ingested_at_utc TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        # 2. Pastikan run_id terdaftar di ops.pipeline_runs untuk referential integrity
        conn.execute(
            """
            INSERT INTO ops.pipeline_runs (run_id, started_at_utc, status, current_stage)
            VALUES (%s, %s, 'RUNNING', 'bronze')
            ON CONFLICT (run_id) DO UPDATE SET current_stage = 'bronze'
            """,
            (run_id, datetime.now(UTC)),
        )

        # 3. Idempotency cleanup jika run_id ini pernah dieksekusi sebelumnya
        conn.execute(
            "DELETE FROM bronze.raw_records WHERE pipeline_run_id = %s", (run_id,)
        )
        conn.execute("DELETE FROM ops.ingested_files WHERE run_id = %s", (run_id,))

        # 4. Proses setiap file
        for category, file_path in discovered_files:
            file_name = file_path.name
            checksum = compute_sha256(file_path)
            rows_to_insert: list[tuple[str, str, str, str | None, str]] = []
            id_col = KNOWN_ID_COLS.get(file_name)

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
                            stripped = line.strip()
                            if stripped:
                                data.append(json.loads(stripped))

                    for item in data:
                        if not isinstance(item, dict):
                            continue
                        row_id = extract_json_row_id(item, id_col)
                        rows_to_insert.append(
                            (run_id, category, file_name, row_id, json.dumps(item))
                        )

            elif file_name.endswith(".csv"):
                with open(file_path, encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        row_id = extract_csv_row_id(row, id_col)
                        rows_to_insert.append(
                            (run_id, category, file_name, row_id, json.dumps(row))
                        )

            record_count = len(rows_to_insert)
            total_records += record_count

            # 5. Multi-row batch insert ke bronze.raw_records (efisiensi tinggi)
            batch_size = 1000
            for chunk_start in range(0, record_count, batch_size):
                chunk = rows_to_insert[chunk_start : chunk_start + batch_size]
                placeholders = ", ".join(["(%s, %s, %s, %s, %s)"] * len(chunk))
                query = f"""
                    INSERT INTO bronze.raw_records 
                    (pipeline_run_id, source_category, file_name, source_row_id, payload)
                    VALUES {placeholders}
                """
                params = [val for r in chunk for val in r]
                conn.execute(query, params)

            # 6. Catat file ingestion metadata ke ops.ingested_files
            conn.execute(
                """
                INSERT INTO ops.ingested_files 
                (run_id, file_name, file_path, record_count, checksum_sha256, status)
                VALUES (%s, %s, %s, %s, %s, 'LOADED')
                """,
                (run_id, file_name, str(file_path), record_count, checksum),
            )

        # 7. Update total records_read di ops.pipeline_runs
        conn.execute(
            """
            UPDATE ops.pipeline_runs 
            SET records_read = %s, current_stage = 'bronze'
            WHERE run_id = %s
            """,
            (total_records, run_id),
        )
        conn.commit()

    print(f"[{run_id}] Selesai memuat {total_records} record ke Bronze.")
    return {"total_records_read": total_records}


if __name__ == "__main__":
    test_run_id = f"manual-run-{int(datetime.now(UTC).timestamp())}"
    with connect("local") as c:
        c.execute(
            "INSERT INTO ops.pipeline_runs (run_id, started_at_utc, status, current_stage) VALUES (%s, %s, 'RUNNING', 'bronze')",
            (test_run_id, datetime.now(UTC)),
        )
        c.commit()
    load_bronze(test_run_id)
