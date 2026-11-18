"""Quality Checks & Audit Gate untuk Silver dan Gold layer."""

from __future__ import annotations

import json
from typing import Any

from shared.db import connect


def _table_exists(conn: Any, schema: str, table: str) -> bool:
    """Helper to check if a table exists in PostgreSQL."""
    query = """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_schema = %s AND table_name = %s
        )
    """
    row = conn.execute(query, (schema, table)).fetchone()
    return bool(row[0]) if row else False


def run_silver_quality_gate(run_id: str, target: str = "local") -> bool:
    """Mengecek kelayakan data Silver. Mengembalikan True jika lulus, raise error jika gagal."""
    with connect(target) as conn:
        checks_passed = True

        # Check 1: silver_orders_exist (Harus ada order valid yang dihasilkan)
        order_count = conn.execute(
            "SELECT COUNT(*) FROM silver.orders WHERE pipeline_run_id = %s", (run_id,)
        ).fetchone()[0]

        c1_passed = order_count > 0
        conn.execute(
            """
            INSERT INTO ops.quality_checks (run_id, check_name, check_stage, passed, details_json)
            VALUES (%s, 'silver_orders_exist', 'silver_gate', %s, %s)
            """,
            (run_id, c1_passed, json.dumps({"order_count": int(order_count)}))
        )
        if not c1_passed:
            checks_passed = False

        # Check 2: no_negative_qty_in_clean (Tidak boleh ada quantity <= 0 di tabel clean silver.order_items)
        negative_qty_count = conn.execute(
            "SELECT COUNT(*) FROM silver.order_items WHERE pipeline_run_id = %s AND quantity <= 0", (run_id,)
        ).fetchone()[0]

        c2_passed = (negative_qty_count == 0)
        conn.execute(
            """
            INSERT INTO ops.quality_checks (run_id, check_name, check_stage, passed, details_json)
            VALUES (%s, 'no_negative_qty_in_clean', 'silver_gate', %s, %s)
            """,
            (run_id, c2_passed, json.dumps({"negative_quantity_rows": int(negative_qty_count)}))
        )
        if not c2_passed:
            checks_passed = False

        # Check 3: unique_keys (Tidak boleh ada duplikasi primary key pada tabel-tabel clean Silver)
        silver_tables_keys = [
            ("silver", "orders", ["order_id"]),
            ("silver", "order_items", ["order_item_id"]),
            ("silver", "payments", ["payment_id"]),
            ("silver", "refunds", ["refund_id"]),
            ("silver", "returns", ["return_id"]),
            ("silver", "support_tickets", ["ticket_id"]),
            ("silver", "promotions", ["promotion_id"]),
            ("silver", "order_promotions", ["order_id", "promotion_id"]),
            ("silver", "web_events", ["event_id"]),
            ("silver", "products", ["product_id"]),
            ("silver", "customers", ["customer_id"]),
            ("silver", "customer_profiles", ["customer_id", "valid_from_utc"]),
            ("silver", "product_categories", ["product_id", "valid_from_utc"]),
            ("silver", "inventory_snapshots", ["product_id", "location_id", "snapshot_date"]),
            ("silver", "campaign_spend", ["spend_date", "campaign_id", "channel"]),
        ]

        unique_details: dict[str, int] = {}
        all_unique = True
        for schema, table, keys in silver_tables_keys:
            if not _table_exists(conn, schema, table):
                continue
            cols = ", ".join(keys)
            query = f"""
                SELECT COUNT(*) FROM (
                    SELECT {cols} FROM {schema}.{table}
                    WHERE pipeline_run_id = %s
                    GROUP BY {cols} HAVING COUNT(*) > 1
                ) dup
            """
            dup_count = conn.execute(query, (run_id,)).fetchone()[0]
            unique_details[f"{table}_duplicates"] = int(dup_count)
            if dup_count > 0:
                all_unique = False

        c3_passed = all_unique
        conn.execute(
            """
            INSERT INTO ops.quality_checks (run_id, check_name, check_stage, passed, details_json)
            VALUES (%s, 'unique_keys', 'silver_gate', %s, %s)
            """,
            (run_id, c3_passed, json.dumps(unique_details))
        )
        if not c3_passed:
            checks_passed = False

        # Check 4: referential_integrity (no orphan items/payments/refunds)
        orphan_details: dict[str, int] = {}

        orphan_items = conn.execute(
            """
            SELECT COUNT(*) FROM silver.order_items oi
            WHERE oi.pipeline_run_id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM silver.orders o
                  WHERE o.order_id = oi.order_id AND o.pipeline_run_id = oi.pipeline_run_id
              )
            """,
            (run_id,)
        ).fetchone()[0]
        orphan_details["orphan_order_items"] = int(orphan_items)

        orphan_payments = conn.execute(
            """
            SELECT COUNT(*) FROM silver.payments p
            WHERE p.pipeline_run_id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM silver.orders o
                  WHERE o.order_id = p.order_id AND o.pipeline_run_id = p.pipeline_run_id
              )
            """,
            (run_id,)
        ).fetchone()[0]
        orphan_details["orphan_payments"] = int(orphan_payments)

        orphan_refunds = conn.execute(
            """
            SELECT COUNT(*) FROM silver.refunds r
            WHERE r.pipeline_run_id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM silver.orders o
                  WHERE o.order_id = r.order_id AND o.pipeline_run_id = r.pipeline_run_id
              )
            """,
            (run_id,)
        ).fetchone()[0]
        orphan_details["orphan_refunds"] = int(orphan_refunds)

        if _table_exists(conn, "silver", "returns"):
            orphan_returns = conn.execute(
                """
                SELECT COUNT(*) FROM silver.returns ret
                WHERE ret.pipeline_run_id = %s
                  AND NOT EXISTS (
                      SELECT 1 FROM silver.orders o
                      WHERE o.order_id = ret.order_id AND o.pipeline_run_id = ret.pipeline_run_id
                  )
                """,
                (run_id,)
            ).fetchone()[0]
            orphan_details["orphan_returns"] = int(orphan_returns)

        c4_passed = all(cnt == 0 for cnt in orphan_details.values())
        conn.execute(
            """
            INSERT INTO ops.quality_checks (run_id, check_name, check_stage, passed, details_json)
            VALUES (%s, 'referential_integrity', 'silver_gate', %s, %s)
            """,
            (run_id, c4_passed, json.dumps(orphan_details))
        )
        if not c4_passed:
            checks_passed = False

        conn.commit()

        if not checks_passed:
            raise ValueError(f"Quality Gate GAGAL untuk run {run_id}. Periksa tabel ops.quality_checks!")

    print(f"[{run_id}] Silver Quality Gate LULUS seluruh pengujian.")
    return True


