-- ============================================================================
-- Databricks Delta Lake DDLs for Unity Catalog: Bronze, Silver, Gold, Ops
-- ============================================================================

-- ----------------------------------------------------------------------------
-- BRONZE LAYER
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${catalog_name}.bronze.raw_records (
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    pipeline_run_id STRING NOT NULL,
    source_category STRING NOT NULL,
    file_name STRING NOT NULL,
    source_row_id STRING,
    payload STRING NOT NULL,
    loaded_at_utc TIMESTAMP,
    CONSTRAINT pk_bronze_raw_records PRIMARY KEY (id) NOT ENFORCED
)
USING DELTA
COMMENT 'Bronze raw record landing table preserving original payloads and source metadata';

-- ----------------------------------------------------------------------------
-- SILVER LAYER: REJECTS & CLEANSING
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${catalog_name}.silver.rejected_records (
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    pipeline_run_id STRING NOT NULL,
    source_table STRING NOT NULL,
    record_identifier STRING,
    reject_reason STRING NOT NULL,
    payload STRING NOT NULL,
    rejected_at_utc TIMESTAMP,
    CONSTRAINT pk_silver_rejected_records PRIMARY KEY (id) NOT ENFORCED
)
USING DELTA
COMMENT 'Silver quarantined records rejected by business rules and quality checks';

CREATE TABLE IF NOT EXISTS ${catalog_name}.silver.orders (
    order_id STRING NOT NULL,
    customer_id STRING NOT NULL,
    ordered_at_utc TIMESTAMP NOT NULL,
    sales_channel STRING NOT NULL,
    order_status STRING NOT NULL,
    shipping_revenue DECIMAL(14, 2) NOT NULL,
    store_id STRING,
    updated_at_utc TIMESTAMP NOT NULL,
    pipeline_run_id STRING NOT NULL,
    CONSTRAINT pk_silver_orders PRIMARY KEY (order_id, pipeline_run_id) NOT ENFORCED
)
USING DELTA
COMMENT 'Silver cleansed and deduplicated orders';

CREATE TABLE IF NOT EXISTS ${catalog_name}.silver.order_items (
    order_item_id STRING NOT NULL,
    order_id STRING NOT NULL,
    product_id STRING NOT NULL,
    quantity INT NOT NULL,
    unit_price DECIMAL(14, 2) NOT NULL,
    item_discount_amount DECIMAL(14, 2) NOT NULL,
    pipeline_run_id STRING NOT NULL,
    CONSTRAINT pk_silver_order_items PRIMARY KEY (order_item_id, pipeline_run_id) NOT ENFORCED
)
USING DELTA
COMMENT 'Silver cleansed order line items with positive quantities';

CREATE TABLE IF NOT EXISTS ${catalog_name}.silver.payments (
    payment_id STRING NOT NULL,
    order_id STRING NOT NULL,
    captured_amount DECIMAL(14, 2) NOT NULL,
    payment_status STRING NOT NULL,
    occurred_at_utc TIMESTAMP NOT NULL,
    pipeline_run_id STRING NOT NULL,
    CONSTRAINT pk_silver_payments PRIMARY KEY (payment_id, pipeline_run_id) NOT ENFORCED
)
USING DELTA
COMMENT 'Silver captured payment transactions';

CREATE TABLE IF NOT EXISTS ${catalog_name}.silver.refunds (
    refund_id STRING NOT NULL,
    order_id STRING NOT NULL,
    refund_amount DECIMAL(14, 2) NOT NULL,
    refund_status STRING NOT NULL,
    occurred_at_utc TIMESTAMP NOT NULL,
    pipeline_run_id STRING NOT NULL,
    CONSTRAINT pk_silver_refunds PRIMARY KEY (refund_id, pipeline_run_id) NOT ENFORCED
)
USING DELTA
COMMENT 'Silver completed refund transactions';

CREATE TABLE IF NOT EXISTS ${catalog_name}.silver.returns (
    return_id STRING NOT NULL,
    order_id STRING NOT NULL,
    return_status STRING NOT NULL,
    occurred_at_utc TIMESTAMP NOT NULL,
    pipeline_run_id STRING NOT NULL,
    CONSTRAINT pk_silver_returns PRIMARY KEY (return_id, pipeline_run_id) NOT ENFORCED
)
USING DELTA
COMMENT 'Silver return events and statuses';

