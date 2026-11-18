"""PySpark Quality Gate & Audit Checks for Databricks Unity Catalog.

Implements audit and reconciliation checks for Silver and Gold layers:
1. --stage silver:
   - silver_orders_exist
   - no_negative_qty_in_clean
   - unique_keys
   - referential_integrity
2. --stage gold:
   - unique_keys
   - revenue_reconciliation
   - refund_reconciliation
   - kpi_rate_bounds_valid
   - non_null_contract_grains

Persists all check results to {catalog}.ops.quality_checks and raises
ValueError on failure to prevent corrupted data from progressing downstream.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from typing import Any


def get_spark_session(app_name: str = "RetailAnalytics_QualityChecks") -> Any:
    """Get active SparkSession or create a new one."""
    try:
        from pyspark.sql import SparkSession
        return SparkSession.builder.appName(app_name).getOrCreate()
    except Exception as exc:
        raise RuntimeError(f"Could not initialize SparkSession: {exc}") from exc


def _table_exists(spark: Any, catalog: str, schema: str, table: str) -> bool:
    """Check if a table exists in Unity Catalog."""
    try:
        spark.sql(f"DESCRIBE TABLE {catalog}.{schema}.{table}")
        return True
    except Exception:
        return False


def record_quality_check(
    spark: Any,
    catalog: str,
    run_id: str,
    check_name: str,
    check_stage: str,
    passed: bool,
    details: dict[str, Any],
) -> None:
    """Record an audit check result into {catalog}.ops.quality_checks."""
    details_str = json.dumps(details).replace("'", "''")
    passed_str = "true" if passed else "false"
    sql = f"""
    INSERT INTO {catalog}.ops.quality_checks
    (run_id, check_name, check_stage, passed, details_json, checked_at_utc)
    VALUES ('{run_id}', '{check_name}', '{check_stage}', {passed_str}, '{details_str}', CURRENT_TIMESTAMP())
    """
    spark.sql(sql)
    status_tag = "PASSED" if passed else "FAILED"
    print(f"[{run_id}] [{check_stage}] [{check_name}]: {status_tag} - {details}")


def resolve_latest_run_id(spark: Any, catalog: str, stage: str = "silver") -> str:
    """Resolve latest run_id from Silver or Bronze if not provided."""
    from pyspark.sql import functions as F
    if stage in {"gold", "all"}:
        try:
            row = (
                spark.table(f"{catalog}.gold.order_360")
                .select("pipeline_run_id")
                .orderBy(F.col("id").desc())
                .first()
            )
            if row and row["pipeline_run_id"]:
                return str(row["pipeline_run_id"])
        except Exception:
            pass

    try:
        row = (
            spark.table(f"{catalog}.silver.orders")
            .select("pipeline_run_id")
            .orderBy(F.col("id").desc())
            .first()
        )
        if row and row["pipeline_run_id"]:
            return str(row["pipeline_run_id"])
    except Exception:
        pass
    try:
        row = (
            spark.table(f"{catalog}.bronze.raw_records")
            .select("pipeline_run_id")
            .orderBy(F.col("id").desc())
            .first()
        )
        if row and row["pipeline_run_id"]:
            return str(row["pipeline_run_id"])
    except Exception:
        pass
    return f"run_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"


def run_silver_checks(spark: Any, catalog: str, run_id: str | None = None) -> bool:
    """Execute Silver quality gate checks."""
    if not run_id:
        run_id = resolve_latest_run_id(spark, catalog, stage="silver")
    print(f"[{run_id}] Running Silver quality gate in catalog '{catalog}'...")
    all_passed = True

    # Check 1: silver_orders_exist
    order_count = spark.sql(
        f"SELECT COUNT(*) FROM {catalog}.silver.orders WHERE pipeline_run_id = '{run_id}'"
    ).collect()[0][0]
    c1_passed = order_count > 0
    record_quality_check(
        spark, catalog, run_id, "silver_orders_exist", "silver_gate",
        c1_passed, {"order_count": int(order_count)}
    )
    if not c1_passed:
        all_passed = False

    # Check 2: no_negative_qty_in_clean
    neg_qty_count = spark.sql(
        f"SELECT COUNT(*) FROM {catalog}.silver.order_items WHERE pipeline_run_id = '{run_id}' AND quantity <= 0"
    ).collect()[0][0]
    c2_passed = (neg_qty_count == 0)
    record_quality_check(
        spark, catalog, run_id, "no_negative_qty_in_clean", "silver_gate",
        c2_passed, {"negative_quantity_rows": int(neg_qty_count)}
    )
    if not c2_passed:
        all_passed = False

    # Check 3: unique_keys on clean Silver tables
    silver_tables_keys = [
        ("orders", ["order_id"]),
        ("order_items", ["order_item_id"]),
        ("payments", ["payment_id"]),
        ("refunds", ["refund_id"]),
        ("returns", ["return_id"]),
        ("support_tickets", ["ticket_id"]),
        ("promotions", ["promotion_id"]),
        ("order_promotions", ["order_id", "promotion_id"]),
        ("web_events", ["event_id"]),
        ("products", ["product_id"]),
        ("customers", ["customer_id"]),
        ("customer_profiles", ["customer_id", "valid_from_utc"]),
        ("product_categories", ["product_id", "valid_from_utc"]),
        ("inventory_snapshots", ["product_id", "location_id", "snapshot_date"]),
        ("campaign_spend", ["spend_date", "campaign_id", "channel"]),
    ]
    unique_details: dict[str, int] = {}
    all_silver_unique = True
    for table, keys in silver_tables_keys:
        if not _table_exists(spark, catalog, "silver", table):
            continue
        cols = ", ".join(keys)
        dup_query = f"""
            SELECT COUNT(*) FROM (
                SELECT {cols} FROM {catalog}.silver.{table}
                WHERE pipeline_run_id = '{run_id}'
                GROUP BY {cols} HAVING COUNT(*) > 1
            ) dup
        """
        dup_count = spark.sql(dup_query).collect()[0][0]
        unique_details[f"{table}_duplicates"] = int(dup_count)
        if dup_count > 0:
            all_silver_unique = False

    c3_passed = all_silver_unique
    record_quality_check(
        spark, catalog, run_id, "unique_keys", "silver_gate",
        c3_passed, unique_details
    )
    if not c3_passed:
        all_passed = False

    # Check 4: referential_integrity
    orphan_details: dict[str, int] = {}
    orphan_items = spark.sql(
        f"""
        SELECT COUNT(*) FROM {catalog}.silver.order_items oi
        WHERE oi.pipeline_run_id = '{run_id}'
          AND NOT EXISTS (
              SELECT 1 FROM {catalog}.silver.orders o
              WHERE o.order_id = oi.order_id AND o.pipeline_run_id = oi.pipeline_run_id
          )
        """
    ).collect()[0][0]
    orphan_details["orphan_order_items"] = int(orphan_items)

    orphan_payments = spark.sql(
        f"""
        SELECT COUNT(*) FROM {catalog}.silver.payments p
        WHERE p.pipeline_run_id = '{run_id}'
          AND NOT EXISTS (
              SELECT 1 FROM {catalog}.silver.orders o
              WHERE o.order_id = p.order_id AND o.pipeline_run_id = p.pipeline_run_id
          )
        """
    ).collect()[0][0]
    orphan_details["orphan_payments"] = int(orphan_payments)

    orphan_refunds = spark.sql(
        f"""
        SELECT COUNT(*) FROM {catalog}.silver.refunds r
        WHERE r.pipeline_run_id = '{run_id}'
          AND NOT EXISTS (
              SELECT 1 FROM {catalog}.silver.orders o
              WHERE o.order_id = r.order_id AND o.pipeline_run_id = r.pipeline_run_id
          )
        """
    ).collect()[0][0]
    orphan_details["orphan_refunds"] = int(orphan_refunds)

    if _table_exists(spark, catalog, "silver", "returns"):
        orphan_returns = spark.sql(
            f"""
            SELECT COUNT(*) FROM {catalog}.silver.returns ret
            WHERE ret.pipeline_run_id = '{run_id}'
              AND NOT EXISTS (
                  SELECT 1 FROM {catalog}.silver.orders o
                  WHERE o.order_id = ret.order_id AND o.pipeline_run_id = ret.pipeline_run_id
              )
            """
        ).collect()[0][0]
        orphan_details["orphan_returns"] = int(orphan_returns)

    c4_passed = all(cnt == 0 for cnt in orphan_details.values())
    record_quality_check(
        spark, catalog, run_id, "referential_integrity", "silver_gate",
        c4_passed, orphan_details
    )
    if not c4_passed:
        all_passed = False

    if not all_passed:
        raise ValueError(f"Silver Quality Gate FAILED for run '{run_id}'. See {catalog}.ops.quality_checks.")

    print(f"[{run_id}] Silver Quality Gate PASSED all checks.")
    return True


def run_gold_checks(spark: Any, catalog: str, run_id: str | None = None) -> bool:
    """Execute Gold validation and reconciliation checks."""
    if not run_id:
        run_id = resolve_latest_run_id(spark, catalog, stage="gold")
    print(f"[{run_id}] Running Gold validation and reconciliation in catalog '{catalog}'...")
    all_passed = True

    # Check 1: unique_keys on all 5 gold tables
    gold_tables_keys = [
        ("order_360", ["order_id"]),
        ("customer_daily", ["customer_id", "metric_date"]),
        ("product_daily", ["product_id", "metric_date"]),
        ("channel_campaign_daily", ["metric_date", "sales_channel", "campaign_id"]),
        ("executive_kpis_daily", ["metric_date"]),
    ]
    gold_unique_details: dict[str, int] = {}
    all_gold_unique = True
    for table, keys in gold_tables_keys:
        cols = ", ".join(keys)
        dup_query = f"""
            SELECT COUNT(*) FROM (
                SELECT {cols} FROM {catalog}.gold.{table}
                WHERE pipeline_run_id = '{run_id}'
                GROUP BY {cols} HAVING COUNT(*) > 1
            ) dup
        """
        dup_count = spark.sql(dup_query).collect()[0][0]
        gold_unique_details[f"{table}_duplicates"] = int(dup_count)
        if dup_count > 0:
            all_gold_unique = False

    c1_passed = all_gold_unique
    record_quality_check(
        spark, catalog, run_id, "unique_keys", "gold_validation",
        c1_passed, gold_unique_details
    )
    if not c1_passed:
        all_passed = False

    # Check 2: revenue_reconciliation
    order_net_rev = spark.sql(
        f"SELECT COALESCE(SUM(net_revenue), 0) FROM {catalog}.gold.order_360 WHERE pipeline_run_id = '{run_id}'"
    ).collect()[0][0]
    cust_net_rev = spark.sql(
        f"SELECT COALESCE(SUM(net_revenue), 0) FROM {catalog}.gold.customer_daily WHERE pipeline_run_id = '{run_id}'"
    ).collect()[0][0]
    exec_net_rev = spark.sql(
        f"SELECT COALESCE(SUM(net_revenue), 0) FROM {catalog}.gold.executive_kpis_daily WHERE pipeline_run_id = '{run_id}'"
    ).collect()[0][0]

    val_order_rev = float(order_net_rev or 0.0)
    val_cust_rev = float(cust_net_rev or 0.0)
    val_exec_rev = float(exec_net_rev or 0.0)

    diff_order_cust = round(abs(val_order_rev - val_cust_rev), 2)
    diff_order_exec = round(abs(val_order_rev - val_exec_rev), 2)

    c2_passed = (diff_order_cust < 0.01) and (diff_order_exec < 0.01)
    revenue_details = {
        "order_360_net_revenue": val_order_rev,
        "customer_daily_net_revenue": val_cust_rev,
        "executive_kpis_daily_net_revenue": val_exec_rev,
        "diff_order_customer": diff_order_cust,
        "diff_order_executive": diff_order_exec,
    }
    record_quality_check(
        spark, catalog, run_id, "revenue_reconciliation", "gold_validation",
        c2_passed, revenue_details
    )
    if not c2_passed:
        all_passed = False

    # Check 3: refund_reconciliation
    silver_refunds = spark.sql(
        f"SELECT COALESCE(SUM(refund_amount), 0) FROM {catalog}.silver.refunds WHERE pipeline_run_id = '{run_id}'"
    ).collect()[0][0]
    order_refunds = spark.sql(
        f"SELECT COALESCE(SUM(refunded_amount), 0) FROM {catalog}.gold.order_360 WHERE pipeline_run_id = '{run_id}'"
    ).collect()[0][0]
    cust_refunds = spark.sql(
        f"SELECT COALESCE(SUM(refund_amount), 0) FROM {catalog}.gold.customer_daily WHERE pipeline_run_id = '{run_id}'"
    ).collect()[0][0]

    val_silv_ref = float(silver_refunds or 0.0)
    val_ord_ref = float(order_refunds or 0.0)
    val_cust_ref = float(cust_refunds or 0.0)

    diff_silv_ord = round(abs(val_silv_ref - val_ord_ref), 2)
    diff_ord_cust = round(abs(val_ord_ref - val_cust_ref), 2)

    c3_passed = (diff_silv_ord < 0.01) and (diff_ord_cust < 0.01)
    refund_details = {
        "silver_refunds": val_silv_ref,
        "order_360_refunds": val_ord_ref,
        "customer_daily_refunds": val_cust_ref,
        "diff_silver_order": diff_silv_ord,
        "diff_order_customer": diff_ord_cust,
    }
    record_quality_check(
        spark, catalog, run_id, "refund_reconciliation", "gold_validation",
        c3_passed, refund_details
    )
    if not c3_passed:
        all_passed = False

    # Check 4: kpi_rate_bounds_valid
    bad_rates_row = spark.sql(
        f"""
        SELECT 
            COUNT(CASE WHEN refund_rate < 0 OR refund_rate > 1 THEN 1 END),
            COUNT(CASE WHEN return_rate < 0 OR return_rate > 1 THEN 1 END),
            COUNT(CASE WHEN repeat_customer_rate < 0 OR repeat_customer_rate > 1 THEN 1 END),
            COUNT(CASE WHEN stockout_rate < 0 OR stockout_rate > 1 THEN 1 END),
            COUNT(CASE WHEN support_contact_rate < 0 OR support_contact_rate > 1 THEN 1 END)
        FROM {catalog}.gold.executive_kpis_daily
        WHERE pipeline_run_id = '{run_id}'
        """
    ).collect()[0]

    bad_conv_count = spark.sql(
        f"""
        SELECT COUNT(*) FROM {catalog}.gold.channel_campaign_daily
        WHERE pipeline_run_id = '{run_id}'
          AND conversion_rate IS NOT NULL
          AND (conversion_rate < 0 OR conversion_rate > 1)
        """
    ).collect()[0][0]

    bad_exec_rates = sum(int(x) for x in bad_rates_row)
    c4_passed = (bad_exec_rates == 0 and int(bad_conv_count) == 0)
    rate_details = {
        "invalid_executive_rates_count": bad_exec_rates,
        "invalid_conversion_rates_count": int(bad_conv_count),
        "breakdown": {
            "refund_rate_invalid": int(bad_rates_row[0]),
            "return_rate_invalid": int(bad_rates_row[1]),
            "repeat_customer_rate_invalid": int(bad_rates_row[2]),
            "stockout_rate_invalid": int(bad_rates_row[3]),
            "support_contact_rate_invalid": int(bad_rates_row[4]),
        }
    }
    record_quality_check(
        spark, catalog, run_id, "kpi_rate_bounds_valid", "gold_validation",
        c4_passed, rate_details
    )
    if not c4_passed:
        all_passed = False

    # Check 5: non_null_contract_grains
    null_order_grains = spark.sql(
        f"SELECT COUNT(*) FROM {catalog}.gold.order_360 WHERE pipeline_run_id = '{run_id}' AND order_id IS NULL"
    ).collect()[0][0]
    null_cust_grains = spark.sql(
        f"SELECT COUNT(*) FROM {catalog}.gold.customer_daily WHERE pipeline_run_id = '{run_id}' AND (customer_id IS NULL OR metric_date IS NULL)"
    ).collect()[0][0]
    null_prod_grains = spark.sql(
        f"SELECT COUNT(*) FROM {catalog}.gold.product_daily WHERE pipeline_run_id = '{run_id}' AND (product_id IS NULL OR metric_date IS NULL)"
    ).collect()[0][0]
    null_chan_grains = spark.sql(
        f"""
        SELECT COUNT(*) FROM {catalog}.gold.channel_campaign_daily 
        WHERE pipeline_run_id = '{run_id}' 
          AND (metric_date IS NULL OR sales_channel IS NULL OR campaign_id IS NULL)
        """
    ).collect()[0][0]
    null_exec_grains = spark.sql(
        f"SELECT COUNT(*) FROM {catalog}.gold.executive_kpis_daily WHERE pipeline_run_id = '{run_id}' AND metric_date IS NULL"
    ).collect()[0][0]

    grain_details = {
        "null_order_grains": int(null_order_grains),
        "null_customer_daily_grains": int(null_cust_grains),
        "null_product_daily_grains": int(null_prod_grains),
        "null_channel_campaign_daily_grains": int(null_chan_grains),
        "null_executive_kpis_daily_grains": int(null_exec_grains),
    }
    total_null_grains = sum(grain_details.values())
    c5_passed = (total_null_grains == 0)
    record_quality_check(
        spark, catalog, run_id, "non_null_contract_grains", "gold_validation",
        c5_passed, grain_details
    )
    if not c5_passed:
        all_passed = False

    if not all_passed:
        raise ValueError(f"Gold Validation & Reconciliation FAILED for run '{run_id}'. See {catalog}.ops.quality_checks.")

    print(f"[{run_id}] Gold Validation & Reconciliation PASSED all checks.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="PySpark Quality Gate & Audit Checks for Databricks")
    parser.add_argument("--stage", required=True, choices=["silver", "gold", "all"], help="Quality gate stage to execute")
    parser.add_argument("--catalog", default=os.getenv("DATABRICKS_CATALOG", "retail_analytics"), help="Unity Catalog name")
    parser.add_argument("--run-id", default=os.getenv("PIPELINE_RUN_ID", None), help="Pipeline run identifier")
    args = parser.parse_args()

    spark = get_spark_session()

    if args.stage in {"silver", "all"}:
        run_silver_checks(spark, catalog=args.catalog, run_id=args.run_id)

    if args.stage in {"gold", "all"}:
        run_gold_checks(spark, catalog=args.catalog, run_id=args.run_id)


if __name__ == "__main__":
    main()
