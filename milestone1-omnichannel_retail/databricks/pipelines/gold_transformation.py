"""PySpark Gold Layer Transformation for Databricks Unity Catalog.

Reads clean normalized tables from {catalog}.silver.*, applies analytical aggregations
without fact multiplication, eliminates all hardcoded constants, and writes/merges into
{catalog}.gold.* Delta tables.
"""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from typing import Any


def get_spark_session(app_name: str = "RetailAnalytics_GoldTransformation") -> Any:
    """Get active SparkSession or create a new one."""
    try:
        from pyspark.sql import SparkSession
        return SparkSession.builder.appName(app_name).getOrCreate()
    except Exception as exc:
        raise RuntimeError(f"Could not initialize SparkSession: {exc}") from exc


def resolve_latest_run_id(spark: Any, catalog: str) -> str:
    """Resolve latest run_id from Silver or Bronze if not provided."""
    from pyspark.sql import functions as F
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


def build_gold_tables(spark: Any, catalog: str = "retail_analytics", run_id: str | None = None) -> dict[str, int]:
    """Execute all 5 Gold table transformations for a given run_id."""
    if not run_id or run_id == "default_run":
        run_id = resolve_latest_run_id(spark, catalog)
    """Build all 5 Gold analytical Delta tables using validated dynamic logic."""
    print(f"[{run_id}] Starting Gold transformation in catalog '{catalog}'...")

    # Set default catalog for the session
    spark.sql(f"USE CATALOG {catalog}")

    results: dict[str, int] = {}

    # -------------------------------------------------------------------------
    # 1. gold.order_360
    # -------------------------------------------------------------------------
    print(f"[{run_id}] Building {catalog}.gold.order_360...")
    order_360_sql = f"""
    WITH item_agg AS (
        SELECT 
            order_id,
            CAST(SUM(quantity * unit_price) AS DECIMAL(14, 2)) AS gmv,
            CAST(SUM(item_discount_amount) AS DECIMAL(14, 2)) AS total_discount,
            COUNT(*) AS item_count,
            SUM(quantity) AS total_units
        FROM {catalog}.silver.order_items
        WHERE pipeline_run_id = '{run_id}'
        GROUP BY order_id
    ),
    pay_agg AS (
        SELECT 
            order_id,
            CAST(SUM(captured_amount) AS DECIMAL(14, 2)) AS total_captured
        FROM {catalog}.silver.payments
        WHERE pipeline_run_id = '{run_id}'
        GROUP BY order_id
    ),
    ref_agg AS (
        SELECT 
            order_id,
            CAST(SUM(refund_amount) AS DECIMAL(14, 2)) AS total_refunded
        FROM {catalog}.silver.refunds
        WHERE pipeline_run_id = '{run_id}'
          AND (refund_status = 'REFUND_COMPLETED' OR refund_status IS NULL)
        GROUP BY order_id
    ),
    latest_returns AS (
        SELECT order_id, return_status
        FROM (
            SELECT 
                order_id, 
                return_status,
                ROW_NUMBER() OVER (
                    PARTITION BY order_id 
                    ORDER BY occurred_at_utc DESC
                ) AS rn
            FROM {catalog}.silver.returns
            WHERE pipeline_run_id = '{run_id}'
        ) r_sub
        WHERE rn = 1
    ),
    promo_agg AS (
        SELECT 
            order_id,
            COUNT(DISTINCT promotion_id) AS promotion_count
        FROM {catalog}.silver.order_promotions
        WHERE pipeline_run_id = '{run_id}'
        GROUP BY order_id
    ),
    customer_first_orders AS (
        SELECT 
            order_id,
            ROW_NUMBER() OVER (
                PARTITION BY customer_id 
                ORDER BY ordered_at_utc ASC, order_id ASC
            ) = 1 AS is_first_order
        FROM {catalog}.silver.orders
        WHERE pipeline_run_id = '{run_id}'
    )
    SELECT 
        o.order_id,
        o.customer_id,
        CAST(o.ordered_at_utc AS DATE) AS order_date,
        o.sales_channel,
        o.store_id,
        COALESCE(i.gmv, CAST(0.00 AS DECIMAL(14, 2))) AS gross_merchandise_value,
        COALESCE(i.total_discount, CAST(0.00 AS DECIMAL(14, 2))) AS discount_amount,
        COALESCE(o.shipping_revenue, CAST(0.00 AS DECIMAL(14, 2))) AS shipping_revenue,
        COALESCE(p.total_captured, CAST(0.00 AS DECIMAL(14, 2))) AS captured_payment_amount,
        COALESCE(r.total_refunded, CAST(0.00 AS DECIMAL(14, 2))) AS refunded_amount,
        CAST((COALESCE(i.gmv, 0.00) - COALESCE(i.total_discount, 0.00) + COALESCE(o.shipping_revenue, 0.00) - COALESCE(r.total_refunded, 0.00)) AS DECIMAL(14, 2)) AS net_revenue,
        CAST(COALESCE(i.item_count, 0) AS INT) AS item_count,
        CAST(COALESCE(i.total_units, 0) AS INT) AS unit_quantity,
        o.order_status,
        CASE WHEN COALESCE(p.total_captured, 0.00) > 0 THEN 'CAPTURED' ELSE 'PENDING' END AS payment_status,
        COALESCE(ret.return_status, 'NONE') AS return_status,
        CAST(COALESCE(pr.promotion_count, 0) AS INT) AS promotion_count,
        COALESCE(fo.is_first_order, false) AS first_order_flag,
        '{run_id}' AS pipeline_run_id
    FROM {catalog}.silver.orders o
    LEFT JOIN item_agg i ON o.order_id = i.order_id
    LEFT JOIN pay_agg p ON o.order_id = p.order_id
    LEFT JOIN ref_agg r ON o.order_id = r.order_id
    LEFT JOIN latest_returns ret ON o.order_id = ret.order_id
    LEFT JOIN promo_agg pr ON o.order_id = pr.order_id
    LEFT JOIN customer_first_orders fo ON o.order_id = fo.order_id
    WHERE o.pipeline_run_id = '{run_id}'
    """

    df_order_360 = spark.sql(order_360_sql)
    df_order_360.createOrReplaceTempView("src_order_360")

    merge_order_360_sql = f"""
    MERGE INTO {catalog}.gold.order_360 AS target
    USING src_order_360 AS source
    ON target.order_id = source.order_id
    WHEN MATCHED THEN UPDATE SET
        target.customer_id = source.customer_id,
        target.order_date = source.order_date,
        target.sales_channel = source.sales_channel,
        target.store_id = source.store_id,
        target.gross_merchandise_value = source.gross_merchandise_value,
        target.discount_amount = source.discount_amount,
        target.shipping_revenue = source.shipping_revenue,
        target.captured_payment_amount = source.captured_payment_amount,
        target.refunded_amount = source.refunded_amount,
        target.net_revenue = source.net_revenue,
        target.item_count = source.item_count,
        target.unit_quantity = source.unit_quantity,
        target.order_status = source.order_status,
        target.payment_status = source.payment_status,
        target.return_status = source.return_status,
        target.promotion_count = source.promotion_count,
        target.first_order_flag = source.first_order_flag,
        target.pipeline_run_id = source.pipeline_run_id
    WHEN NOT MATCHED THEN INSERT (
        order_id, customer_id, order_date, sales_channel, store_id,
        gross_merchandise_value, discount_amount, shipping_revenue,
        captured_payment_amount, refunded_amount, net_revenue,
        item_count, unit_quantity, order_status, payment_status,
        return_status, promotion_count, first_order_flag, pipeline_run_id
    ) VALUES (
        source.order_id, source.customer_id, source.order_date, source.sales_channel, source.store_id,
        source.gross_merchandise_value, source.discount_amount, source.shipping_revenue,
        source.captured_payment_amount, source.refunded_amount, source.net_revenue,
        source.item_count, source.unit_quantity, source.order_status, source.payment_status,
        source.return_status, source.promotion_count, source.first_order_flag, source.pipeline_run_id
    )
    """
    spark.sql(merge_order_360_sql)
    count_order_360 = spark.sql(f"SELECT COUNT(*) FROM {catalog}.gold.order_360 WHERE pipeline_run_id = '{run_id}'").collect()[0][0]
    results["gold.order_360"] = count_order_360
    print(f"[{run_id}] {catalog}.gold.order_360 built: {count_order_360} rows.")

    # -------------------------------------------------------------------------
    # 2. gold.customer_daily
    # -------------------------------------------------------------------------
    print(f"[{run_id}] Building {catalog}.gold.customer_daily...")
    customer_daily_sql = f"""
    WITH order_returns AS (
        SELECT 
            order_id,
            COUNT(DISTINCT return_id) AS return_count
        FROM {catalog}.silver.returns
        WHERE pipeline_run_id = '{run_id}'
        GROUP BY order_id
    ),
    order_support AS (
        SELECT 
            order_id,
            COUNT(DISTINCT ticket_id) AS support_contacts
        FROM {catalog}.silver.support_tickets
        WHERE pipeline_run_id = '{run_id}'
        GROUP BY order_id
    )
    SELECT 
        o.customer_id,
        o.order_date AS metric_date,
        CAST(COUNT(o.order_id) AS INT) AS order_count,
        CAST(SUM(o.unit_quantity) AS INT) AS unit_quantity,
        CAST(SUM(o.gross_merchandise_value) AS DECIMAL(14, 2)) AS gross_revenue,
        CAST(SUM(o.net_revenue) AS DECIMAL(14, 2)) AS net_revenue,
        CAST(SUM(o.refunded_amount) AS DECIMAL(14, 2)) AS refund_amount,
        CAST(SUM(COALESCE(r.return_count, CASE WHEN o.return_status != 'NONE' THEN 1 ELSE 0 END)) AS INT) AS return_count,
        CAST(SUM(COALESCE(st.support_contacts, 0)) AS INT) AS support_contacts,
        MAX(o.sales_channel) AS active_channel,
        MAX(CASE WHEN o.first_order_flag THEN 1 ELSE 0 END) = 1 AS new_customer_flag,
        MAX(CASE WHEN o.first_order_flag THEN 1 ELSE 0 END) = 0 AS repeat_customer_flag,
        '{run_id}' AS pipeline_run_id
    FROM {catalog}.gold.order_360 o
    LEFT JOIN order_returns r ON o.order_id = r.order_id
    LEFT JOIN order_support st ON o.order_id = st.order_id
    WHERE o.pipeline_run_id = '{run_id}'
    GROUP BY o.customer_id, o.order_date
    """

    df_customer_daily = spark.sql(customer_daily_sql)
    df_customer_daily.createOrReplaceTempView("src_customer_daily")

    merge_customer_daily_sql = f"""
    MERGE INTO {catalog}.gold.customer_daily AS target
    USING src_customer_daily AS source
    ON target.customer_id = source.customer_id AND target.metric_date = source.metric_date
    WHEN MATCHED THEN UPDATE SET
        target.order_count = source.order_count,
        target.unit_quantity = source.unit_quantity,
        target.gross_revenue = source.gross_revenue,
        target.net_revenue = source.net_revenue,
        target.refund_amount = source.refund_amount,
        target.return_count = source.return_count,
        target.support_contacts = source.support_contacts,
        target.active_channel = source.active_channel,
        target.new_customer_flag = source.new_customer_flag,
        target.repeat_customer_flag = source.repeat_customer_flag,
        target.pipeline_run_id = source.pipeline_run_id
    WHEN NOT MATCHED THEN INSERT (
        customer_id, metric_date, order_count, unit_quantity, gross_revenue,
        net_revenue, refund_amount, return_count, support_contacts,
        active_channel, new_customer_flag, repeat_customer_flag, pipeline_run_id
    ) VALUES (
        source.customer_id, source.metric_date, source.order_count, source.unit_quantity, source.gross_revenue,
        source.net_revenue, source.refund_amount, source.return_count, source.support_contacts,
        source.active_channel, source.new_customer_flag, source.repeat_customer_flag, source.pipeline_run_id
    )
    """
    spark.sql(merge_customer_daily_sql)
    count_customer_daily = spark.sql(f"SELECT COUNT(*) FROM {catalog}.gold.customer_daily WHERE pipeline_run_id = '{run_id}'").collect()[0][0]
    results["gold.customer_daily"] = count_customer_daily
    print(f"[{run_id}] {catalog}.gold.customer_daily built: {count_customer_daily} rows.")

    # -------------------------------------------------------------------------
    # 3. gold.product_daily
    # -------------------------------------------------------------------------
    print(f"[{run_id}] Building {catalog}.gold.product_daily...")
    product_daily_sql = f"""
    WITH prod_sales AS (
        SELECT 
            oi.product_id,
            CAST(o.ordered_at_utc AS DATE) AS metric_date,
            CAST(SUM(oi.quantity) AS INT) AS units_sold,
            COUNT(DISTINCT oi.order_id) AS order_count,
            CAST(SUM(oi.quantity * oi.unit_price) AS DECIMAL(14, 2)) AS gross_revenue,
            CAST(SUM(oi.quantity * oi.unit_price - oi.item_discount_amount) AS DECIMAL(14, 2)) AS net_revenue
        FROM {catalog}.silver.order_items oi
        JOIN {catalog}.silver.orders o ON oi.order_id = o.order_id AND oi.pipeline_run_id = o.pipeline_run_id
        WHERE oi.pipeline_run_id = '{run_id}'
        GROUP BY oi.product_id, CAST(o.ordered_at_utc AS DATE)
    ),
    inventory_agg AS (
        SELECT 
            product_id,
            CAST(snapshot_date AS DATE) AS metric_date,
            CAST(SUM(available_quantity) AS INT) AS available_inv,
            CAST(SUM(reserved_quantity) AS INT) AS reserved_inv
        FROM {catalog}.silver.inventory_snapshots
        WHERE pipeline_run_id = '{run_id}'
        GROUP BY product_id, snapshot_date
    ),
    all_product_days AS (
        SELECT product_id, metric_date FROM prod_sales
        UNION
        SELECT product_id, metric_date FROM inventory_agg
    ),
    prod_refunds AS (
        SELECT 
            oi.product_id,
            CAST(o.ordered_at_utc AS DATE) AS metric_date,
            CAST(SUM(oi.quantity) AS INT) AS refunded_units
        FROM {catalog}.silver.order_items oi
        JOIN {catalog}.silver.orders o ON oi.order_id = o.order_id AND oi.pipeline_run_id = o.pipeline_run_id
        JOIN (
            SELECT DISTINCT order_id 
            FROM {catalog}.silver.refunds 
            WHERE pipeline_run_id = '{run_id}'
              AND (refund_status = 'REFUND_COMPLETED' OR refund_status IS NULL)
        ) r ON oi.order_id = r.order_id
        WHERE oi.pipeline_run_id = '{run_id}'
        GROUP BY oi.product_id, CAST(o.ordered_at_utc AS DATE)
    ),
    prod_promos AS (
        SELECT 
            oi.product_id,
            CAST(o.ordered_at_utc AS DATE) AS metric_date,
            COUNT(DISTINCT op.promotion_id) AS promotion_count
        FROM {catalog}.silver.order_items oi
        JOIN {catalog}.silver.orders o ON oi.order_id = o.order_id AND oi.pipeline_run_id = o.pipeline_run_id
        JOIN {catalog}.silver.order_promotions op ON oi.order_id = op.order_id AND oi.pipeline_run_id = op.pipeline_run_id
        WHERE oi.pipeline_run_id = '{run_id}'
        GROUP BY oi.product_id, CAST(o.ordered_at_utc AS DATE)
    ),
    active_categories AS (
        SELECT product_id, metric_date, category_name
        FROM (
            SELECT 
                d.product_id,
                d.metric_date,
                pc.category_name,
                ROW_NUMBER() OVER (
                    PARTITION BY d.product_id, d.metric_date 
                    ORDER BY pc.valid_from_utc DESC
                ) AS rn
            FROM all_product_days d
            JOIN {catalog}.silver.product_categories pc 
              ON d.product_id = pc.product_id 
             AND pc.pipeline_run_id = '{run_id}'
             AND d.metric_date BETWEEN CAST(pc.valid_from_utc AS DATE) AND COALESCE(CAST(pc.valid_to_utc AS DATE), DATE '9999-12-31')
        ) ranked_cat
        WHERE rn = 1
    ),
    fallback_categories AS (
        SELECT product_id, category_name
        FROM (
            SELECT 
                product_id, 
                category_name,
                ROW_NUMBER() OVER (
                    PARTITION BY product_id 
                    ORDER BY valid_from_utc DESC
                ) AS rn
            FROM {catalog}.silver.product_categories
            WHERE pipeline_run_id = '{run_id}'
        ) ranked_fcat
        WHERE rn = 1
    )
    SELECT 
        d.product_id,
        d.metric_date,
        COALESCE(ac.category_name, fc.category_name, 'general') AS active_category,
        CAST(COALESCE(p.units_sold, 0) AS INT) AS units_sold,
        CAST(COALESCE(p.order_count, 0) AS INT) AS order_count,
        COALESCE(p.gross_revenue, CAST(0.00 AS DECIMAL(14, 2))) AS gross_revenue,
        COALESCE(p.net_revenue, CAST(0.00 AS DECIMAL(14, 2))) AS net_revenue,
        CAST(COALESCE(pr.refunded_units, 0) AS INT) AS refunded_units,
        CAST(COALESCE(inv.available_inv, 0) AS INT) AS available_inventory,
        CAST(COALESCE(inv.reserved_inv, 0) AS INT) AS reserved_inventory,
        CASE WHEN COALESCE(inv.available_inv, 0) <= 0 THEN true ELSE false END AS stockout_flag,
        CAST(COALESCE(pp.promotion_count, 0) AS INT) AS promotion_count,
        '{run_id}' AS pipeline_run_id
    FROM all_product_days d
    LEFT JOIN prod_sales p ON d.product_id = p.product_id AND d.metric_date = p.metric_date
    LEFT JOIN inventory_agg inv ON d.product_id = inv.product_id AND d.metric_date = inv.metric_date
    LEFT JOIN prod_refunds pr ON d.product_id = pr.product_id AND d.metric_date = pr.metric_date
    LEFT JOIN prod_promos pp ON d.product_id = pp.product_id AND d.metric_date = pp.metric_date
    LEFT JOIN active_categories ac ON d.product_id = ac.product_id AND d.metric_date = ac.metric_date
    LEFT JOIN fallback_categories fc ON d.product_id = fc.product_id
    """

    df_product_daily = spark.sql(product_daily_sql)
    df_product_daily.createOrReplaceTempView("src_product_daily")

    merge_product_daily_sql = f"""
    MERGE INTO {catalog}.gold.product_daily AS target
    USING src_product_daily AS source
    ON target.product_id = source.product_id AND target.metric_date = source.metric_date
    WHEN MATCHED THEN UPDATE SET
        target.active_category = source.active_category,
        target.units_sold = source.units_sold,
        target.order_count = source.order_count,
        target.gross_revenue = source.gross_revenue,
        target.net_revenue = source.net_revenue,
        target.refunded_units = source.refunded_units,
        target.available_inventory = source.available_inventory,
        target.reserved_inventory = source.reserved_inventory,
        target.stockout_flag = source.stockout_flag,
        target.promotion_count = source.promotion_count,
        target.pipeline_run_id = source.pipeline_run_id
    WHEN NOT MATCHED THEN INSERT (
        product_id, metric_date, active_category, units_sold, order_count,
        gross_revenue, net_revenue, refunded_units, available_inventory,
        reserved_inventory, stockout_flag, promotion_count, pipeline_run_id
    ) VALUES (
        source.product_id, source.metric_date, source.active_category, source.units_sold, source.order_count,
        source.gross_revenue, source.net_revenue, source.refunded_units, source.available_inventory,
        source.reserved_inventory, source.stockout_flag, source.promotion_count, source.pipeline_run_id
    )
    """
    spark.sql(merge_product_daily_sql)
    count_product_daily = spark.sql(f"SELECT COUNT(*) FROM {catalog}.gold.product_daily WHERE pipeline_run_id = '{run_id}'").collect()[0][0]
    results["gold.product_daily"] = count_product_daily
    print(f"[{run_id}] {catalog}.gold.product_daily built: {count_product_daily} rows.")

    # -------------------------------------------------------------------------
    # 4. gold.channel_campaign_daily
    # -------------------------------------------------------------------------
    print(f"[{run_id}] Building {catalog}.gold.channel_campaign_daily...")
    channel_campaign_daily_sql = f"""
    WITH order_campaign_attribution AS (
        SELECT DISTINCT
            order_id,
            campaign_id
        FROM {catalog}.silver.web_events
        WHERE pipeline_run_id = '{run_id}'
          AND event_type = 'PURCHASE'
          AND order_id IS NOT NULL
          AND campaign_id IS NOT NULL
    ),
    attributed_orders_agg AS (
        SELECT 
            o.order_date AS metric_date,
            o.sales_channel,
            attr.campaign_id,
            CAST(COUNT(DISTINCT o.order_id) AS INT) AS attributed_orders,
            CAST(COUNT(DISTINCT o.customer_id) AS INT) AS attributed_customers,
            CAST(SUM(o.gross_merchandise_value) AS DECIMAL(14, 2)) AS gross_revenue,
            CAST(SUM(o.net_revenue) AS DECIMAL(14, 2)) AS net_revenue,
            CAST(SUM(o.refunded_amount) AS DECIMAL(14, 2)) AS refunds
        FROM {catalog}.gold.order_360 o
        JOIN order_campaign_attribution attr ON o.order_id = attr.order_id
        WHERE o.pipeline_run_id = '{run_id}'
        GROUP BY o.order_date, o.sales_channel, attr.campaign_id
    ),
    spend_agg AS (
        SELECT 
            CAST(spend_date AS DATE) AS metric_date,
            channel AS sales_channel,
            campaign_id,
            CAST(SUM(spend_amount) AS DECIMAL(14, 2)) AS campaign_spend
        FROM {catalog}.silver.campaign_spend
        WHERE pipeline_run_id = '{run_id}'
        GROUP BY spend_date, channel, campaign_id
    ),
    web_events_agg AS (
        SELECT 
            CAST(occurred_at_utc AS DATE) AS metric_date,
            channel AS sales_channel,
            campaign_id,
            CAST(COUNT(DISTINCT CASE WHEN event_type = 'PURCHASE' THEN session_id END) AS DOUBLE) / NULLIF(COUNT(DISTINCT session_id), 0) AS conversion_rate
        FROM {catalog}.silver.web_events
        WHERE pipeline_run_id = '{run_id}'
          AND campaign_id IS NOT NULL
        GROUP BY CAST(occurred_at_utc AS DATE), channel, campaign_id
    ),
    campaign_keys AS (
        SELECT metric_date, sales_channel, campaign_id FROM spend_agg
        UNION
        SELECT metric_date, sales_channel, campaign_id FROM attributed_orders_agg
        UNION
        SELECT metric_date, sales_channel, campaign_id FROM web_events_agg
    )
    SELECT 
        k.metric_date,
        k.sales_channel,
        k.campaign_id,
        COALESCE(s.campaign_spend, CAST(0.00 AS DECIMAL(14, 2))) AS campaign_spend,
        CAST(COALESCE(ao.attributed_orders, 0) AS INT) AS attributed_orders,
        CAST(COALESCE(ao.attributed_customers, 0) AS INT) AS attributed_customers,
        COALESCE(ao.gross_revenue, CAST(0.00 AS DECIMAL(14, 2))) AS gross_revenue,
        COALESCE(ao.net_revenue, CAST(0.00 AS DECIMAL(14, 2))) AS net_revenue,
        COALESCE(ao.refunds, CAST(0.00 AS DECIMAL(14, 2))) AS refunds,
        CAST(ROUND(COALESCE(ao.net_revenue, 0.00) / NULLIF(s.campaign_spend, 0), 4) AS DECIMAL(14, 4)) AS roas,
        CAST(ROUND(COALESCE(we.conversion_rate, 0.0000), 4) AS DECIMAL(14, 4)) AS conversion_rate,
        '{run_id}' AS pipeline_run_id
    FROM campaign_keys k
    LEFT JOIN spend_agg s 
      ON k.metric_date = s.metric_date 
     AND k.sales_channel = s.sales_channel 
     AND k.campaign_id = s.campaign_id
    LEFT JOIN attributed_orders_agg ao 
      ON k.metric_date = ao.metric_date 
     AND k.sales_channel = ao.sales_channel 
     AND k.campaign_id = ao.campaign_id
    LEFT JOIN web_events_agg we 
      ON k.metric_date = we.metric_date 
     AND k.sales_channel = we.sales_channel 
     AND k.campaign_id = we.campaign_id
    """

    df_channel_campaign_daily = spark.sql(channel_campaign_daily_sql)
    df_channel_campaign_daily.createOrReplaceTempView("src_channel_campaign_daily")

    merge_channel_campaign_daily_sql = f"""
    MERGE INTO {catalog}.gold.channel_campaign_daily AS target
    USING src_channel_campaign_daily AS source
    ON target.metric_date = source.metric_date AND target.sales_channel = source.sales_channel AND target.campaign_id = source.campaign_id
    WHEN MATCHED THEN UPDATE SET
        target.campaign_spend = source.campaign_spend,
        target.attributed_orders = source.attributed_orders,
        target.attributed_customers = source.attributed_customers,
        target.gross_revenue = source.gross_revenue,
        target.net_revenue = source.net_revenue,
        target.refunds = source.refunds,
        target.roas = source.roas,
        target.conversion_rate = source.conversion_rate,
        target.pipeline_run_id = source.pipeline_run_id
    WHEN NOT MATCHED THEN INSERT (
        metric_date, sales_channel, campaign_id, campaign_spend,
        attributed_orders, attributed_customers, gross_revenue, net_revenue,
        refunds, roas, conversion_rate, pipeline_run_id
    ) VALUES (
        source.metric_date, source.sales_channel, source.campaign_id, source.campaign_spend,
        source.attributed_orders, source.attributed_customers, source.gross_revenue, source.net_revenue,
        source.refunds, source.roas, source.conversion_rate, source.pipeline_run_id
    )
    """
    spark.sql(merge_channel_campaign_daily_sql)
    count_channel_campaign_daily = spark.sql(f"SELECT COUNT(*) FROM {catalog}.gold.channel_campaign_daily WHERE pipeline_run_id = '{run_id}'").collect()[0][0]
    results["gold.channel_campaign_daily"] = count_channel_campaign_daily
    print(f"[{run_id}] {catalog}.gold.channel_campaign_daily built: {count_channel_campaign_daily} rows.")

    # -------------------------------------------------------------------------
    # 5. gold.executive_kpis_daily
    # -------------------------------------------------------------------------
    print(f"[{run_id}] Building {catalog}.gold.executive_kpis_daily...")
    executive_kpis_daily_sql = f"""
    WITH daily_stockouts AS (
        SELECT 
            metric_date,
            CAST(ROUND(AVG(CAST(stockout_flag AS INT)), 4) AS DECIMAL(14, 4)) AS stockout_rate
        FROM {catalog}.gold.product_daily
        WHERE pipeline_run_id = '{run_id}'
          AND stockout_flag IS NOT NULL
        GROUP BY metric_date
    ),
    support_orders AS (
        SELECT DISTINCT order_id
        FROM {catalog}.silver.support_tickets
        WHERE pipeline_run_id = '{run_id}'
    )
    SELECT 
        o.order_date AS metric_date,
        CAST(COUNT(o.order_id) AS INT) AS total_orders,
        CAST(SUM(o.gross_merchandise_value) AS DECIMAL(14, 2)) AS gross_revenue,
        CAST(SUM(o.net_revenue) AS DECIMAL(14, 2)) AS net_revenue,
        CAST(COALESCE(ROUND(SUM(o.gross_merchandise_value) / NULLIF(COUNT(o.order_id), 0), 2), 0.00) AS DECIMAL(14, 2)) AS average_order_value,
        CAST(COALESCE(ROUND(CAST(COUNT(CASE WHEN o.refunded_amount > 0 THEN 1 END) AS DOUBLE) / NULLIF(COUNT(CASE WHEN o.captured_payment_amount > 0 THEN 1 END), 0), 4), 0.0000) AS DECIMAL(14, 4)) AS refund_rate,
        CAST(COALESCE(ROUND(CAST(COUNT(CASE WHEN o.return_status != 'NONE' THEN 1 END) AS DOUBLE) / NULLIF(COUNT(o.order_id), 0), 4), 0.0000) AS DECIMAL(14, 4)) AS return_rate,
        CAST(COALESCE(ROUND(CAST(COUNT(CASE WHEN o.first_order_flag = false THEN 1 END) AS DOUBLE) / NULLIF(COUNT(o.order_id), 0), 4), 0.0000) AS DECIMAL(14, 4)) AS repeat_customer_rate,
        CAST(COALESCE(MAX(ds.stockout_rate), 0.0000) AS DECIMAL(14, 4)) AS stockout_rate,
        CAST(COUNT(DISTINCT o.customer_id) AS INT) AS active_customers,
        CAST(COALESCE(ROUND(CAST(COUNT(DISTINCT CASE WHEN supp.order_id IS NOT NULL THEN o.customer_id END) AS DOUBLE) / NULLIF(COUNT(DISTINCT o.customer_id), 0), 4), 0.0000) AS DECIMAL(14, 4)) AS support_contact_rate,
        CURRENT_TIMESTAMP() AS data_freshness_utc,
        '{run_id}' AS pipeline_run_id
    FROM {catalog}.gold.order_360 o
    LEFT JOIN daily_stockouts ds ON o.order_date = ds.metric_date
    LEFT JOIN support_orders supp ON o.order_id = supp.order_id
    WHERE o.pipeline_run_id = '{run_id}'
    GROUP BY o.order_date
    """

    df_executive_kpis_daily = spark.sql(executive_kpis_daily_sql)
    df_executive_kpis_daily.createOrReplaceTempView("src_executive_kpis_daily")

    merge_executive_kpis_daily_sql = f"""
    MERGE INTO {catalog}.gold.executive_kpis_daily AS target
    USING src_executive_kpis_daily AS source
    ON target.metric_date = source.metric_date
    WHEN MATCHED THEN UPDATE SET
        target.total_orders = source.total_orders,
        target.gross_revenue = source.gross_revenue,
        target.net_revenue = source.net_revenue,
        target.average_order_value = source.average_order_value,
        target.refund_rate = source.refund_rate,
        target.return_rate = source.return_rate,
        target.repeat_customer_rate = source.repeat_customer_rate,
        target.stockout_rate = source.stockout_rate,
        target.active_customers = source.active_customers,
        target.support_contact_rate = source.support_contact_rate,
        target.data_freshness_utc = source.data_freshness_utc,
        target.pipeline_run_id = source.pipeline_run_id
    WHEN NOT MATCHED THEN INSERT (
        metric_date, total_orders, gross_revenue, net_revenue,
        average_order_value, refund_rate, return_rate, repeat_customer_rate,
        stockout_rate, active_customers, support_contact_rate,
        data_freshness_utc, pipeline_run_id
    ) VALUES (
        source.metric_date, source.total_orders, source.gross_revenue, source.net_revenue,
        source.average_order_value, source.refund_rate, source.return_rate, source.repeat_customer_rate,
        source.stockout_rate, source.active_customers, source.support_contact_rate,
        source.data_freshness_utc, source.pipeline_run_id
    )
    """
    spark.sql(merge_executive_kpis_daily_sql)
    count_executive_kpis_daily = spark.sql(f"SELECT COUNT(*) FROM {catalog}.gold.executive_kpis_daily WHERE pipeline_run_id = '{run_id}'").collect()[0][0]
    results["gold.executive_kpis_daily"] = count_executive_kpis_daily
    print(f"[{run_id}] {catalog}.gold.executive_kpis_daily built: {count_executive_kpis_daily} rows.")

    print(f"[{run_id}] Gold transformation completed successfully across all 5 analytical tables.")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="PySpark Gold Layer Transformation for Databricks Unity Catalog")
    parser.add_argument("--catalog", default=os.getenv("DATABRICKS_CATALOG", "retail_analytics"), help="Unity Catalog name")
    parser.add_argument("--run-id", default=os.getenv("PIPELINE_RUN_ID", None), help="Pipeline run identifier")
    args = parser.parse_args()

    spark = get_spark_session()
    build_gold_tables(spark, catalog=args.catalog, run_id=args.run_id)


if __name__ == "__main__":
    main()