CREATE TABLE IF NOT EXISTS ${catalog_name}.silver.customer_profiles (
    customer_id STRING NOT NULL,
    customer_segment STRING,
    city_id STRING,
    valid_from_utc TIMESTAMP NOT NULL,
    valid_to_utc TIMESTAMP NOT NULL,
    pipeline_run_id STRING NOT NULL,
    CONSTRAINT pk_silver_customer_profiles PRIMARY KEY (customer_id, valid_from_utc, pipeline_run_id) NOT ENFORCED
)
USING DELTA
COMMENT 'Silver SCD Type 2 customer profiles and tier histories';

CREATE TABLE IF NOT EXISTS ${catalog_name}.silver.product_categories (
    product_id STRING NOT NULL,
    category_id STRING NOT NULL,
    category_name STRING NOT NULL,
    valid_from_utc TIMESTAMP NOT NULL,
    valid_to_utc TIMESTAMP NOT NULL,
    pipeline_run_id STRING NOT NULL,
    CONSTRAINT pk_silver_product_categories PRIMARY KEY (product_id, valid_from_utc, pipeline_run_id) NOT ENFORCED
)
USING DELTA
COMMENT 'Silver SCD Type 2 product categories';

CREATE TABLE IF NOT EXISTS ${catalog_name}.silver.inventory_snapshots (
    product_id STRING NOT NULL,
    location_id STRING NOT NULL,
    snapshot_date DATE NOT NULL,
    available_quantity INT NOT NULL,
    reserved_quantity INT NOT NULL,
    unit_cost DECIMAL(14, 2),
    pipeline_run_id STRING NOT NULL,
    CONSTRAINT pk_silver_inventory_snapshots PRIMARY KEY (product_id, location_id, snapshot_date, pipeline_run_id) NOT ENFORCED
)
USING DELTA
COMMENT 'Silver daily inventory snapshots per product and location';

CREATE TABLE IF NOT EXISTS ${catalog_name}.silver.campaign_spend (
    spend_date DATE NOT NULL,
    campaign_id STRING NOT NULL,
    channel STRING NOT NULL,
    spend_amount DECIMAL(14, 2) NOT NULL,
    pipeline_run_id STRING NOT NULL,
    CONSTRAINT pk_silver_campaign_spend PRIMARY KEY (spend_date, campaign_id, channel, pipeline_run_id) NOT ENFORCED
)
USING DELTA
COMMENT 'Silver marketing campaign daily spend across channels';

CREATE TABLE IF NOT EXISTS ${catalog_name}.silver.support_tickets (
    ticket_id STRING NOT NULL,
    customer_id STRING NOT NULL,
    order_id STRING,
    reason STRING,
    event_type STRING NOT NULL,
    occurred_at_utc TIMESTAMP NOT NULL,
    pipeline_run_id STRING NOT NULL,
    CONSTRAINT pk_silver_support_tickets PRIMARY KEY (ticket_id, pipeline_run_id) NOT ENFORCED
)
USING DELTA
COMMENT 'Silver customer support tickets and issue events';

CREATE TABLE IF NOT EXISTS ${catalog_name}.silver.promotions (
    promotion_id STRING NOT NULL,
    promotion_code STRING NOT NULL,
    promotion_type STRING NOT NULL,
    discount_rate DECIMAL(14, 4) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    pipeline_run_id STRING NOT NULL,
    CONSTRAINT pk_silver_promotions PRIMARY KEY (promotion_id, pipeline_run_id) NOT ENFORCED
)
USING DELTA
COMMENT 'Silver active promotion campaigns and discount rates';

CREATE TABLE IF NOT EXISTS ${catalog_name}.silver.order_promotions (
    order_id STRING NOT NULL,
    promotion_id STRING NOT NULL,
    discount_amount DECIMAL(14, 2) NOT NULL,
    pipeline_run_id STRING NOT NULL,
    CONSTRAINT pk_silver_order_promotions PRIMARY KEY (order_id, promotion_id, pipeline_run_id) NOT ENFORCED
)
USING DELTA
COMMENT 'Silver promotion bridge table attributing discounts to orders';

