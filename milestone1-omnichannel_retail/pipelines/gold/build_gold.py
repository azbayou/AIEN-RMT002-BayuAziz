"""Membangun 5 tabel Gold analitik tanpa fact multiplication."""

from datetime import UTC, datetime

from shared.db import connect


def build_gold(run_id: str, target: str = "local") -> None:
    print(f"[{run_id}] Memulai pembangunan Gold Layer...")

    with connect(target) as conn:
        # 1. Bangun gold.order_360
        conn.execute(
            """
            WITH item_agg AS (
                SELECT 
                    order_id,
                    SUM(quantity * unit_price) AS gmv,
                    SUM(item_discount_amount) AS total_discount,
                    COUNT(*) AS item_count,
                    SUM(quantity) AS total_units
                FROM silver.order_items
                WHERE pipeline_run_id = %s
                GROUP BY order_id
            ),
            pay_agg AS (
                SELECT 
                    order_id,
                    SUM(captured_amount) AS total_captured
                FROM silver.payments
                WHERE pipeline_run_id = %s
                GROUP BY order_id
            ),
            ref_agg AS (
                SELECT 
                    order_id,
                    SUM(refund_amount) AS total_refunded
                FROM silver.refunds
                WHERE pipeline_run_id = %s
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
                    FROM silver.returns
                    WHERE pipeline_run_id = %s
                ) r_sub
                WHERE rn = 1
            ),
            promo_agg AS (
                SELECT 
                    order_id,
                    COUNT(DISTINCT promotion_id) AS promotion_count
                FROM silver.order_promotions
                WHERE pipeline_run_id = %s
                GROUP BY order_id
            ),
            customer_first_orders AS (
                SELECT 
                    order_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY customer_id 
                        ORDER BY ordered_at_utc ASC, order_id ASC
                    ) = 1 AS is_first_order
                FROM silver.orders
                WHERE pipeline_run_id = %s
            )
            INSERT INTO gold.order_360
            (order_id, customer_id, order_date, sales_channel, store_id,
             gross_merchandise_value, discount_amount, shipping_revenue,
             captured_payment_amount, refunded_amount, net_revenue,
             item_count, unit_quantity, order_status, payment_status,
             return_status, promotion_count, first_order_flag, pipeline_run_id)
            SELECT 
                o.order_id,
                o.customer_id,
                o.ordered_at_utc::DATE AS order_date,
                o.sales_channel,
                o.store_id,
                COALESCE(i.gmv, 0),
                COALESCE(i.total_discount, 0),
                COALESCE(o.shipping_revenue, 0),
                COALESCE(p.total_captured, 0),
                COALESCE(r.total_refunded, 0),
                (COALESCE(i.gmv, 0) - COALESCE(i.total_discount, 0) + COALESCE(o.shipping_revenue, 0) - COALESCE(r.total_refunded, 0)) AS net_revenue,
                COALESCE(i.item_count, 0),
                COALESCE(i.total_units, 0),
                o.order_status,
                CASE WHEN COALESCE(p.total_captured, 0) > 0 THEN 'CAPTURED' ELSE 'PENDING' END,
                COALESCE(ret.return_status, 'NONE'),
                COALESCE(pr.promotion_count, 0),
                COALESCE(fo.is_first_order, false),
                %s
            FROM silver.orders o
            LEFT JOIN item_agg i ON o.order_id = i.order_id
            LEFT JOIN pay_agg p ON o.order_id = p.order_id
            LEFT JOIN ref_agg r ON o.order_id = r.order_id
            LEFT JOIN latest_returns ret ON o.order_id = ret.order_id
            LEFT JOIN promo_agg pr ON o.order_id = pr.order_id
            LEFT JOIN customer_first_orders fo ON o.order_id = fo.order_id
            WHERE o.pipeline_run_id = %s
            ON CONFLICT (order_id) DO UPDATE SET
                customer_id = EXCLUDED.customer_id,
                order_date = EXCLUDED.order_date,
                sales_channel = EXCLUDED.sales_channel,
                store_id = EXCLUDED.store_id,
                gross_merchandise_value = EXCLUDED.gross_merchandise_value,
                discount_amount = EXCLUDED.discount_amount,
                shipping_revenue = EXCLUDED.shipping_revenue,
                captured_payment_amount = EXCLUDED.captured_payment_amount,
                refunded_amount = EXCLUDED.refunded_amount,
                net_revenue = EXCLUDED.net_revenue,
                item_count = EXCLUDED.item_count,
                unit_quantity = EXCLUDED.unit_quantity,
                order_status = EXCLUDED.order_status,
                payment_status = EXCLUDED.payment_status,
                return_status = EXCLUDED.return_status,
                promotion_count = EXCLUDED.promotion_count,
                first_order_flag = EXCLUDED.first_order_flag,
                pipeline_run_id = EXCLUDED.pipeline_run_id
            """,
            (run_id, run_id, run_id, run_id, run_id, run_id, run_id, run_id)
        )

        # 2. Bangun gold.customer_daily
        conn.execute(
            """
            WITH order_returns AS (
                SELECT 
                    order_id,
                    COUNT(DISTINCT return_id) AS return_count
                FROM silver.returns
                WHERE pipeline_run_id = %s
                GROUP BY order_id
            ),
            order_support AS (
                SELECT 
                    order_id,
                    COUNT(DISTINCT ticket_id) AS support_contacts
                FROM silver.support_tickets
                WHERE pipeline_run_id = %s
                GROUP BY order_id
            )
            INSERT INTO gold.customer_daily
            (customer_id, metric_date, order_count, unit_quantity, gross_revenue,
             net_revenue, refund_amount, return_count, support_contacts,
             active_channel, new_customer_flag, repeat_customer_flag, pipeline_run_id)
            SELECT 
                o.customer_id,
                o.order_date AS metric_date,
                COUNT(o.order_id) AS order_count,
                SUM(o.unit_quantity) AS unit_quantity,
                SUM(o.gross_merchandise_value) AS gross_revenue,
                SUM(o.net_revenue) AS net_revenue,
                SUM(o.refunded_amount) AS refund_amount,
                SUM(COALESCE(r.return_count, CASE WHEN o.return_status != 'NONE' THEN 1 ELSE 0 END)) AS return_count,
                SUM(COALESCE(st.support_contacts, 0)) AS support_contacts,
                MAX(o.sales_channel) AS active_channel,
                BOOL_OR(o.first_order_flag) AS new_customer_flag,
                NOT BOOL_OR(o.first_order_flag) AS repeat_customer_flag,
                %s
            FROM gold.order_360 o
            LEFT JOIN order_returns r ON o.order_id = r.order_id
            LEFT JOIN order_support st ON o.order_id = st.order_id
            WHERE o.pipeline_run_id = %s
            GROUP BY o.customer_id, o.order_date
            ON CONFLICT (customer_id, metric_date) DO UPDATE SET
                order_count = EXCLUDED.order_count,
                unit_quantity = EXCLUDED.unit_quantity,
                gross_revenue = EXCLUDED.gross_revenue,
                net_revenue = EXCLUDED.net_revenue,
                refund_amount = EXCLUDED.refund_amount,
                return_count = EXCLUDED.return_count,
                support_contacts = EXCLUDED.support_contacts,
                active_channel = EXCLUDED.active_channel,
                new_customer_flag = EXCLUDED.new_customer_flag,
                repeat_customer_flag = EXCLUDED.repeat_customer_flag,
                pipeline_run_id = EXCLUDED.pipeline_run_id
            """,
            (run_id, run_id, run_id, run_id)
        )

        # 3. Bangun gold.product_daily
        conn.execute(
            """
            WITH prod_sales AS (
                SELECT 
                    oi.product_id,
                    o.ordered_at_utc::DATE AS metric_date,
                    SUM(oi.quantity) AS units_sold,
                    COUNT(DISTINCT oi.order_id) AS order_count,
                    SUM(oi.quantity * oi.unit_price) AS gross_revenue,
                    SUM(oi.quantity * oi.unit_price - oi.item_discount_amount) AS net_revenue
                FROM silver.order_items oi
                JOIN silver.orders o ON oi.order_id = o.order_id AND oi.pipeline_run_id = o.pipeline_run_id
                WHERE oi.pipeline_run_id = %s
                GROUP BY oi.product_id, o.ordered_at_utc::DATE
            ),
            inventory_agg AS (
                SELECT 
                    product_id,
                    snapshot_date AS metric_date,
                    SUM(available_quantity) AS available_inv,
                    SUM(reserved_quantity) AS reserved_inv
                FROM silver.inventory_snapshots
                WHERE pipeline_run_id = %s
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
                    o.ordered_at_utc::DATE AS metric_date,
                    SUM(oi.quantity) AS refunded_units
                FROM silver.order_items oi
                JOIN silver.orders o ON oi.order_id = o.order_id AND oi.pipeline_run_id = o.pipeline_run_id
                JOIN (
                    SELECT DISTINCT order_id 
                    FROM silver.refunds 
                    WHERE pipeline_run_id = %s
                      AND (refund_status = 'REFUND_COMPLETED' OR refund_status IS NULL)
                ) r ON oi.order_id = r.order_id
                WHERE oi.pipeline_run_id = %s
                GROUP BY oi.product_id, o.ordered_at_utc::DATE
            ),
            prod_promos AS (
                SELECT 
                    oi.product_id,
                    o.ordered_at_utc::DATE AS metric_date,
                    COUNT(DISTINCT op.promotion_id) AS promotion_count
                FROM silver.order_items oi
                JOIN silver.orders o ON oi.order_id = o.order_id AND oi.pipeline_run_id = o.pipeline_run_id
                JOIN silver.order_promotions op ON oi.order_id = op.order_id AND oi.pipeline_run_id = op.pipeline_run_id
                WHERE oi.pipeline_run_id = %s
                GROUP BY oi.product_id, o.ordered_at_utc::DATE
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
                    JOIN silver.product_categories pc 
                      ON d.product_id = pc.product_id 
                     AND pc.pipeline_run_id = %s
                     AND d.metric_date BETWEEN pc.valid_from_utc::DATE AND COALESCE(pc.valid_to_utc::DATE, '9999-12-31'::DATE)
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
                    FROM silver.product_categories
                    WHERE pipeline_run_id = %s
                ) ranked_fcat
                WHERE rn = 1
            )
            INSERT INTO gold.product_daily
            (product_id, metric_date, active_category, units_sold, order_count,
             gross_revenue, net_revenue, refunded_units, available_inventory,
             reserved_inventory, stockout_flag, promotion_count, pipeline_run_id)
            SELECT 
                d.product_id,
                d.metric_date,
                COALESCE(ac.category_name, fc.category_name, 'general') AS active_category,
                COALESCE(p.units_sold, 0),
                COALESCE(p.order_count, 0),
                COALESCE(p.gross_revenue, 0),
                COALESCE(p.net_revenue, 0),
                COALESCE(pr.refunded_units, 0),
                COALESCE(inv.available_inv, 0),
                COALESCE(inv.reserved_inv, 0),
                CASE WHEN COALESCE(inv.available_inv, 0) <= 0 THEN true ELSE false END AS stockout_flag,
                COALESCE(pp.promotion_count, 0),
                %s
            FROM all_product_days d
            LEFT JOIN prod_sales p ON d.product_id = p.product_id AND d.metric_date = p.metric_date
            LEFT JOIN inventory_agg inv ON d.product_id = inv.product_id AND d.metric_date = inv.metric_date
            LEFT JOIN prod_refunds pr ON d.product_id = pr.product_id AND d.metric_date = pr.metric_date
            LEFT JOIN prod_promos pp ON d.product_id = pp.product_id AND d.metric_date = pp.metric_date
            LEFT JOIN active_categories ac ON d.product_id = ac.product_id AND d.metric_date = ac.metric_date
            LEFT JOIN fallback_categories fc ON d.product_id = fc.product_id
            ON CONFLICT (product_id, metric_date) DO UPDATE SET
                active_category = EXCLUDED.active_category,
                units_sold = EXCLUDED.units_sold,
                order_count = EXCLUDED.order_count,
                gross_revenue = EXCLUDED.gross_revenue,
                net_revenue = EXCLUDED.net_revenue,
                refunded_units = EXCLUDED.refunded_units,
                available_inventory = EXCLUDED.available_inventory,
                reserved_inventory = EXCLUDED.reserved_inventory,
                stockout_flag = EXCLUDED.stockout_flag,
                promotion_count = EXCLUDED.promotion_count,
                pipeline_run_id = EXCLUDED.pipeline_run_id
            """,
            (run_id, run_id, run_id, run_id, run_id, run_id, run_id, run_id)
        )

        # 4. Bangun gold.channel_campaign_daily
        conn.execute(
            """
            WITH order_campaign_attribution AS (
                SELECT DISTINCT
                    order_id,
                    campaign_id
                FROM silver.web_events
                WHERE pipeline_run_id = %s
                  AND event_type = 'PURCHASE'
                  AND order_id IS NOT NULL
                  AND campaign_id IS NOT NULL
            ),
            attributed_orders_agg AS (
                SELECT 
                    o.order_date AS metric_date,
                    o.sales_channel,
                    attr.campaign_id,
                    COUNT(DISTINCT o.order_id) AS attributed_orders,
                    COUNT(DISTINCT o.customer_id) AS attributed_customers,
                    SUM(o.gross_merchandise_value) AS gross_revenue,
                    SUM(o.net_revenue) AS net_revenue,
                    SUM(o.refunded_amount) AS refunds
                FROM gold.order_360 o
                JOIN order_campaign_attribution attr ON o.order_id = attr.order_id
                WHERE o.pipeline_run_id = %s
                GROUP BY o.order_date, o.sales_channel, attr.campaign_id
            ),
            spend_agg AS (
                SELECT 
                    spend_date AS metric_date,
                    channel AS sales_channel,
                    campaign_id,
                    SUM(spend_amount) AS campaign_spend
                FROM silver.campaign_spend
                WHERE pipeline_run_id = %s
                GROUP BY spend_date, channel, campaign_id
            ),
            web_events_agg AS (
                SELECT 
                    occurred_at_utc::DATE AS metric_date,
                    channel AS sales_channel,
                    campaign_id,
                    COUNT(DISTINCT CASE WHEN event_type = 'PURCHASE' THEN session_id END)::NUMERIC / 
                        NULLIF(COUNT(DISTINCT session_id), 0) AS conversion_rate
                FROM silver.web_events
                WHERE pipeline_run_id = %s
                  AND campaign_id IS NOT NULL
                GROUP BY occurred_at_utc::DATE, channel, campaign_id
            ),
            campaign_keys AS (
                SELECT metric_date, sales_channel, campaign_id FROM spend_agg
                UNION
                SELECT metric_date, sales_channel, campaign_id FROM attributed_orders_agg
                UNION
                SELECT metric_date, sales_channel, campaign_id FROM web_events_agg
            )
            INSERT INTO gold.channel_campaign_daily
            (metric_date, sales_channel, campaign_id, campaign_spend,
             attributed_orders, attributed_customers, gross_revenue, net_revenue,
             refunds, roas, conversion_rate, pipeline_run_id)
            SELECT 
                k.metric_date,
                k.sales_channel,
                k.campaign_id,
                COALESCE(s.campaign_spend, 0.00) AS campaign_spend,
                COALESCE(ao.attributed_orders, 0) AS attributed_orders,
                COALESCE(ao.attributed_customers, 0) AS attributed_customers,
                COALESCE(ao.gross_revenue, 0.00) AS gross_revenue,
                COALESCE(ao.net_revenue, 0.00) AS net_revenue,
                COALESCE(ao.refunds, 0.00) AS refunds,
                ROUND(COALESCE(ao.net_revenue, 0.00) / NULLIF(s.campaign_spend, 0), 4) AS roas,
                ROUND(COALESCE(we.conversion_rate, 0.0000), 4) AS conversion_rate,
                %s
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
            ON CONFLICT (metric_date, sales_channel, campaign_id) DO UPDATE SET
                campaign_spend = EXCLUDED.campaign_spend,
                attributed_orders = EXCLUDED.attributed_orders,
                attributed_customers = EXCLUDED.attributed_customers,
                gross_revenue = EXCLUDED.gross_revenue,
                net_revenue = EXCLUDED.net_revenue,
                refunds = EXCLUDED.refunds,
                roas = EXCLUDED.roas,
                conversion_rate = EXCLUDED.conversion_rate,
                pipeline_run_id = EXCLUDED.pipeline_run_id
            """,
            (run_id, run_id, run_id, run_id, run_id)
        )

        # 5. Bangun gold.executive_kpis_daily
        conn.execute(
            """
            WITH daily_stockouts AS (
                SELECT 
                    metric_date,
                    ROUND(AVG(stockout_flag::INT), 4) AS stockout_rate
                FROM gold.product_daily
                WHERE pipeline_run_id = %s
                  AND stockout_flag IS NOT NULL
                GROUP BY metric_date
            ),
            support_orders AS (
                SELECT DISTINCT order_id
                FROM silver.support_tickets
                WHERE pipeline_run_id = %s
            )
            INSERT INTO gold.executive_kpis_daily
            (metric_date, total_orders, gross_revenue, net_revenue,
             average_order_value, refund_rate, return_rate, repeat_customer_rate,
             stockout_rate, active_customers, support_contact_rate,
             data_freshness_utc, pipeline_run_id)
            SELECT 
                o.order_date AS metric_date,
                COUNT(o.order_id) AS total_orders,
                SUM(o.gross_merchandise_value) AS gross_revenue,
                SUM(o.net_revenue) AS net_revenue,
                COALESCE(ROUND(SUM(o.gross_merchandise_value) / NULLIF(COUNT(o.order_id), 0), 2), 0.00) AS average_order_value,
                COALESCE(ROUND(COUNT(CASE WHEN o.refunded_amount > 0 THEN 1 END)::NUMERIC / 
                    NULLIF(COUNT(CASE WHEN o.captured_payment_amount > 0 THEN 1 END), 0), 4), 0.0000) AS refund_rate,
                COALESCE(ROUND(COUNT(CASE WHEN o.return_status != 'NONE' THEN 1 END)::NUMERIC / 
                    NULLIF(COUNT(o.order_id), 0), 4), 0.0000) AS return_rate,
                COALESCE(ROUND(COUNT(CASE WHEN o.first_order_flag = false THEN 1 END)::NUMERIC / 
                    NULLIF(COUNT(o.order_id), 0), 4), 0.0000) AS repeat_customer_rate,
                COALESCE(MAX(ds.stockout_rate), 0.0000) AS stockout_rate,
                COUNT(DISTINCT o.customer_id) AS active_customers,
                COALESCE(ROUND(COUNT(DISTINCT CASE WHEN supp.order_id IS NOT NULL THEN o.customer_id END)::NUMERIC / 
                    NULLIF(COUNT(DISTINCT o.customer_id), 0), 4), 0.0000) AS support_contact_rate,
                %s AS data_freshness_utc,
                %s AS pipeline_run_id
            FROM gold.order_360 o
            LEFT JOIN daily_stockouts ds ON o.order_date = ds.metric_date
            LEFT JOIN support_orders supp ON o.order_id = supp.order_id
            WHERE o.pipeline_run_id = %s
            GROUP BY o.order_date
            ON CONFLICT (metric_date) DO UPDATE SET
                total_orders = EXCLUDED.total_orders,
                gross_revenue = EXCLUDED.gross_revenue,
                net_revenue = EXCLUDED.net_revenue,
                average_order_value = EXCLUDED.average_order_value,
                refund_rate = EXCLUDED.refund_rate,
                return_rate = EXCLUDED.return_rate,
                repeat_customer_rate = EXCLUDED.repeat_customer_rate,
                stockout_rate = EXCLUDED.stockout_rate,
                active_customers = EXCLUDED.active_customers,
                support_contact_rate = EXCLUDED.support_contact_rate,
                data_freshness_utc = EXCLUDED.data_freshness_utc,
                pipeline_run_id = EXCLUDED.pipeline_run_id
            """,
            (run_id, run_id, datetime.now(UTC), run_id, run_id)
        )

        conn.commit()
    print(f"[{run_id}] Sukses membangun seluruh 5 tabel Gold analytical layer.")
