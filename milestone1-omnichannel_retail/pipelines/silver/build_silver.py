"""Transformasi Bronze ke Silver: Pembersihan, Deduplikasi, Rejeksi, dan Normalisasi UTC."""

from __future__ import annotations

from shared.db import connect


def build_silver(run_id: str, target: str = "local") -> dict[str, int]:
    """Eksekusi transformasi dan pembersihan data dari bronze ke silver."""
    print(f"[{run_id}] Memulai pembangunan Silver Layer...")

    with connect(target) as conn:
        # 0. Pastikan Schema dan Seluruh Tabel Silver Terdefinisi
        conn.execute("CREATE SCHEMA IF NOT EXISTS silver;")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS silver.rejected_records (
                id BIGSERIAL PRIMARY KEY,
                pipeline_run_id TEXT NOT NULL,
                source_table TEXT NOT NULL,
                record_identifier TEXT,
                reject_reason TEXT NOT NULL,
                payload JSONB NOT NULL,
                rejected_at_utc TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS silver.orders (
                order_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                ordered_at_utc TIMESTAMPTZ NOT NULL,
                sales_channel TEXT NOT NULL,
                order_status TEXT NOT NULL,
                shipping_revenue NUMERIC(14, 2) NOT NULL DEFAULT 0,
                store_id TEXT,
                updated_at_utc TIMESTAMPTZ NOT NULL,
                pipeline_run_id TEXT NOT NULL,
                PRIMARY KEY (order_id, pipeline_run_id)
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS silver.order_items (
                order_item_id TEXT NOT NULL,
                order_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price NUMERIC(14, 2) NOT NULL,
                item_discount_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
                pipeline_run_id TEXT NOT NULL,
                PRIMARY KEY (order_item_id, pipeline_run_id)
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS silver.payments (
                payment_id TEXT NOT NULL,
                order_id TEXT NOT NULL,
                captured_amount NUMERIC(14, 2) NOT NULL,
                payment_status TEXT NOT NULL,
                occurred_at_utc TIMESTAMPTZ NOT NULL,
                pipeline_run_id TEXT NOT NULL,
                PRIMARY KEY (payment_id, pipeline_run_id)
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS silver.refunds (
                refund_id TEXT NOT NULL,
                order_id TEXT NOT NULL,
                refund_amount NUMERIC(14, 2) NOT NULL,
                refund_status TEXT NOT NULL,
                occurred_at_utc TIMESTAMPTZ NOT NULL,
                pipeline_run_id TEXT NOT NULL,
                PRIMARY KEY (refund_id, pipeline_run_id)
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS silver.returns (
                return_id TEXT NOT NULL,
                order_id TEXT NOT NULL,
                return_status TEXT NOT NULL,
                occurred_at_utc TIMESTAMPTZ NOT NULL,
                pipeline_run_id TEXT NOT NULL,
                PRIMARY KEY (return_id, pipeline_run_id)
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS silver.support_tickets (
                ticket_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                order_id TEXT,
                reason TEXT,
                event_type TEXT NOT NULL,
                occurred_at_utc TIMESTAMPTZ NOT NULL,
                pipeline_run_id TEXT NOT NULL,
                PRIMARY KEY (ticket_id, pipeline_run_id)
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS silver.promotions (
                promotion_id TEXT NOT NULL,
                promotion_code TEXT NOT NULL,
                promotion_type TEXT NOT NULL,
                discount_rate NUMERIC(14, 4) NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                pipeline_run_id TEXT NOT NULL,
                PRIMARY KEY (promotion_id, pipeline_run_id)
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS silver.order_promotions (
                order_id TEXT NOT NULL,
                promotion_id TEXT NOT NULL,
                discount_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
                pipeline_run_id TEXT NOT NULL,
                PRIMARY KEY (order_id, promotion_id, pipeline_run_id)
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS silver.web_events (
                event_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                session_id TEXT,
                customer_id TEXT,
                order_id TEXT,
                channel TEXT,
                campaign_id TEXT,
                occurred_at_utc TIMESTAMPTZ NOT NULL,
                pipeline_run_id TEXT NOT NULL,
                PRIMARY KEY (event_id, pipeline_run_id)
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS silver.products (
                product_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                product_name TEXT NOT NULL,
                unit_price NUMERIC(14, 2) NOT NULL,
                pipeline_run_id TEXT NOT NULL,
                PRIMARY KEY (product_id, pipeline_run_id)
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS silver.customers (
                customer_id TEXT NOT NULL,
                customer_segment TEXT,
                city_id TEXT,
                created_at_utc TIMESTAMPTZ NOT NULL,
                pipeline_run_id TEXT NOT NULL,
                PRIMARY KEY (customer_id, pipeline_run_id)
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS silver.customer_profiles (
                customer_id TEXT NOT NULL,
                customer_segment TEXT,
                city_id TEXT,
                valid_from_utc TIMESTAMPTZ NOT NULL,
                valid_to_utc TIMESTAMPTZ NOT NULL,
                pipeline_run_id TEXT NOT NULL,
                PRIMARY KEY (customer_id, valid_from_utc, pipeline_run_id)
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS silver.product_categories (
                product_id TEXT NOT NULL,
                category_id TEXT NOT NULL,
                category_name TEXT NOT NULL,
                valid_from_utc TIMESTAMPTZ NOT NULL,
                valid_to_utc TIMESTAMPTZ NOT NULL,
                pipeline_run_id TEXT NOT NULL,
                PRIMARY KEY (product_id, valid_from_utc, pipeline_run_id)
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS silver.inventory_snapshots (
                product_id TEXT NOT NULL,
                location_id TEXT NOT NULL,
                snapshot_date DATE NOT NULL,
                available_quantity INTEGER NOT NULL,
                reserved_quantity INTEGER NOT NULL,
                unit_cost NUMERIC(14, 2),
                pipeline_run_id TEXT NOT NULL,
                PRIMARY KEY (product_id, location_id, snapshot_date, pipeline_run_id)
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS silver.campaign_spend (
                spend_date DATE NOT NULL,
                campaign_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                spend_amount NUMERIC(14, 2) NOT NULL,
                pipeline_run_id TEXT NOT NULL,
                PRIMARY KEY (spend_date, campaign_id, channel, pipeline_run_id)
            );
            """
        )

        # 1. Reject Order Items dengan Quantity Negatif atau Nol
        conn.execute(
            """
            INSERT INTO silver.rejected_records 
            (pipeline_run_id, source_table, record_identifier, reject_reason, payload)
            SELECT 
                %s,
                'order_items',
                payload->>'order_item_id',
                'INVALID_QUANTITY_NEGATIVE_OR_ZERO',
                payload
            FROM bronze.raw_records
            WHERE pipeline_run_id = %s 
              AND file_name = 'order_items.json'
              AND (payload->>'quantity')::INT <= 0
            """,
            (run_id, run_id),
        )

        # 2. Masukkan Order Items yang Valid ke Clean Table (Deduplikasi per order_item_id)
        conn.execute(
            """
            WITH ranked_items AS (
                SELECT 
                    payload->>'order_item_id' AS order_item_id,
                    payload->>'order_id' AS order_id,
                    payload->>'product_id' AS product_id,
                    (payload->>'quantity')::INT AS quantity,
                    (payload->>'unit_price')::NUMERIC(14, 2) AS unit_price,
                    COALESCE((payload->>'item_discount_amount')::NUMERIC(14, 2), 0.0) AS item_discount_amount,
                    ROW_NUMBER() OVER (
                        PARTITION BY payload->>'order_item_id'
                        ORDER BY payload->>'source_row_id' DESC
                    ) AS rn
                FROM bronze.raw_records
                WHERE pipeline_run_id = %s 
                  AND file_name = 'order_items.json'
                  AND (payload->>'quantity')::INT > 0
            )
            INSERT INTO silver.order_items
            (order_item_id, order_id, product_id, quantity, unit_price, item_discount_amount, pipeline_run_id)
            SELECT 
                order_item_id, order_id, product_id, quantity, unit_price, item_discount_amount, %s
            FROM ranked_items
            WHERE rn = 1
            ON CONFLICT (order_item_id, pipeline_run_id) DO NOTHING
            """,
            (run_id, run_id),
        )

        # 3. Deduplikasi dan Validasi Orders (Ambil versi order paling mutakhir via updated_at_utc DESC)
        conn.execute(
            """
            WITH ranked_orders AS (
                SELECT 
                    payload->>'order_id' AS order_id,
                    payload->>'customer_id' AS customer_id,
                    (payload->>'ordered_at_utc')::TIMESTAMPTZ AS ordered_at_utc,
                    payload->>'sales_channel' AS sales_channel,
                    payload->>'status' AS order_status,
                    COALESCE((payload->>'shipping_revenue')::NUMERIC(14, 2), 0) AS shipping_revenue,
                    payload->>'store_id' AS store_id,
                    (payload->>'updated_at_utc')::TIMESTAMPTZ AS updated_at_utc,
                    ROW_NUMBER() OVER (
                        PARTITION BY payload->>'order_id' 
                        ORDER BY (payload->>'updated_at_utc')::TIMESTAMPTZ DESC
                    ) AS rn
                FROM bronze.raw_records
                WHERE pipeline_run_id = %s AND file_name = 'orders.json'
            )
            INSERT INTO silver.orders
            (order_id, customer_id, ordered_at_utc, sales_channel, order_status, shipping_revenue, store_id, updated_at_utc, pipeline_run_id)
            SELECT 
                order_id, customer_id, ordered_at_utc, sales_channel, order_status, shipping_revenue, store_id, updated_at_utc, %s
            FROM ranked_orders
            WHERE rn = 1
            ON CONFLICT (order_id, pipeline_run_id) DO NOTHING
            """,
            (run_id, run_id),
        )

        # 4. Ingest Payments (Event Resolution & Deduplication ke Aggregated State)
        conn.execute(
            """
            WITH dedup_payment_events AS (
                SELECT 
                    payload->'payload'->>'payment_id' AS payment_id,
                    payload->'payload'->>'order_id' AS order_id,
                    (payload->'payload'->>'amount')::NUMERIC(14, 2) AS amount,
                    payload->>'event_type' AS event_type,
                    (payload->>'occurred_at_utc')::TIMESTAMPTZ AS occurred_at_utc,
                    ROW_NUMBER() OVER (
                        PARTITION BY payload->>'event_id'
                        ORDER BY (payload->>'occurred_at_utc')::TIMESTAMPTZ DESC
                    ) AS rn
                FROM bronze.raw_records
                WHERE pipeline_run_id = %s 
                  AND file_name = 'payment_events.json'
                  AND payload->>'event_type' = 'PAYMENT_CAPTURED'
            ),
            agg_payments AS (
                SELECT
                    payment_id,
                    order_id,
                    SUM(amount) AS captured_amount,
                    'PAYMENT_CAPTURED' AS payment_status,
                    MAX(occurred_at_utc) AS occurred_at_utc
                FROM dedup_payment_events
                WHERE rn = 1
                GROUP BY payment_id, order_id
            )
            INSERT INTO silver.payments
            (payment_id, order_id, captured_amount, payment_status, occurred_at_utc, pipeline_run_id)
            SELECT payment_id, order_id, captured_amount, payment_status, occurred_at_utc, %s
            FROM agg_payments
            ON CONFLICT (payment_id, pipeline_run_id) DO NOTHING
            """,
            (run_id, run_id),
        )

        # 5. Ingest Refunds (Deduplikasi per refund_id, ambil REFUND_COMPLETED)
        conn.execute(
            """
            WITH ranked_refunds AS (
                SELECT 
                    payload->'payload'->>'refund_id' AS refund_id,
                    payload->'payload'->>'order_id' AS order_id,
                    (payload->'payload'->>'amount')::NUMERIC(14, 2) AS refund_amount,
                    payload->>'event_type' AS refund_status,
                    (payload->>'occurred_at_utc')::TIMESTAMPTZ AS occurred_at_utc,
                    ROW_NUMBER() OVER (
                        PARTITION BY payload->'payload'->>'refund_id'
                        ORDER BY 
                            CASE WHEN payload->>'event_type' = 'REFUND_COMPLETED' THEN 1 ELSE 2 END,
                            (payload->>'occurred_at_utc')::TIMESTAMPTZ DESC
                    ) AS rn
                FROM bronze.raw_records
                WHERE pipeline_run_id = %s 
                  AND file_name = 'refund_events.json'
            )
            INSERT INTO silver.refunds
            (refund_id, order_id, refund_amount, refund_status, occurred_at_utc, pipeline_run_id)
            SELECT refund_id, order_id, refund_amount, refund_status, occurred_at_utc, %s
            FROM ranked_refunds
            WHERE rn = 1
            ON CONFLICT (refund_id, pipeline_run_id) DO NOTHING
            """,
            (run_id, run_id),
        )

        # 6. Ingest Returns (Deduplikasi per return_id, ambil versi paling mutakhir)
        conn.execute(
            """
            WITH ranked_returns AS (
                SELECT 
                    payload->'payload'->>'return_id' AS return_id,
                    payload->'payload'->>'order_id' AS order_id,
                    payload->>'event_type' AS return_status,
                    (payload->>'occurred_at_utc')::TIMESTAMPTZ AS occurred_at_utc,
                    ROW_NUMBER() OVER (
                        PARTITION BY payload->'payload'->>'return_id'
                        ORDER BY (payload->>'occurred_at_utc')::TIMESTAMPTZ DESC
                    ) AS rn
                FROM bronze.raw_records
                WHERE pipeline_run_id = %s 
                  AND file_name = 'return_events.json'
            )
            INSERT INTO silver.returns
            (return_id, order_id, return_status, occurred_at_utc, pipeline_run_id)
            SELECT return_id, order_id, return_status, occurred_at_utc, %s
            FROM ranked_returns
            WHERE rn = 1
            ON CONFLICT (return_id, pipeline_run_id) DO NOTHING
            """,
            (run_id, run_id),
        )

        # 7. Ingest Support Tickets
        conn.execute(
            """
            WITH ranked_support AS (
                SELECT 
                    payload->'payload'->>'ticket_id' AS ticket_id,
                    payload->'payload'->>'customer_id' AS customer_id,
                    payload->'payload'->>'order_id' AS order_id,
                    payload->'payload'->>'reason' AS reason,
                    payload->>'event_type' AS event_type,
                    (payload->>'occurred_at_utc')::TIMESTAMPTZ AS occurred_at_utc,
                    ROW_NUMBER() OVER (
                        PARTITION BY payload->'payload'->>'ticket_id'
                        ORDER BY (payload->>'occurred_at_utc')::TIMESTAMPTZ DESC
                    ) AS rn
                FROM bronze.raw_records
                WHERE pipeline_run_id = %s 
                  AND file_name = 'support_events.json'
            )
            INSERT INTO silver.support_tickets
            (ticket_id, customer_id, order_id, reason, event_type, occurred_at_utc, pipeline_run_id)
            SELECT ticket_id, customer_id, order_id, reason, event_type, occurred_at_utc, %s
            FROM ranked_support
            WHERE rn = 1
            ON CONFLICT (ticket_id, pipeline_run_id) DO NOTHING
            """,
            (run_id, run_id),
        )

        # 8. Ingest Web Events
        conn.execute(
            """
            WITH ranked_web_events AS (
                SELECT 
                    payload->>'event_id' AS event_id,
                    payload->>'event_type' AS event_type,
                    payload->'payload'->>'session_id' AS session_id,
                    payload->'payload'->>'customer_id' AS customer_id,
                    payload->'payload'->>'order_id' AS order_id,
                    payload->'payload'->>'channel' AS channel,
                    payload->'payload'->>'campaign_id' AS campaign_id,
                    (payload->>'occurred_at_utc')::TIMESTAMPTZ AS occurred_at_utc,
                    ROW_NUMBER() OVER (
                        PARTITION BY payload->>'event_id'
                        ORDER BY (payload->>'occurred_at_utc')::TIMESTAMPTZ DESC
                    ) AS rn
                FROM bronze.raw_records
                WHERE pipeline_run_id = %s 
                  AND file_name = 'web_events.json'
            )
            INSERT INTO silver.web_events
            (event_id, event_type, session_id, customer_id, order_id, channel, campaign_id, occurred_at_utc, pipeline_run_id)
            SELECT event_id, event_type, session_id, customer_id, order_id, channel, campaign_id, occurred_at_utc, %s
            FROM ranked_web_events
            WHERE rn = 1
            ON CONFLICT (event_id, pipeline_run_id) DO NOTHING
            """,
            (run_id, run_id),
        )

        # 9. Ingest Promotions
        conn.execute(
            """
            WITH ranked_promotions AS (
                SELECT 
                    payload->>'promotion_id' AS promotion_id,
                    payload->>'promotion_code' AS promotion_code,
                    payload->>'promotion_type' AS promotion_type,
                    (payload->>'discount_rate')::NUMERIC(14, 4) AS discount_rate,
                    (payload->>'start_date')::DATE AS start_date,
                    (payload->>'end_date')::DATE AS end_date,
                    ROW_NUMBER() OVER (
                        PARTITION BY payload->>'promotion_id'
                        ORDER BY payload->>'source_row_id' DESC
                    ) AS rn
                FROM bronze.raw_records
                WHERE pipeline_run_id = %s AND file_name = 'promotions.json'
            )
            INSERT INTO silver.promotions
            (promotion_id, promotion_code, promotion_type, discount_rate, start_date, end_date, pipeline_run_id)
            SELECT promotion_id, promotion_code, promotion_type, discount_rate, start_date, end_date, %s
            FROM ranked_promotions
            WHERE rn = 1
            ON CONFLICT (promotion_id, pipeline_run_id) DO NOTHING
            """,
            (run_id, run_id),
        )

        # 10. Ingest Order Promotions
        conn.execute(
            """
            WITH ranked_order_promotions AS (
                SELECT 
                    payload->>'order_id' AS order_id,
                    payload->>'promotion_id' AS promotion_id,
                    COALESCE((payload->>'discount_amount')::NUMERIC(14, 2), 0.0) AS discount_amount,
                    ROW_NUMBER() OVER (
                        PARTITION BY payload->>'order_id', payload->>'promotion_id'
                        ORDER BY payload->>'source_row_id' DESC
                    ) AS rn
                FROM bronze.raw_records
                WHERE pipeline_run_id = %s AND file_name = 'order_promotions.json'
            )
            INSERT INTO silver.order_promotions
            (order_id, promotion_id, discount_amount, pipeline_run_id)
            SELECT order_id, promotion_id, discount_amount, %s
            FROM ranked_order_promotions
            WHERE rn = 1
            ON CONFLICT (order_id, promotion_id, pipeline_run_id) DO NOTHING
            """,
            (run_id, run_id),
        )

        # 11. Ingest Products
        conn.execute(
            """
            WITH ranked_products AS (
                SELECT 
                    payload->>'product_id' AS product_id,
                    payload->>'sku' AS sku,
                    payload->>'product_name' AS product_name,
                    (payload->>'unit_price')::NUMERIC(14, 2) AS unit_price,
                    ROW_NUMBER() OVER (
                        PARTITION BY payload->>'product_id'
                        ORDER BY payload->>'source_row_id' DESC
                    ) AS rn
                FROM bronze.raw_records
                WHERE pipeline_run_id = %s AND file_name = 'products.json'
            )
            INSERT INTO silver.products
            (product_id, sku, product_name, unit_price, pipeline_run_id)
            SELECT product_id, sku, product_name, unit_price, %s
            FROM ranked_products
            WHERE rn = 1
            ON CONFLICT (product_id, pipeline_run_id) DO NOTHING
            """,
            (run_id, run_id),
        )

        # 12. Ingest Customers
        conn.execute(
            """
            WITH ranked_customers AS (
                SELECT 
                    payload->>'customer_id' AS customer_id,
                    payload->>'customer_segment' AS customer_segment,
                    payload->>'city_id' AS city_id,
                    (payload->>'created_at_utc')::TIMESTAMPTZ AS created_at_utc,
                    ROW_NUMBER() OVER (
                        PARTITION BY payload->>'customer_id'
                        ORDER BY (payload->>'created_at_utc')::TIMESTAMPTZ DESC
                    ) AS rn
                FROM bronze.raw_records
                WHERE pipeline_run_id = %s AND file_name = 'customers.json'
            )
            INSERT INTO silver.customers
            (customer_id, customer_segment, city_id, created_at_utc, pipeline_run_id)
            SELECT customer_id, customer_segment, city_id, created_at_utc, %s
            FROM ranked_customers
            WHERE rn = 1
            ON CONFLICT (customer_id, pipeline_run_id) DO NOTHING
            """,
            (run_id, run_id),
        )

        # 13. Ingest Customer Profiles
        conn.execute(
            """
            INSERT INTO silver.customer_profiles
            (customer_id, customer_segment, city_id, valid_from_utc, valid_to_utc, pipeline_run_id)
            SELECT 
                payload->>'customer_id',
                payload->>'customer_segment',
                payload->>'city_id',
                (payload->>'valid_from_utc')::TIMESTAMPTZ,
                (payload->>'valid_to_utc')::TIMESTAMPTZ,
                %s
            FROM bronze.raw_records
            WHERE pipeline_run_id = %s AND file_name = 'customer_profiles.json'
            ON CONFLICT (customer_id, valid_from_utc, pipeline_run_id) DO NOTHING
            """,
            (run_id, run_id),
        )

        # 14. Ingest Product Categories
        conn.execute(
            """
            INSERT INTO silver.product_categories
            (product_id, category_id, category_name, valid_from_utc, valid_to_utc, pipeline_run_id)
            SELECT 
                payload->>'product_id',
                payload->>'category_id',
                payload->>'category_name',
                (payload->>'valid_from_utc')::TIMESTAMPTZ,
                (payload->>'valid_to_utc')::TIMESTAMPTZ,
                %s
            FROM bronze.raw_records
            WHERE pipeline_run_id = %s AND file_name = 'product_categories.json'
            ON CONFLICT (product_id, valid_from_utc, pipeline_run_id) DO NOTHING
            """,
            (run_id, run_id),
        )

        # 15. Ingest Inventory Snapshots
        conn.execute(
            """
            INSERT INTO silver.inventory_snapshots
            (product_id, location_id, snapshot_date, available_quantity, reserved_quantity, unit_cost, pipeline_run_id)
            SELECT 
                payload->>'product_id',
                payload->>'location_id',
                (payload->>'snapshot_date')::DATE,
                (payload->>'available_quantity')::INT,
                (payload->>'reserved_quantity')::INT,
                (payload->>'unit_cost')::NUMERIC(14, 2),
                %s
            FROM bronze.raw_records
            WHERE pipeline_run_id = %s AND file_name = 'inventory_snapshots.csv'
            ON CONFLICT (product_id, location_id, snapshot_date, pipeline_run_id) DO NOTHING
            """,
            (run_id, run_id),
        )

        # 16. Ingest Campaign Spend
        conn.execute(
            """
            INSERT INTO silver.campaign_spend
            (spend_date, campaign_id, channel, spend_amount, pipeline_run_id)
            SELECT 
                (payload->>'spend_date')::DATE,
                payload->>'campaign_id',
                payload->>'channel',
                (payload->>'spend_amount')::NUMERIC(14, 2),
                %s
            FROM bronze.raw_records
            WHERE pipeline_run_id = %s AND file_name = 'campaign_spend.csv'
            ON CONFLICT (spend_date, campaign_id, channel, pipeline_run_id) DO NOTHING
            """,
            (run_id, run_id),
        )

        # Hitung statistik clean dan reject untuk run ini
        clean_count = conn.execute(
            """
            SELECT (
                (SELECT COUNT(*) FROM silver.orders WHERE pipeline_run_id = %s) +
                (SELECT COUNT(*) FROM silver.order_items WHERE pipeline_run_id = %s) +
                (SELECT COUNT(*) FROM silver.payments WHERE pipeline_run_id = %s) +
                (SELECT COUNT(*) FROM silver.refunds WHERE pipeline_run_id = %s) +
                (SELECT COUNT(*) FROM silver.returns WHERE pipeline_run_id = %s) +
                (SELECT COUNT(*) FROM silver.support_tickets WHERE pipeline_run_id = %s) +
                (SELECT COUNT(*) FROM silver.web_events WHERE pipeline_run_id = %s) +
                (SELECT COUNT(*) FROM silver.promotions WHERE pipeline_run_id = %s) +
                (SELECT COUNT(*) FROM silver.order_promotions WHERE pipeline_run_id = %s) +
                (SELECT COUNT(*) FROM silver.products WHERE pipeline_run_id = %s) +
                (SELECT COUNT(*) FROM silver.customers WHERE pipeline_run_id = %s) +
                (SELECT COUNT(*) FROM silver.customer_profiles WHERE pipeline_run_id = %s) +
                (SELECT COUNT(*) FROM silver.product_categories WHERE pipeline_run_id = %s) +
                (SELECT COUNT(*) FROM silver.inventory_snapshots WHERE pipeline_run_id = %s) +
                (SELECT COUNT(*) FROM silver.campaign_spend WHERE pipeline_run_id = %s)
            )
            """,
            (run_id,) * 15,
        ).fetchone()[0]

        reject_count = conn.execute(
            "SELECT COUNT(*) FROM silver.rejected_records WHERE pipeline_run_id = %s",
            (run_id,),
        ).fetchone()[0]

        clean_orders = conn.execute(
            "SELECT COUNT(*) FROM silver.orders WHERE pipeline_run_id = %s",
            (run_id,),
        ).fetchone()[0]

        # Update metadata ke ops.pipeline_runs
        conn.execute(
            """
            UPDATE ops.pipeline_runs
            SET records_clean = %s,
                records_rejected = %s,
                current_stage = 'silver'
            WHERE run_id = %s
            """,
            (clean_count, reject_count, run_id),
        )
        conn.commit()

    print(
        f"[{run_id}] Silver selesai: {clean_count} records clean ({clean_orders} orders), {reject_count} record rejected."
    )
    return {
        "clean_count": int(clean_count),
        "clean_orders": int(clean_orders),
        "reject_count": int(reject_count),
        "rejected_records": int(reject_count),
    }


if __name__ == "__main__":
    import sys

    target_run_id = sys.argv[1] if len(sys.argv) > 1 else "manual-run"
    build_silver(target_run_id)