CREATE TABLE IF NOT EXISTS ${catalog_name}.silver.web_events (
    event_id STRING NOT NULL,
    event_type STRING NOT NULL,
    session_id STRING,
    customer_id STRING,
    order_id STRING,
    channel STRING,
    campaign_id STRING,
    occurred_at_utc TIMESTAMP NOT NULL,
    pipeline_run_id STRING NOT NULL,
    CONSTRAINT pk_silver_web_events PRIMARY KEY (event_id, pipeline_run_id) NOT ENFORCED
)
USING DELTA
COMMENT 'Silver clickstream, funnel, and purchase web events';

CREATE TABLE IF NOT EXISTS ${catalog_name}.silver.products (
    product_id STRING NOT NULL,
    sku STRING NOT NULL,
    product_name STRING NOT NULL,
    unit_price DECIMAL(14, 2) NOT NULL,
    pipeline_run_id STRING NOT NULL,
    CONSTRAINT pk_silver_products PRIMARY KEY (product_id, pipeline_run_id) NOT ENFORCED
)
USING DELTA
COMMENT 'Silver canonical product catalog';

CREATE TABLE IF NOT EXISTS ${catalog_name}.silver.customers (
    customer_id STRING NOT NULL,
    customer_segment STRING,
    city_id STRING,
    created_at_utc TIMESTAMP NOT NULL,
    pipeline_run_id STRING NOT NULL,
    CONSTRAINT pk_silver_customers PRIMARY KEY (customer_id, pipeline_run_id) NOT ENFORCED
)
USING DELTA
COMMENT 'Silver canonical customer master records';

-- ----------------------------------------------------------------------------
-- GOLD LAYER: ANALYTICS & 360 VIEWS
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${catalog_name}.gold.order_360 (
    order_id STRING NOT NULL,
    customer_id STRING NOT NULL,
    order_date DATE NOT NULL,
    sales_channel STRING NOT NULL,
    store_id STRING,
    gross_merchandise_value DECIMAL(14, 2) NOT NULL,
    discount_amount DECIMAL(14, 2) NOT NULL,
    shipping_revenue DECIMAL(14, 2) NOT NULL,
    captured_payment_amount DECIMAL(14, 2) NOT NULL,
    refunded_amount DECIMAL(14, 2) NOT NULL,
    net_revenue DECIMAL(14, 2) NOT NULL,
    item_count INT NOT NULL,
    unit_quantity INT NOT NULL,
    order_status STRING NOT NULL,
    payment_status STRING NOT NULL,
    return_status STRING NOT NULL,
    promotion_count INT NOT NULL,
    first_order_flag BOOLEAN NOT NULL,
    pipeline_run_id STRING NOT NULL,
    CONSTRAINT pk_gold_order_360 PRIMARY KEY (order_id) NOT ENFORCED
)
USING DELTA
COMMENT 'Gold unified 360-degree view of completed and processed orders';

CREATE TABLE IF NOT EXISTS ${catalog_name}.gold.customer_daily (
    customer_id STRING NOT NULL,
    metric_date DATE NOT NULL,
    order_count INT NOT NULL,
    unit_quantity INT NOT NULL,
    gross_revenue DECIMAL(14, 2) NOT NULL,
    net_revenue DECIMAL(14, 2) NOT NULL,
    refund_amount DECIMAL(14, 2) NOT NULL,
    return_count INT NOT NULL,
    support_contacts INT NOT NULL,
    active_channel STRING,
    new_customer_flag BOOLEAN NOT NULL,
    repeat_customer_flag BOOLEAN NOT NULL,
    pipeline_run_id STRING NOT NULL,
    CONSTRAINT pk_gold_customer_daily PRIMARY KEY (customer_id, metric_date) NOT ENFORCED
)
USING DELTA
COMMENT 'Gold daily customer behavioral, purchase, and support aggregations';

CREATE TABLE IF NOT EXISTS ${catalog_name}.gold.product_daily (
    product_id STRING NOT NULL,
    metric_date DATE NOT NULL,
    active_category STRING,
    units_sold INT NOT NULL,
    order_count INT NOT NULL,
    gross_revenue DECIMAL(14, 2) NOT NULL,
    net_revenue DECIMAL(14, 2) NOT NULL,
    refunded_units INT NOT NULL,
    available_inventory INT,
    reserved_inventory INT,
    stockout_flag BOOLEAN,
    promotion_count INT NOT NULL,
    pipeline_run_id STRING NOT NULL,
    CONSTRAINT pk_gold_product_daily PRIMARY KEY (product_id, metric_date) NOT ENFORCED
)
USING DELTA
COMMENT 'Gold daily product sales, stockout status, and returns aggregation';