def run_gold_validation_and_reconciliation(run_id: str, target: str = "local") -> bool:
    """Validasi dan rekonsiliasi Gold layer:
    1. unique_keys on all 5 gold tables
    2. revenue_reconciliation (net revenue match across gold.order_360, customer_daily, executive_kpis_daily)
    3. refund_reconciliation (refunds match across gold.order_360, customer_daily, silver.refunds)
    4. kpi_rate_bounds_valid (all rates 0 <= r <= 1)
    5. non_null_contract_grains
    Mengembalikan True jika semua check lulus, raise ValueError jika ada yang gagal.
    """
    with connect(target) as conn:
        checks_passed = True

        # Check 1: unique_keys on all 5 gold tables
        gold_tables_keys = [
            ("gold", "order_360", ["order_id"]),
            ("gold", "customer_daily", ["customer_id", "metric_date"]),
            ("gold", "product_daily", ["product_id", "metric_date"]),
            ("gold", "channel_campaign_daily", ["metric_date", "sales_channel", "campaign_id"]),
            ("gold", "executive_kpis_daily", ["metric_date"]),
        ]

        gold_unique_details: dict[str, int] = {}
        all_gold_unique = True
        for schema, table, keys in gold_tables_keys:
            cols = ", ".join(keys)
            query = f"""
                SELECT COUNT(*) FROM (
                    SELECT {cols} FROM {schema}.{table}
                    WHERE pipeline_run_id = %s
                    GROUP BY {cols} HAVING COUNT(*) > 1
                ) dup
            """
            dup_count = conn.execute(query, (run_id,)).fetchone()[0]
            gold_unique_details[f"{table}_duplicates"] = int(dup_count)
            if dup_count > 0:
                all_gold_unique = False

        c1_passed = all_gold_unique
        conn.execute(
            """
            INSERT INTO ops.quality_checks (run_id, check_name, check_stage, passed, details_json)
            VALUES (%s, 'unique_keys', 'gold_validation', %s, %s)
            """,
            (run_id, c1_passed, json.dumps(gold_unique_details))
        )
        if not c1_passed:
            checks_passed = False

        # Check 2: revenue_reconciliation (net revenue match across gold.order_360, customer_daily, executive_kpis_daily)
        order_net_rev = conn.execute(
            "SELECT COALESCE(SUM(net_revenue), 0) FROM gold.order_360 WHERE pipeline_run_id = %s",
            (run_id,)
        ).fetchone()[0]

        cust_net_rev = conn.execute(
            "SELECT COALESCE(SUM(net_revenue), 0) FROM gold.customer_daily WHERE pipeline_run_id = %s",
            (run_id,)
        ).fetchone()[0]

        exec_net_rev = conn.execute(
            "SELECT COALESCE(SUM(net_revenue), 0) FROM gold.executive_kpis_daily WHERE pipeline_run_id = %s",
            (run_id,)
        ).fetchone()[0]

        val_order_rev = float(order_net_rev)
        val_cust_rev = float(cust_net_rev)
        val_exec_rev = float(exec_net_rev)

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
        conn.execute(
            """
            INSERT INTO ops.quality_checks (run_id, check_name, check_stage, passed, details_json)
            VALUES (%s, 'revenue_reconciliation', 'gold_validation', %s, %s)
            """,
            (run_id, c2_passed, json.dumps(revenue_details))
        )
        if not c2_passed:
            checks_passed = False

        # Check 3: refund_reconciliation (refunds match across gold.order_360, customer_daily, silver.refunds)
        silver_refunds = conn.execute(
            "SELECT COALESCE(SUM(refund_amount), 0) FROM silver.refunds WHERE pipeline_run_id = %s",
            (run_id,)
        ).fetchone()[0]

        order_refunds = conn.execute(
            "SELECT COALESCE(SUM(refunded_amount), 0) FROM gold.order_360 WHERE pipeline_run_id = %s",
            (run_id,)
        ).fetchone()[0]

        cust_refunds = conn.execute(
            "SELECT COALESCE(SUM(refund_amount), 0) FROM gold.customer_daily WHERE pipeline_run_id = %s",
            (run_id,)
        ).fetchone()[0]

        val_silv_ref = float(silver_refunds)
        val_ord_ref = float(order_refunds)
        val_cust_ref = float(cust_refunds)

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
        conn.execute(
            """
            INSERT INTO ops.quality_checks (run_id, check_name, check_stage, passed, details_json)
            VALUES (%s, 'refund_reconciliation', 'gold_validation', %s, %s)
            """,
            (run_id, c3_passed, json.dumps(refund_details))
        )
        if not c3_passed:
            checks_passed = False

        # Check 4: kpi_rate_bounds_valid (all rates 0 <= r <= 1)
        bad_rates_row = conn.execute(
            """
            SELECT 
                COUNT(CASE WHEN refund_rate < 0 OR refund_rate > 1 THEN 1 END),
                COUNT(CASE WHEN return_rate < 0 OR return_rate > 1 THEN 1 END),
                COUNT(CASE WHEN repeat_customer_rate < 0 OR repeat_customer_rate > 1 THEN 1 END),
                COUNT(CASE WHEN stockout_rate < 0 OR stockout_rate > 1 THEN 1 END),
                COUNT(CASE WHEN support_contact_rate < 0 OR support_contact_rate > 1 THEN 1 END)
            FROM gold.executive_kpis_daily
            WHERE pipeline_run_id = %s
            """,
            (run_id,)
        ).fetchone()

        bad_conv_count = conn.execute(
            """
            SELECT COUNT(*) FROM gold.channel_campaign_daily
            WHERE pipeline_run_id = %s
              AND conversion_rate IS NOT NULL
              AND (conversion_rate < 0 OR conversion_rate > 1)
            """,
            (run_id,)
        ).fetchone()[0]

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
        conn.execute(
            """
            INSERT INTO ops.quality_checks (run_id, check_name, check_stage, passed, details_json)
            VALUES (%s, 'kpi_rate_bounds_valid', 'gold_validation', %s, %s)
            """,
            (run_id, c4_passed, json.dumps(rate_details))
        )
        if not c4_passed:
            checks_passed = False

        # Check 5: non_null_contract_grains
        null_order_grains = conn.execute(
            "SELECT COUNT(*) FROM gold.order_360 WHERE pipeline_run_id = %s AND order_id IS NULL",
            (run_id,)
        ).fetchone()[0]

        null_cust_grains = conn.execute(
            "SELECT COUNT(*) FROM gold.customer_daily WHERE pipeline_run_id = %s AND (customer_id IS NULL OR metric_date IS NULL)",
            (run_id,)
        ).fetchone()[0]

        null_prod_grains = conn.execute(
            "SELECT COUNT(*) FROM gold.product_daily WHERE pipeline_run_id = %s AND (product_id IS NULL OR metric_date IS NULL)",
            (run_id,)
        ).fetchone()[0]

        null_chan_grains = conn.execute(
            """
            SELECT COUNT(*) FROM gold.channel_campaign_daily 
            WHERE pipeline_run_id = %s 
              AND (metric_date IS NULL OR sales_channel IS NULL OR campaign_id IS NULL)
            """,
            (run_id,)
        ).fetchone()[0]

        null_exec_grains = conn.execute(
            "SELECT COUNT(*) FROM gold.executive_kpis_daily WHERE pipeline_run_id = %s AND metric_date IS NULL",
            (run_id,)
        ).fetchone()[0]

        grain_details = {
            "null_order_grains": int(null_order_grains),
            "null_customer_daily_grains": int(null_cust_grains),
            "null_product_daily_grains": int(null_prod_grains),
            "null_channel_campaign_daily_grains": int(null_chan_grains),
            "null_executive_kpis_daily_grains": int(null_exec_grains),
        }
        total_null_grains = sum(grain_details.values())
        c5_passed = (total_null_grains == 0)
        conn.execute(
            """
            INSERT INTO ops.quality_checks (run_id, check_name, check_stage, passed, details_json)
            VALUES (%s, 'non_null_contract_grains', 'gold_validation', %s, %s)
            """,
            (run_id, c5_passed, json.dumps(grain_details))
        )
        if not c5_passed:
            checks_passed = False

        conn.commit()

        if not checks_passed:
            raise ValueError(f"Gold Validation & Reconciliation GAGAL untuk run {run_id}. Periksa tabel ops.quality_checks!")

    print(f"[{run_id}] Gold Validation & Reconciliation LULUS seluruh pengujian.")
    return True
