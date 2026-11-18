"""PySpark Silver Transformation Pipeline for Databricks Delta Lake / Unity Catalog."""

from __future__ import annotations

import argparse
from typing import Any


def get_spark() -> Any:
    """Inisialisasi atau dapatkan SparkSession aktif."""
    try:
        from pyspark.sql import SparkSession

        return SparkSession.builder.appName("SilverTransformation").getOrCreate()
    except Exception as e:
        print(f"Error initializing SparkSession: {e}")
        raise


def ensure_silver_tables(spark: Any, catalog: str) -> None:
    """Pastikan schema silver dan seluruh Delta table sudah terdefinisi."""
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.silver")
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.ops")

    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {catalog}.silver.rejected_records (
            pipeline_run_id STRING,
            source_table STRING,
            record_identifier STRING,
            reject_reason STRING,
            payload STRING,
            rejected_at_utc TIMESTAMP
        ) USING DELTA
        """
    )

    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {catalog}.silver.orders (
            order_id STRING,
            customer_id STRING,
            ordered_at_utc TIMESTAMP,
            sales_channel STRING,
            order_status STRING,
            shipping_revenue DECIMAL(14, 2),
            store_id STRING,
            updated_at_utc TIMESTAMP,
            pipeline_run_id STRING
        ) USING DELTA
        """
    )

    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {catalog}.silver.order_items (
            order_item_id STRING,
            order_id STRING,
            product_id STRING,
            quantity INT,
            unit_price DECIMAL(14, 2),
            item_discount_amount DECIMAL(14, 2),
            pipeline_run_id STRING
        ) USING DELTA
        """
    )

    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {catalog}.silver.payments (
            payment_id STRING,
            order_id STRING,
            captured_amount DECIMAL(14, 2),
            payment_status STRING,
            occurred_at_utc TIMESTAMP,
            pipeline_run_id STRING
        ) USING DELTA
        """
    )

    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {catalog}.silver.refunds (
            refund_id STRING,
            order_id STRING,
            refund_amount DECIMAL(14, 2),
            refund_status STRING,
            occurred_at_utc TIMESTAMP,
            pipeline_run_id STRING
        ) USING DELTA
        """
    )

    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {catalog}.silver.returns (
            return_id STRING,
            order_id STRING,
            return_status STRING,
            occurred_at_utc TIMESTAMP,
            pipeline_run_id STRING
        ) USING DELTA
        """
    )

    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {catalog}.silver.support_tickets (
            ticket_id STRING,
            customer_id STRING,
            order_id STRING,
            reason STRING,
            event_type STRING,
            occurred_at_utc TIMESTAMP,
            pipeline_run_id STRING
        ) USING DELTA
        """
    )

    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {catalog}.silver.promotions (
            promotion_id STRING,
            promotion_code STRING,
            promotion_type STRING,
            discount_rate DECIMAL(14, 4),
            start_date DATE,
            end_date DATE,
            pipeline_run_id STRING
        ) USING DELTA
        """
    )

    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {catalog}.silver.order_promotions (
            order_id STRING,
            promotion_id STRING,
            discount_amount DECIMAL(14, 2),
            pipeline_run_id STRING
        ) USING DELTA
        """
    )

    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {catalog}.silver.web_events (
            event_id STRING,
            event_type STRING,
            session_id STRING,
            customer_id STRING,
            order_id STRING,
            channel STRING,
            campaign_id STRING,
            occurred_at_utc TIMESTAMP,
            pipeline_run_id STRING
        ) USING DELTA
        """
    )

    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {catalog}.silver.products (
            product_id STRING,
            sku STRING,
            product_name STRING,
            unit_price DECIMAL(14, 2),
            pipeline_run_id STRING
        ) USING DELTA
        """
    )

    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {catalog}.silver.customers (
            customer_id STRING,
            customer_segment STRING,
            city_id STRING,
            created_at_utc TIMESTAMP,
            pipeline_run_id STRING
        ) USING DELTA
        """
    )

    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {catalog}.silver.customer_profiles (
            customer_id STRING,
            customer_segment STRING,
            city_id STRING,
            valid_from_utc TIMESTAMP,
            valid_to_utc TIMESTAMP,
            pipeline_run_id STRING
        ) USING DELTA
        """
    )

    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {catalog}.silver.product_categories (
            product_id STRING,
            category_id STRING,
            category_name STRING,
            valid_from_utc TIMESTAMP,
            valid_to_utc TIMESTAMP,
            pipeline_run_id STRING
        ) USING DELTA
        """
    )

    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {catalog}.silver.inventory_snapshots (
            product_id STRING,
            location_id STRING,
            snapshot_date DATE,
            available_quantity INT,
            reserved_quantity INT,
            unit_cost DECIMAL(14, 2),
            pipeline_run_id STRING
        ) USING DELTA
        """
    )

    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {catalog}.silver.campaign_spend (
            spend_date DATE,
            campaign_id STRING,
            channel STRING,
            spend_amount DECIMAL(14, 2),
            pipeline_run_id STRING
        ) USING DELTA
        """
    )