CREATE TABLE IF NOT EXISTS ${catalog_name}.gold.channel_campaign_daily (
    metric_date DATE NOT NULL,
    sales_channel STRING NOT NULL,
    campaign_id STRING NOT NULL,
    campaign_spend DECIMAL(14, 2) NOT NULL,
    attributed_orders INT NOT NULL,
    attributed_customers INT NOT NULL,
    gross_revenue DECIMAL(14, 2) NOT NULL,
    net_revenue DECIMAL(14, 2) NOT NULL,
    refunds DECIMAL(14, 2) NOT NULL,
    roas DECIMAL(14, 4),
    conversion_rate DECIMAL(14, 4),
    pipeline_run_id STRING NOT NULL,
    CONSTRAINT pk_gold_channel_campaign_daily PRIMARY KEY (metric_date, sales_channel, campaign_id) NOT ENFORCED
)
USING DELTA
COMMENT 'Gold daily marketing performance, attribution, ROAS, and conversion metrics';

CREATE TABLE IF NOT EXISTS ${catalog_name}.gold.executive_kpis_daily (
    metric_date DATE NOT NULL,
    total_orders INT NOT NULL,
    gross_revenue DECIMAL(14, 2) NOT NULL,
    net_revenue DECIMAL(14, 2) NOT NULL,
    average_order_value DECIMAL(14, 2) NOT NULL,
    refund_rate DECIMAL(14, 4) NOT NULL,
    return_rate DECIMAL(14, 4) NOT NULL,
    repeat_customer_rate DECIMAL(14, 4) NOT NULL,
    stockout_rate DECIMAL(14, 4) NOT NULL,
    active_customers INT NOT NULL,
    support_contact_rate DECIMAL(14, 4) NOT NULL,
    data_freshness_utc TIMESTAMP NOT NULL,
    pipeline_run_id STRING NOT NULL,
    CONSTRAINT pk_gold_executive_kpis_daily PRIMARY KEY (metric_date) NOT ENFORCED
)
USING DELTA
COMMENT 'Gold executive summary KPIs with daily high-level business indicators';

-- ----------------------------------------------------------------------------
-- OPS LAYER: LIFECYCLE & QUALITY AUDITS
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${catalog_name}.ops.pipeline_runs (
    run_id STRING NOT NULL,
    started_at_utc TIMESTAMP NOT NULL,
    completed_at_utc TIMESTAMP,
    status STRING NOT NULL,
    current_stage STRING,
    error_message STRING,
    records_read INT,
    records_clean INT,
    records_rejected INT,
    created_at_utc TIMESTAMP,
    CONSTRAINT pk_ops_pipeline_runs PRIMARY KEY (run_id) NOT ENFORCED
)
USING DELTA
COMMENT 'Ops pipeline execution runs and lifecycle status';

CREATE TABLE IF NOT EXISTS ${catalog_name}.ops.ingested_files (
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    run_id STRING NOT NULL,
    file_name STRING NOT NULL,
    file_path STRING NOT NULL,
    record_count INT NOT NULL,
    checksum_sha256 STRING,
    status STRING NOT NULL,
    ingested_at_utc TIMESTAMP,
    CONSTRAINT pk_ops_ingested_files PRIMARY KEY (id) NOT ENFORCED
)
USING DELTA
COMMENT 'Ops ingested source files metadata, record counts, and SHA-256 checksums';

CREATE TABLE IF NOT EXISTS ${catalog_name}.ops.quality_checks (
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    run_id STRING NOT NULL,
    check_name STRING NOT NULL,
    check_stage STRING NOT NULL,
    passed BOOLEAN NOT NULL,
    details_json STRING,
    checked_at_utc TIMESTAMP,
    CONSTRAINT pk_ops_quality_checks PRIMARY KEY (id) NOT ENFORCED
)
USING DELTA
COMMENT 'Ops data quality check execution records and reconciliation audits';
