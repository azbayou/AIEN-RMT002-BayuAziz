"""Setup Databricks Unity Catalog, schemas (bronze, silver, gold, ops), and raw_data volume."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

try:
    CURRENT_DIR = Path(__file__).resolve().parent
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
except NameError:
    CURRENT_DIR = Path.cwd()
    PROJECT_ROOT = Path.cwd()


def get_spark_session() -> Any:
    """Retrieve existing SparkSession or initialize one."""
    try:
        from pyspark.sql import SparkSession

        return SparkSession.builder.appName("setup_unity_catalog").getOrCreate()
    except ImportError:
        print("Note: pyspark not installed locally. Operating in script/CLI mode.")
        return None
    except Exception as exc:
        print(f"Warning: SparkSession could not be initialized: {exc}")
        return None


def setup_unity_catalog(
    catalog: str = "retail_analytics",
    spark: Any = None,
    create_tables: bool = True,
) -> None:
    """Execute Unity Catalog DDLs for catalog, schemas, volume, and delta tables."""
    print(f"Initializing Unity Catalog environment for catalog: '{catalog}'...")

    if spark is None:
        spark = get_spark_session()

    ddls = [
        f"CREATE CATALOG IF NOT EXISTS {catalog}",
        f"USE CATALOG {catalog}",
        f"CREATE SCHEMA IF NOT EXISTS {catalog}.bronze COMMENT 'Bronze Layer: Raw ingested data and landing logs'",
        f"CREATE SCHEMA IF NOT EXISTS {catalog}.silver COMMENT 'Silver Layer: Cleaned and normalized tables'",
        f"CREATE SCHEMA IF NOT EXISTS {catalog}.gold COMMENT 'Gold Layer: Aggregated business metrics and KPIs'",
        f"CREATE SCHEMA IF NOT EXISTS {catalog}.ops COMMENT 'Operations Layer: Pipeline lifecycle, ingestion logs, and quality checks'",
        f"CREATE VOLUME IF NOT EXISTS {catalog}.bronze.raw_data COMMENT 'Volume storing landed raw JSON and CSV files'",
    ]

    for ddl in ddls:
        print(f"Executing: {ddl}")
        if spark is not None:
            spark.sql(ddl)

    if create_tables:
        sql_file: Path | None = None
        candidates = [
            CURRENT_DIR / "create_delta_tables.sql",
            CURRENT_DIR / "databricks" / "schemas" / "create_delta_tables.sql",
            CURRENT_DIR / "schemas" / "create_delta_tables.sql",
            Path.cwd() / "create_delta_tables.sql",
            Path.cwd() / "databricks" / "schemas" / "create_delta_tables.sql",
            Path.cwd() / "schemas" / "create_delta_tables.sql",
        ]
        for c in candidates:
            if c.exists() and c.is_file():
                sql_file = c
                break

        if sql_file is None:
            for c in Path.cwd().rglob("create_delta_tables.sql"):
                if c.is_file():
                    sql_file = c
                    break

        if sql_file and sql_file.exists():
            print(f"Applying Delta Lake table DDLs from {sql_file}...")
            content = sql_file.read_text(encoding="utf-8")
            # Replace template variable ${catalog_name} with actual catalog
            templated_sql = content.replace("${catalog_name}", catalog)
            statements = [s.strip() for s in templated_sql.split(";") if s.strip()]
            for stmt in statements:
                if spark is not None:
                    spark.sql(stmt)
        else:
            print("Note: create_delta_tables.sql not found in workspace paths. Pre-existing tables retained.")

    print(f"Successfully initialized Unity Catalog schemas and volume for catalog '{catalog}'.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Setup Databricks Unity Catalog, schemas, volume, and tables."
    )
    parser.add_argument(
        "--catalog",
        default=os.getenv("DATABRICKS_CATALOG", "retail_analytics"),
        help="Target catalog name (default: retail_analytics)",
    )
    parser.add_argument(
        "--skip-tables",
        action="store_true",
        help="Skip executing create_delta_tables.sql",
    )
    args = parser.parse_args()

    setup_unity_catalog(catalog=args.catalog, create_tables=not args.skip_tables)


if __name__ == "__main__":
    main()