def save_delta_table(
    spark: Any, df: Any, full_table_name: str, run_id: str
) -> int:
    """Simpan DataFrame ke Delta table dengan penanganan idempotency per run_id."""
    count = df.count()
    if count == 0:
        return 0

    try:
        spark.sql(
            f"DELETE FROM {full_table_name} WHERE pipeline_run_id = '{run_id}'"
        )
    except Exception:
        pass

    df.write.format("delta").mode("append").saveAsTable(full_table_name)
    return count


def run_silver_transformation(
    spark: Any, catalog: str = "retail_analytics", run_id: str | None = None
) -> dict[str, int]:
    """Eksekusi transformasi data Bronze ke Silver pada Databricks Delta Lake."""
    from pyspark.sql import functions as F
    from pyspark.sql.window import Window

    ensure_silver_tables(spark, catalog)

    # Tentukan run_id jika belum diberikan
    if not run_id:
        latest_row = (
            spark.table(f"{catalog}.bronze.raw_records")
            .select("pipeline_run_id")
            .orderBy(F.col("loaded_at_utc").desc(), F.col("id").desc())
            .first()
        )
        if latest_row:
            run_id = latest_row["pipeline_run_id"]
        else:
            raise ValueError(
                f"Tabel {catalog}.bronze.raw_records kosong, tidak ada run_id yang ditemukan!"
            )

    print(
        f"[{run_id}] Memulai Silver Transformation pada catalog '{catalog}'..."
    )

    bronze_df = spark.table(f"{catalog}.bronze.raw_records").filter(
        F.col("pipeline_run_id") == run_id
    )

    # 1. Reject Order Items dengan Quantity Negatif atau Nol
    order_items_raw = bronze_df.filter(
        F.col("file_name") == "order_items.json"
    )

    rejected_items_df = (
        order_items_raw.filter(
            F.coalesce(
                F.get_json_object("payload", "$.quantity").cast("int"), F.lit(0)
            )
            <= 0
        )
        .select(
            F.lit(run_id).alias("pipeline_run_id"),
            F.lit("order_items").alias("source_table"),
            F.get_json_object("payload", "$.order_item_id").alias(
                "record_identifier"
            ),
            F.lit("INVALID_QUANTITY_NEGATIVE_OR_ZERO").alias("reject_reason"),
            F.col("payload").cast("string").alias("payload"),
            F.current_timestamp().alias("rejected_at_utc"),
        )
    )
    reject_count = save_delta_table(
        spark, rejected_items_df, f"{catalog}.silver.rejected_records", run_id
    )

    # 2. Ingest Clean Order Items (Quantity > 0, deduplikasi per order_item_id)
    window_item = Window.partitionBy("order_item_id").orderBy(
        F.col("source_row_id").desc()
    )
    clean_items_df = (
        order_items_raw.filter(
            F.get_json_object("payload", "$.quantity").cast("int") > 0
        )
        .select(
            F.get_json_object("payload", "$.order_item_id").alias(
                "order_item_id"
            ),
            F.get_json_object("payload", "$.order_id").alias("order_id"),
            F.get_json_object("payload", "$.product_id").alias("product_id"),
            F.get_json_object("payload", "$.quantity")
            .cast("int")
            .alias("quantity"),
            F.get_json_object("payload", "$.unit_price")
            .cast("decimal(14,2)")
            .alias("unit_price"),
            F.coalesce(
                F.get_json_object("payload", "$.item_discount_amount").cast(
                    "decimal(14,2)"
                ),
                F.lit(0.00),
            ).alias("item_discount_amount"),
            F.coalesce(
                F.col("source_row_id"),
                F.get_json_object("payload", "$.source_row_id"),
            ).alias("source_row_id"),
            F.lit(run_id).alias("pipeline_run_id"),
        )
        .withColumn("rn", F.row_number().over(window_item))
        .filter(F.col("rn") == 1)
        .drop("rn", "source_row_id")
    )
    items_count = save_delta_table(
        spark, clean_items_df, f"{catalog}.silver.order_items", run_id
    )

    # 3. Deduplikasi dan Normalisasi Orders (Paling mutakhir via updated_at_utc DESC)
    orders_raw = bronze_df.filter(F.col("file_name") == "orders.json")
    window_order = Window.partitionBy("order_id").orderBy(
        F.col("updated_at_utc").desc()
    )
    clean_orders_df = (
        orders_raw.select(
            F.get_json_object("payload", "$.order_id").alias("order_id"),
            F.get_json_object("payload", "$.customer_id").alias("customer_id"),
            F.to_timestamp(
                F.get_json_object("payload", "$.ordered_at_utc")
            ).alias("ordered_at_utc"),
            F.get_json_object("payload", "$.sales_channel").alias(
                "sales_channel"
            ),
            F.get_json_object("payload", "$.status").alias("order_status"),
            F.coalesce(
                F.get_json_object("payload", "$.shipping_revenue").cast(
                    "decimal(14,2)"
                ),
                F.lit(0.00),
            ).alias("shipping_revenue"),
            F.get_json_object("payload", "$.store_id").alias("store_id"),
            F.to_timestamp(
                F.get_json_object("payload", "$.updated_at_utc")
            ).alias("updated_at_utc"),
            F.lit(run_id).alias("pipeline_run_id"),
        )
        .withColumn("rn", F.row_number().over(window_order))
        .filter(F.col("rn") == 1)
        .drop("rn")
    )
    orders_count = save_delta_table(
        spark, clean_orders_df, f"{catalog}.silver.orders", run_id
    )

    # 4. Ingest Payments (Event resolution & deduplikasi event ke aggregated state)
    payments_raw = bronze_df.filter(
        F.col("file_name") == "payment_events.json"
    ).filter(
        F.get_json_object("payload", "$.event_type") == "PAYMENT_CAPTURED"
    )

    window_pay_evt = Window.partitionBy("event_id").orderBy(
        F.col("occurred_at_utc").desc()
    )
    dedup_pay_events = (
        payments_raw.select(
            F.coalesce(
                F.col("source_row_id"),
                F.get_json_object("payload", "$.event_id"),
            ).alias("event_id"),
            F.get_json_object("payload", "$.payload.payment_id").alias(
                "payment_id"
            ),
            F.get_json_object("payload", "$.payload.order_id").alias(
                "order_id"
            ),
            F.get_json_object("payload", "$.payload.amount")
            .cast("decimal(14,2)")
            .alias("amount"),
            F.to_timestamp(
                F.get_json_object("payload", "$.occurred_at_utc")
            ).alias("occurred_at_utc"),
        )
        .withColumn("rn", F.row_number().over(window_pay_evt))
        .filter(F.col("rn") == 1)
        .drop("rn")
    )

    clean_payments_df = dedup_pay_events.groupBy("payment_id", "order_id").agg(
        F.sum("amount").cast("decimal(14,2)").alias("captured_amount"),
        F.lit("PAYMENT_CAPTURED").alias("payment_status"),
        F.max("occurred_at_utc").alias("occurred_at_utc"),
        F.lit(run_id).alias("pipeline_run_id"),
    )
    payments_count = save_delta_table(
        spark, clean_payments_df, f"{catalog}.silver.payments", run_id
    )

    # 5. Ingest Refunds (Deduplikasi per refund_id, ambil status REFUND_COMPLETED)
    refunds_raw = bronze_df.filter(F.col("file_name") == "refund_events.json")
    window_ref = Window.partitionBy("refund_id").orderBy(
        F.when(F.col("event_type") == "REFUND_COMPLETED", F.lit(1)).otherwise(
            F.lit(2)
        ),
        F.col("occurred_at_utc").desc(),
    )
    clean_refunds_df = (
        refunds_raw.select(
            F.get_json_object("payload", "$.payload.refund_id").alias(
                "refund_id"
            ),
            F.get_json_object("payload", "$.payload.order_id").alias(
                "order_id"
            ),
            F.get_json_object("payload", "$.payload.amount")
            .cast("decimal(14,2)")
            .alias("refund_amount"),
            F.get_json_object("payload", "$.event_type").alias("refund_status"),
            F.get_json_object("payload", "$.event_type").alias("event_type"),
            F.to_timestamp(
                F.get_json_object("payload", "$.occurred_at_utc")
            ).alias("occurred_at_utc"),
            F.lit(run_id).alias("pipeline_run_id"),
        )
        .withColumn("rn", F.row_number().over(window_ref))
        .filter(F.col("rn") == 1)
        .drop("rn", "event_type")
    )
    refunds_count = save_delta_table(
        spark, clean_refunds_df, f"{catalog}.silver.refunds", run_id
    )

    # 6. Ingest Returns (Deduplikasi per return_id, ambil status paling mutakhir)
    returns_raw = bronze_df.filter(F.col("file_name") == "return_events.json")
    window_ret = Window.partitionBy("return_id").orderBy(
        F.col("occurred_at_utc").desc()
    )
    clean_returns_df = (
        returns_raw.select(
            F.get_json_object("payload", "$.payload.return_id").alias(
                "return_id"
            ),
            F.get_json_object("payload", "$.payload.order_id").alias(
                "order_id"
            ),
            F.get_json_object("payload", "$.event_type").alias("return_status"),
            F.to_timestamp(
                F.get_json_object("payload", "$.occurred_at_utc")
            ).alias("occurred_at_utc"),
            F.lit(run_id).alias("pipeline_run_id"),
        )
        .withColumn("rn", F.row_number().over(window_ret))
        .filter(F.col("rn") == 1)
        .drop("rn")
    )
    returns_count = save_delta_table(
        spark, clean_returns_df, f"{catalog}.silver.returns", run_id
    )

    # 7. Ingest Support Tickets
    support_raw = bronze_df.filter(F.col("file_name") == "support_events.json")
    window_supp = Window.partitionBy("ticket_id").orderBy(
        F.col("occurred_at_utc").desc()
    )
    clean_support_df = (
        support_raw.select(
            F.get_json_object("payload", "$.payload.ticket_id").alias(
                "ticket_id"
            ),
            F.get_json_object("payload", "$.payload.customer_id").alias(
                "customer_id"
            ),
            F.get_json_object("payload", "$.payload.order_id").alias(
                "order_id"
            ),
            F.get_json_object("payload", "$.payload.reason").alias("reason"),
            F.get_json_object("payload", "$.event_type").alias("event_type"),
            F.to_timestamp(
                F.get_json_object("payload", "$.occurred_at_utc")
            ).alias("occurred_at_utc"),
            F.lit(run_id).alias("pipeline_run_id"),
        )
        .withColumn("rn", F.row_number().over(window_supp))
        .filter(F.col("rn") == 1)
        .drop("rn")
    )
    support_count = save_delta_table(
        spark, clean_support_df, f"{catalog}.silver.support_tickets", run_id
    )

    # 8. Ingest Web Events (Deduplikasi per event_id)
    web_raw = bronze_df.filter(F.col("file_name") == "web_events.json")
    window_web = Window.partitionBy("event_id").orderBy(
        F.col("occurred_at_utc").desc()
    )
    clean_web_df = (
        web_raw.select(
            F.coalesce(
                F.col("source_row_id"),
                F.get_json_object("payload", "$.event_id"),
            ).alias("event_id"),
            F.get_json_object("payload", "$.event_type").alias("event_type"),
            F.get_json_object("payload", "$.payload.session_id").alias(
                "session_id"
            ),
            F.get_json_object("payload", "$.payload.customer_id").alias(
                "customer_id"
            ),
            F.get_json_object("payload", "$.payload.order_id").alias(
                "order_id"
            ),
            F.get_json_object("payload", "$.payload.channel").alias("channel"),
            F.get_json_object("payload", "$.payload.campaign_id").alias(
                "campaign_id"
            ),
            F.to_timestamp(
                F.get_json_object("payload", "$.occurred_at_utc")
            ).alias("occurred_at_utc"),
            F.lit(run_id).alias("pipeline_run_id"),
        )
        .withColumn("rn", F.row_number().over(window_web))
        .filter(F.col("rn") == 1)
        .drop("rn")
    )
    web_count = save_delta_table(
        spark, clean_web_df, f"{catalog}.silver.web_events", run_id
    )

    # 9. Ingest Promotions
    promos_raw = bronze_df.filter(F.col("file_name") == "promotions.json")
    window_promo = Window.partitionBy("promotion_id").orderBy(
        F.col("source_row_id").desc()
    )
    clean_promos_df = (
        promos_raw.select(
            F.get_json_object("payload", "$.promotion_id").alias(
                "promotion_id"
            ),
            F.get_json_object("payload", "$.promotion_code").alias(
                "promotion_code"
            ),
            F.get_json_object("payload", "$.promotion_type").alias(
                "promotion_type"
            ),
            F.get_json_object("payload", "$.discount_rate")
            .cast("decimal(14,4)")
            .alias("discount_rate"),
            F.to_date(F.get_json_object("payload", "$.start_date")).alias(
                "start_date"
            ),
            F.to_date(F.get_json_object("payload", "$.end_date")).alias(
                "end_date"
            ),
            F.coalesce(
                F.col("source_row_id"),
                F.get_json_object("payload", "$.source_row_id"),
            ).alias("source_row_id"),
            F.lit(run_id).alias("pipeline_run_id"),
        )
        .withColumn("rn", F.row_number().over(window_promo))
        .filter(F.col("rn") == 1)
        .drop("rn", "source_row_id")
    )
    promos_count = save_delta_table(
        spark, clean_promos_df, f"{catalog}.silver.promotions", run_id
    )

    # 10. Ingest Order Promotions
    order_promos_raw = bronze_df.filter(
        F.col("file_name") == "order_promotions.json"
    )
    window_op = Window.partitionBy("order_id", "promotion_id").orderBy(
        F.col("source_row_id").desc()
    )
    clean_order_promos_df = (
        order_promos_raw.select(
            F.get_json_object("payload", "$.order_id").alias("order_id"),
            F.get_json_object("payload", "$.promotion_id").alias(
                "promotion_id"
            ),
            F.coalesce(
                F.get_json_object("payload", "$.discount_amount").cast(
                    "decimal(14,2)"
                ),
                F.lit(0.00),
            ).alias("discount_amount"),
            F.coalesce(
                F.col("source_row_id"),
                F.get_json_object("payload", "$.source_row_id"),
            ).alias("source_row_id"),
            F.lit(run_id).alias("pipeline_run_id"),
        )
        .withColumn("rn", F.row_number().over(window_op))
        .filter(F.col("rn") == 1)
        .drop("rn", "source_row_id")
    )
    order_promos_count = save_delta_table(
        spark,
        clean_order_promos_df,
        f"{catalog}.silver.order_promotions",
        run_id,
    )

    # 11. Ingest Products
    products_raw = bronze_df.filter(F.col("file_name") == "products.json")
    window_prod = Window.partitionBy("product_id").orderBy(
        F.col("source_row_id").desc()
    )
    clean_products_df = (
        products_raw.select(
            F.get_json_object("payload", "$.product_id").alias("product_id"),
            F.get_json_object("payload", "$.sku").alias("sku"),
            F.get_json_object("payload", "$.product_name").alias(
                "product_name"
            ),
            F.get_json_object("payload", "$.unit_price")
            .cast("decimal(14,2)")
            .alias("unit_price"),
            F.coalesce(
                F.col("source_row_id"),
                F.get_json_object("payload", "$.source_row_id"),
            ).alias("source_row_id"),
            F.lit(run_id).alias("pipeline_run_id"),
        )
        .withColumn("rn", F.row_number().over(window_prod))
        .filter(F.col("rn") == 1)
        .drop("rn", "source_row_id")
    )
    products_count = save_delta_table(
        spark, clean_products_df, f"{catalog}.silver.products", run_id
    )

    # 12. Ingest Customers
    customers_raw = bronze_df.filter(F.col("file_name") == "customers.json")
    window_cust = Window.partitionBy("customer_id").orderBy(
        F.col("created_at_utc").desc()
    )
    clean_customers_df = (
        customers_raw.select(
            F.get_json_object("payload", "$.customer_id").alias("customer_id"),
            F.get_json_object("payload", "$.customer_segment").alias(
                "customer_segment"
            ),
            F.get_json_object("payload", "$.city_id").alias("city_id"),
            F.to_timestamp(
                F.get_json_object("payload", "$.created_at_utc")
            ).alias("created_at_utc"),
            F.lit(run_id).alias("pipeline_run_id"),
        )
        .withColumn("rn", F.row_number().over(window_cust))
        .filter(F.col("rn") == 1)
        .drop("rn")
    )
    customers_count = save_delta_table(
        spark, clean_customers_df, f"{catalog}.silver.customers", run_id
    )

    # 13. Ingest Customer Profiles
    cust_prof_raw = bronze_df.filter(
        F.col("file_name") == "customer_profiles.json"
    )
    window_cp = Window.partitionBy("customer_id", "valid_from_utc").orderBy(
        F.col("source_row_id").desc()
    )
    clean_cust_prof_df = (
        cust_prof_raw.select(
            F.get_json_object("payload", "$.customer_id").alias("customer_id"),
            F.get_json_object("payload", "$.customer_segment").alias(
                "customer_segment"
            ),
            F.get_json_object("payload", "$.city_id").alias("city_id"),
            F.to_timestamp(
                F.get_json_object("payload", "$.valid_from_utc")
            ).alias("valid_from_utc"),
            F.to_timestamp(
                F.get_json_object("payload", "$.valid_to_utc")
            ).alias("valid_to_utc"),
            F.coalesce(
                F.col("source_row_id"),
                F.get_json_object("payload", "$.source_row_id"),
            ).alias("source_row_id"),
            F.lit(run_id).alias("pipeline_run_id"),
        )
        .withColumn("rn", F.row_number().over(window_cp))
        .filter(F.col("rn") == 1)
        .drop("rn", "source_row_id")
    )
    cust_prof_count = save_delta_table(
        spark,
        clean_cust_prof_df,
        f"{catalog}.silver.customer_profiles",
        run_id,
    )

    # 14. Ingest Product Categories
    prod_cat_raw = bronze_df.filter(
        F.col("file_name") == "product_categories.json"
    )
    window_pc = Window.partitionBy("product_id", "valid_from_utc").orderBy(
        F.col("source_row_id").desc()
    )
    clean_prod_cat_df = (
        prod_cat_raw.select(
            F.get_json_object("payload", "$.product_id").alias("product_id"),
            F.get_json_object("payload", "$.category_id").alias("category_id"),
            F.get_json_object("payload", "$.category_name").alias(
                "category_name"
            ),
            F.to_timestamp(
                F.get_json_object("payload", "$.valid_from_utc")
            ).alias("valid_from_utc"),
            F.to_timestamp(
                F.get_json_object("payload", "$.valid_to_utc")
            ).alias("valid_to_utc"),
            F.coalesce(
                F.col("source_row_id"),
                F.get_json_object("payload", "$.source_row_id"),
            ).alias("source_row_id"),
            F.lit(run_id).alias("pipeline_run_id"),
        )
        .withColumn("rn", F.row_number().over(window_pc))
        .filter(F.col("rn") == 1)
        .drop("rn", "source_row_id")
    )
    prod_cat_count = save_delta_table(
        spark,
        clean_prod_cat_df,
        f"{catalog}.silver.product_categories",
        run_id,
    )

    # 15. Ingest Inventory Snapshots
    inv_raw = bronze_df.filter(
        F.col("file_name") == "inventory_snapshots.csv"
    )
    window_inv = Window.partitionBy(
        "product_id", "location_id", "snapshot_date"
    ).orderBy(F.col("loaded_at_utc").desc())
    clean_inv_df = (
        inv_raw.select(
            F.get_json_object("payload", "$.product_id").alias("product_id"),
            F.get_json_object("payload", "$.location_id").alias("location_id"),
            F.to_date(F.get_json_object("payload", "$.snapshot_date")).alias(
                "snapshot_date"
            ),
            F.get_json_object("payload", "$.available_quantity")
            .cast("int")
            .alias("available_quantity"),
            F.get_json_object("payload", "$.reserved_quantity")
            .cast("int")
            .alias("reserved_quantity"),
            F.get_json_object("payload", "$.unit_cost")
            .cast("decimal(14,2)")
            .alias("unit_cost"),
            F.col("loaded_at_utc"),
            F.lit(run_id).alias("pipeline_run_id"),
        )
        .withColumn("rn", F.row_number().over(window_inv))
        .filter(F.col("rn") == 1)
        .drop("rn", "loaded_at_utc")
    )
    inv_count = save_delta_table(
        spark,
        clean_inv_df,
        f"{catalog}.silver.inventory_snapshots",
        run_id,
    )

    # 16. Ingest Campaign Spend
    spend_raw = bronze_df.filter(F.col("file_name") == "campaign_spend.csv")
    window_spend = Window.partitionBy(
        "spend_date", "campaign_id", "channel"
    ).orderBy(F.col("loaded_at_utc").desc())
    clean_spend_df = (
        spend_raw.select(
            F.to_date(F.get_json_object("payload", "$.spend_date")).alias(
                "spend_date"
            ),
            F.get_json_object("payload", "$.campaign_id").alias("campaign_id"),
            F.get_json_object("payload", "$.channel").alias("channel"),
            F.get_json_object("payload", "$.spend_amount")
            .cast("decimal(14,2)")
            .alias("spend_amount"),
            F.col("loaded_at_utc"),
            F.lit(run_id).alias("pipeline_run_id"),
        )
        .withColumn("rn", F.row_number().over(window_spend))
        .filter(F.col("rn") == 1)
        .drop("rn", "loaded_at_utc")
    )
    spend_count = save_delta_table(
        spark, clean_spend_df, f"{catalog}.silver.campaign_spend", run_id
    )

    # Total Clean Count across all 15 clean Silver tables
    total_clean_count = (
        items_count
        + orders_count
        + payments_count
        + refunds_count
        + returns_count
        + support_count
        + web_count
        + promos_count
        + order_promos_count
        + products_count
        + customers_count
        + cust_prof_count
        + prod_cat_count
        + inv_count
        + spend_count
    )

    print(
        f"[{run_id}] Silver Transformation Selesai: {total_clean_count} records clean, {reject_count} records rejected."
    )

    # Update metadata ke ops.pipeline_runs
    try:
        spark.sql(
            f"""
            UPDATE {catalog}.ops.pipeline_runs
            SET records_clean = {total_clean_count},
                records_rejected = {reject_count},
                current_stage = 'silver'
            WHERE run_id = '{run_id}'
            """
        )
    except Exception as e:
        print(f"Warning: Could not update ops.pipeline_runs: {e}")

    return {
        "clean_count": total_clean_count,
        "clean_orders": orders_count,
        "reject_count": reject_count,
        "rejected_records": reject_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run PySpark Silver Transformation on Databricks"
    )
    parser.add_argument(
        "--catalog",
        type=str,
        default="retail_analytics",
        help="Target Unity Catalog name",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Pipeline run ID to process (default: latest)",
    )
    args = parser.parse_args()

    spark = get_spark()
    run_silver_transformation(spark, catalog=args.catalog, run_id=args.run_id)


if __name__ == "__main__":
    main()
