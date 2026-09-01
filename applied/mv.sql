-- StarRocks DDL dump from 192.168.1.54:9030 db=tatva_datalack
-- generated 2026-06-03T21:18:07.321Z

-- mv_ai_ar_risk
CREATE MATERIALIZED VIEW `mv_ai_ar_risk` (`tenant_id`, `customer`, `customer_name`, `total_open`, `bucket_90plus`, `bucket_61_90`, `bucket_31_60`, `max_days_overdue`)
DISTRIBUTED BY HASH(`tenant_id`, `customer`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    tenant_id,
    customer,
    ANY_VALUE(customer_name)                                        AS customer_name,
    SUM(open_amount)                                                AS total_open,
    SUM(CASE WHEN aging_bucket = '90+'   THEN open_amount ELSE 0 END) AS bucket_90plus,
    SUM(CASE WHEN aging_bucket = '61-90' THEN open_amount ELSE 0 END) AS bucket_61_90,
    SUM(CASE WHEN aging_bucket = '31-60' THEN open_amount ELSE 0 END) AS bucket_31_60,
    MAX(days_overdue)                                               AS max_days_overdue
FROM mv_fi_ar_aging
WHERE open_amount > 0
GROUP BY tenant_id, customer;;

-- mv_ai_customer_health
CREATE MATERIALIZED VIEW `mv_ai_customer_health` (`tenant_id`, `customer`, `customer_name`, `first_billing_date`, `last_billing_date`, `days_since_last_order`, `order_count_12m`, `avg_order_interval_days`, `rev_90d`, `rev_prev_90d`, `rev_12m`, `margin_12m`, `margin_pct_12m`, `rev_trend_pct`, `available_credit`, `total_exposure`, `risk_category`, `churn_alert`, `health_score`, `segment`, `reason`)
DISTRIBUTED BY HASH(`tenant_id`, `customer`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 6 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    s.tenant_id,
    s.customer,
    s.customer_name,
    s.first_billing_date,
    s.last_billing_date,
    s.days_since_last_order,
    s.order_count_12m,
    s.avg_order_interval_days,
    s.rev_90d,
    s.rev_prev_90d,
    s.rev_12m,
    s.margin_12m,
 
    CASE
        WHEN s.rev_12m > 0
        THEN s.margin_12m / s.rev_12m
        ELSE NULL
    END AS margin_pct_12m,
 
    CASE
        WHEN s.rev_prev_90d > 0
        THEN (s.rev_90d - s.rev_prev_90d) / s.rev_prev_90d
        ELSE NULL
    END AS rev_trend_pct,
 
    ce.available_credit,
    ce.total_exposure,
    ce.risk_category,
 
    CASE
        WHEN s.order_count_12m >= 4
         AND s.avg_order_interval_days IS NOT NULL
         AND s.days_since_last_order > (2.5 * s.avg_order_interval_days)
        THEN 1
        ELSE 0
    END AS churn_alert,
 
    CASE
        WHEN (
            50
            + CASE
                WHEN s.rev_prev_90d > 0
                 AND s.rev_90d >= s.rev_prev_90d THEN 20
                WHEN s.rev_prev_90d > 0
                 AND s.rev_90d < s.rev_prev_90d THEN -20
                ELSE 0
              END
            + CASE
                WHEN s.avg_order_interval_days IS NOT NULL
                 AND s.days_since_last_order <= s.avg_order_interval_days THEN 20
                WHEN s.avg_order_interval_days IS NOT NULL
                 AND s.days_since_last_order > (2.5 * s.avg_order_interval_days) THEN -30
                ELSE 0
              END
            + CASE
                WHEN s.rev_12m > 0
                 AND s.margin_12m / s.rev_12m >= 0.15 THEN 10
                WHEN s.rev_12m > 0
                 AND s.margin_12m / s.rev_12m < 0.05 THEN -15
                ELSE 0
              END
            + CASE
                WHEN ce.available_credit < 0 THEN -15
                ELSE 0
              END
        ) < 0 THEN 0
 
        WHEN (
            50
            + CASE
                WHEN s.rev_prev_90d > 0
                 AND s.rev_90d >= s.rev_prev_90d THEN 20
                WHEN s.rev_prev_90d > 0
                 AND s.rev_90d < s.rev_prev_90d THEN -20
                ELSE 0
              END
            + CASE
                WHEN s.avg_order_interval_days IS NOT NULL
                 AND s.days_since_last_order <= s.avg_order_interval_days THEN 20
                WHEN s.avg_order_interval_days IS NOT NULL
                 AND s.days_since_last_order > (2.5 * s.avg_order_interval_days) THEN -30
                ELSE 0
              END
            + CASE
                WHEN s.rev_12m > 0
                 AND s.margin_12m / s.rev_12m >= 0.15 THEN 10
                WHEN s.rev_12m > 0
                 AND s.margin_12m / s.rev_12m < 0.05 THEN -15
                ELSE 0
              END
            + CASE
                WHEN ce.available_credit < 0 THEN -15
                ELSE 0
              END
        ) > 100 THEN 100
 
        ELSE (
            50
            + CASE
                WHEN s.rev_prev_90d > 0
                 AND s.rev_90d >= s.rev_prev_90d THEN 20
                WHEN s.rev_prev_90d > 0
                 AND s.rev_90d < s.rev_prev_90d THEN -20
                ELSE 0
              END
            + CASE
                WHEN s.avg_order_interval_days IS NOT NULL
                 AND s.days_since_last_order <= s.avg_order_interval_days THEN 20
                WHEN s.avg_order_interval_days IS NOT NULL
                 AND s.days_since_last_order > (2.5 * s.avg_order_interval_days) THEN -30
                ELSE 0
              END
            + CASE
                WHEN s.rev_12m > 0
                 AND s.margin_12m / s.rev_12m >= 0.15 THEN 10
                WHEN s.rev_12m > 0
                 AND s.margin_12m / s.rev_12m < 0.05 THEN -15
                ELSE 0
              END
            + CASE
                WHEN ce.available_credit < 0 THEN -15
                ELSE 0
              END
        )
    END AS health_score,
 
    CASE
        WHEN s.order_count_12m >= 4
         AND s.avg_order_interval_days IS NOT NULL
         AND s.days_since_last_order > (2.5 * s.avg_order_interval_days)
        THEN 'AT_RISK_STOPPED'
 
        WHEN s.rev_prev_90d > 0
         AND s.rev_90d < (0.6 * s.rev_prev_90d)
        THEN 'DECLINING'
 
        WHEN s.rev_12m > 0
         AND s.margin_12m / s.rev_12m < 0.05
        THEN 'LOW_MARGIN'
 
        WHEN ce.available_credit < 0
        THEN 'CREDIT_BLOCKED'
 
        WHEN s.rev_90d >= s.rev_prev_90d
         AND s.order_count_12m >= 6
        THEN 'GROWING_LOYAL'
 
        ELSE 'STABLE'
    END AS segment,
 
    CASE
        WHEN s.order_count_12m >= 4
         AND s.avg_order_interval_days IS NOT NULL
         AND s.days_since_last_order > (2.5 * s.avg_order_interval_days)
        THEN 'No recent orders'
 
        WHEN s.rev_prev_90d > 0
         AND s.rev_90d < (0.6 * s.rev_prev_90d)
        THEN 'Revenue decline'
 
        WHEN s.rev_12m > 0
         AND s.margin_12m / s.rev_12m < 0.05
        THEN 'Low margin'
 
        WHEN ce.available_credit < 0
        THEN 'Over credit limit'
 
        ELSE NULL
    END AS reason
 
FROM mv_ai_customer_signals s
LEFT JOIN mv_sd_credit_exposure ce
    ON ce.tenant_id = s.tenant_id
   AND ce.customer = s.customer;;

-- mv_ai_customer_signals
CREATE MATERIALIZED VIEW `mv_ai_customer_signals` (`tenant_id`, `customer`, `customer_name`, `first_billing_date`, `last_billing_date`, `days_since_last_order`, `order_count_12m`, `avg_order_interval_days`, `rev_90d`, `rev_prev_90d`, `rev_12m`, `margin_12m`)
DISTRIBUTED BY HASH(`tenant_id`, `customer`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 6 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    tenant_id,
    sold_to                                                 AS customer,
    ANY_VALUE(customer_name)                                AS customer_name,
    MIN(billing_date)                                       AS first_billing_date,
    MAX(billing_date)                                       AS last_billing_date,
    DATEDIFF(CURRENT_DATE(), MAX(billing_date))             AS days_since_last_order,
    COUNT(DISTINCT CASE WHEN billing_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 365 DAY)
                        THEN billing_doc END)               AS order_count_12m,
    DATEDIFF(MAX(billing_date), MIN(billing_date))
      / NULLIF(COUNT(DISTINCT billing_date) - 1, 0)         AS avg_order_interval_days,
    SUM(CASE WHEN billing_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
             THEN net_value ELSE 0 END)                     AS rev_90d,
    SUM(CASE WHEN billing_date <  DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
              AND billing_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 180 DAY)
             THEN net_value ELSE 0 END)                     AS rev_prev_90d,
    SUM(CASE WHEN billing_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 365 DAY)
             THEN net_value ELSE 0 END)                     AS rev_12m,
    SUM(CASE WHEN billing_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 365 DAY)
             THEN margin_amount ELSE 0 END)                 AS margin_12m
FROM mv_sd_billing_flat
GROUP BY tenant_id, sold_to;;

-- mv_ai_inventory_risk
CREATE MATERIALIZED VIEW `mv_ai_inventory_risk` (`tenant_id`, `material`, `material_desc`, `plant`, `total_stock_qty`, `coverage_days`, `stock_state`)
DISTRIBUTED BY HASH(`tenant_id`, `plant`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    tenant_id,
    material,
    material_desc,
    plant,
    total_stock_qty,
    coverage_days,
    CASE
      WHEN total_stock_qty > 0 AND coverage_days IS NULL          THEN 'DEAD_STOCK'
      WHEN coverage_days IS NOT NULL AND coverage_days < 7        THEN 'STOCKOUT_IMMINENT'
      WHEN coverage_days IS NOT NULL AND coverage_days < 21       THEN 'STOCKOUT_RISK'
      WHEN coverage_days IS NOT NULL AND coverage_days > 365      THEN 'OVERSTOCK'
      ELSE 'HEALTHY'
    END                                                            AS stock_state
FROM mv_x_stock_coverage;;

-- mv_ai_production_risk
CREATE MATERIALIZED VIEW `mv_ai_production_risk` (`tenant_id`, `production_order`, `plant`, `material`, `basic_finish_date`, `order_qty`, `open_qty`, `days_late`, `yield_variance_qty`, `yield_var_pct`)
DISTRIBUTED BY HASH(`tenant_id`, `plant`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 30 MINUTE)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    o.tenant_id,
    o.production_order,
    o.plant,
    o.material,
    o.basic_finish_date,
    o.order_qty,
    o.open_qty,
    CASE WHEN o.basic_finish_date < CURRENT_DATE() AND o.open_qty > 0
         THEN DATEDIFF(CURRENT_DATE(), o.basic_finish_date) END     AS days_late,
    yv.yield_variance_qty,
    CASE WHEN o.order_qty > 0 THEN yv.yield_variance_qty / o.order_qty END AS yield_var_pct
FROM mv_pp_open_production_orders o
LEFT JOIN mv_pp_yield_variance yv
       ON yv.tenant_id = o.tenant_id AND yv.production_order = o.production_order;;

-- mv_ai_vendor_risk
CREATE MATERIALIZED VIEW `mv_ai_vendor_risk` (`tenant_id`, `vendor`, `vendor_name`, `open_items`, `overdue_items`, `overdue_value`, `max_days_late`)
DISTRIBUTED BY HASH(`tenant_id`, `vendor`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    po.tenant_id,
    po.vendor,
    ANY_VALUE(po.vendor_name)                                        AS vendor_name,
    COUNT(*)                                                         AS open_items,
    SUM(CASE WHEN po.delivery_date < CURRENT_DATE() AND po.open_qty > 0
             THEN 1 ELSE 0 END)                                      AS overdue_items,
    SUM(CASE WHEN po.delivery_date < CURRENT_DATE() AND po.open_qty > 0
             THEN po.net_value ELSE 0 END)                           AS overdue_value,
    MAX(CASE WHEN po.open_qty > 0 AND po.delivery_date < CURRENT_DATE()
             THEN DATEDIFF(CURRENT_DATE(), po.delivery_date) END)    AS max_days_late
FROM mv_mm_open_purchase_orders po
GROUP BY po.tenant_id, po.vendor;;

-- mv_co_cost_center_actuals
CREATE MATERIALIZED VIEW `mv_co_cost_center_actuals` (`tenant_id`, `controlling_area`, `company_code`, `fiscal_year`, `fiscal_period`, `posting_month`, `cost_center`, `cost_center_name`, `cost_element`, `cost_element_name`, `company_currency`, `actual_amount`, `quantity`, `quantity_unit`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `controlling_area`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    a.tenant_id,
    a.KOKRS                                    AS controlling_area,
    a.RBUKRS                                   AS company_code,
    a.GJAHR                                    AS fiscal_year,
    a.POPER                                    AS fiscal_period,
    date_trunc('month', a.BUDAT)               AS posting_month,
    a.RCNTR                                    AS cost_center,
    ct.KTEXT                                   AS cost_center_name,
    a.RACCT                                    AS cost_element,
    sk.TXT50                                   AS cost_element_name,
    a.RHCUR                                    AS company_currency,
    SUM(a.HSL)                                 AS actual_amount,
    SUM(a.MSL)                                 AS quantity,
    a.RUNIT                                    AS quantity_unit
FROM ACDOCA a
LEFT JOIN CSKT ct
     ON ct.tenant_id=a.tenant_id AND ct.KOKRS=a.KOKRS AND ct.KOSTL=a.RCNTR
    AND ct.SPRAS='E' AND ct.DATBI>=CURRENT_DATE()
LEFT JOIN SKAT sk
     ON sk.tenant_id=a.tenant_id AND sk.SAKNR=a.RACCT AND sk.SPRAS='E'
WHERE a.RLDNR='0L'
  AND a.RCNTR IS NOT NULL AND a.RCNTR <> ''
GROUP BY a.tenant_id, a.KOKRS, a.RBUKRS, a.GJAHR, a.POPER, date_trunc('month', a.BUDAT),
         a.RCNTR, ct.KTEXT, a.RACCT, sk.TXT50, a.RHCUR, a.RUNIT;;

-- mv_co_cost_element_plan_vs_actual
CREATE MATERIALIZED VIEW `mv_co_cost_element_plan_vs_actual` (`tenant_id`, `controlling_area`, `fiscal_year`, `period`, `cost_element`, `cost_element_name`, `cost_center`, `order_no`, `currency`, `plan_amount`, `actual_amount`, `variance_amount`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `controlling_area`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    act.tenant_id,
    act.controlling_area,
    act.fiscal_year,
    act.period,
    act.cost_element,
    sk.TXT50                                       AS cost_element_name,
    act.cost_center,
    act.order_no,
    act.currency,
    COALESCE(pl.plan_amount, 0)                    AS plan_amount,
    act.actual_amount,
    act.actual_amount - COALESCE(pl.plan_amount,0) AS variance_amount
FROM (
    SELECT
        a.tenant_id,
        a.KOKRS  AS controlling_area,
        a.GJAHR  AS fiscal_year,
        a.POPER  AS period,
        a.RACCT  AS cost_element,
        a.RCNTR  AS cost_center,
        a.AUFNR  AS order_no,
        a.RHCUR  AS currency,
        a.KTOPL  AS chart_of_accounts,
        SUM(a.HSL) AS actual_amount
    FROM ACDOCA a
    WHERE a.RLDNR = '0L'
      AND (COALESCE(a.RCNTR,'') <> '' OR COALESCE(a.AUFNR,'') <> '')
    GROUP BY a.tenant_id, a.KOKRS, a.GJAHR, a.POPER, a.RACCT,
             a.RCNTR, a.AUFNR, a.RHCUR, a.KTOPL
) act
LEFT JOIN (
    SELECT
        p.tenant_id,
        p.KOKRS  AS controlling_area,
        p.RYEAR  AS fiscal_year,
        p.POPER  AS period,
        p.RACCT  AS cost_element,
        p.RCNTR  AS cost_center,
        p.AUFNR  AS order_no,
        p.RHCUR  AS currency,
        SUM(p.HSL) AS plan_amount
    FROM ACDOCP p
    WHERE (COALESCE(p.RCNTR,'') <> '' OR COALESCE(p.AUFNR,'') <> '')
    GROUP BY p.tenant_id, p.KOKRS, p.RYEAR, p.POPER, p.RACCT,
             p.RCNTR, p.AUFNR, p.RHCUR
) pl
  ON  pl.tenant_id        = act.tenant_id
  AND pl.controlling_area = act.controlling_area
  AND pl.fiscal_year      = act.fiscal_year
  AND pl.period           = act.period
  AND pl.cost_element     = act.cost_element
  AND COALESCE(pl.cost_center,'') = COALESCE(act.cost_center,'')
  AND COALESCE(pl.order_no,'')    = COALESCE(act.order_no,'')
LEFT JOIN SKAT sk
  ON  sk.tenant_id = act.tenant_id
 AND sk.KTOPL      = act.chart_of_accounts
 AND sk.SAKNR      = act.cost_element
 AND sk.SPRAS      = 'E';;

-- mv_co_internal_order_actuals
CREATE MATERIALIZED VIEW `mv_co_internal_order_actuals` (`tenant_id`, `controlling_area`, `fiscal_year`, `period`, `order_no`, `order_name`, `order_type`, `cost_element`, `cost_element_category`, `value_type`, `object_currency`, `amount_co_area_currency`, `quantity`, `quantity_unit`)
DISTRIBUTED BY HASH(`tenant_id`, `controlling_area`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    a.tenant_id,
    a.KOKRS                       AS controlling_area,
    a.GJAHR                       AS fiscal_year,
    a.POPER                       AS period,
    a.AUFNR                       AS order_no,
    o.KTEXT                       AS order_name,
    o.AUART                       AS order_type,
    a.RACCT                       AS cost_element,
    cb.KATYP                      AS cost_element_category,
    '04'                          AS value_type,            -- ACDOCA actuals
    a.RHCUR                       AS object_currency,        -- local currency (see note)
    SUM(a.HSL)                    AS amount_co_area_currency,-- local-currency actuals
    SUM(a.CO_MEGBTR)              AS quantity,
    a.CO_MEINH                    AS quantity_unit
FROM ACDOCA a
LEFT JOIN AUFK o
       ON o.tenant_id = a.tenant_id
      AND o.AUFNR     = a.AUFNR
LEFT JOIN CSKB cb
       ON cb.tenant_id = a.tenant_id
      AND cb.KOKRS     = a.KOKRS
      AND cb.KSTAR     = a.RACCT
      AND cb.DATBI    >= CURRENT_DATE()          -- current-valid cost-element category
WHERE a.RLDNR = '0L'                             -- leading ledger = actuals
  AND COALESCE(a.AUFNR,'') <> ''                 -- internal-order lines only
GROUP BY
    a.tenant_id, a.KOKRS, a.GJAHR, a.POPER, a.AUFNR, o.KTEXT, o.AUART,
    a.RACCT, cb.KATYP, a.RHCUR, a.CO_MEINH;;

-- mv_co_pa_margin_by_segment
CREATE MATERIALIZED VIEW `mv_co_pa_margin_by_segment` (`tenant_id`, `company_code`, `fiscal_year`, `fiscal_period`, `posting_month`, `profit_center`, `segment`, `customer`, `material`, `plant`, `company_currency`, `contribution_amount`, `quantity`)
DISTRIBUTED BY HASH(`tenant_id`, `company_code`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 6 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    a.tenant_id,
    a.RBUKRS                                            AS company_code,
    a.GJAHR                                             AS fiscal_year,
    a.POPER                                             AS fiscal_period,
    date_trunc('month', a.BUDAT)                        AS posting_month,
    a.PRCTR                                             AS profit_center,
    a.SEGMENT                                           AS segment,
    a.KUNNR                                             AS customer,
    a.MATNR                                             AS material,
    a.WERKS                                             AS plant,
    a.RHCUR                                             AS company_currency,
    SUM(CASE WHEN a.DRCRK='H' THEN a.HSL ELSE -a.HSL END) AS contribution_amount,
    SUM(a.MSL)                                          AS quantity
FROM ACDOCA a
WHERE a.RLDNR = '0L'
  AND a.GLACCOUNT_TYPE IN ('P','S','N')
GROUP BY
    a.tenant_id, a.RBUKRS, a.GJAHR, a.POPER, date_trunc('month', a.BUDAT),
    a.PRCTR, a.SEGMENT, a.KUNNR, a.MATNR, a.WERKS, a.RHCUR;;

-- mv_co_profit_center_pl
CREATE MATERIALIZED VIEW `mv_co_profit_center_pl` (`tenant_id`, `controlling_area`, `company_code`, `fiscal_year`, `fiscal_period`, `posting_month`, `profit_center`, `profit_center_name`, `segment`, `gl_account`, `company_currency`, `revenue_amount`, `cost_amount`, `net_amount`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `controlling_area`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    a.tenant_id,
    a.KOKRS                                    AS controlling_area,
    a.RBUKRS                                   AS company_code,
    a.GJAHR                                    AS fiscal_year,
    a.POPER                                    AS fiscal_period,
    date_trunc('month', a.BUDAT)               AS posting_month,
    a.PRCTR                                    AS profit_center,
    pc.KTEXT                                   AS profit_center_name,
    a.SEGMENT                                  AS segment,
    a.RACCT                                    AS gl_account,
    a.RHCUR                                    AS company_currency,
    SUM(CASE WHEN a.DRCRK='H' THEN a.HSL ELSE 0 END)  AS revenue_amount,
    SUM(CASE WHEN a.DRCRK='S' THEN a.HSL ELSE 0 END)  AS cost_amount,
    SUM(CASE WHEN a.DRCRK='H' THEN a.HSL ELSE -a.HSL END) AS net_amount
FROM ACDOCA a
LEFT JOIN CEPCT pc
     ON pc.tenant_id=a.tenant_id AND pc.PRCTR=a.PRCTR AND pc.KOKRS=a.KOKRS
    AND pc.SPRAS='E' AND pc.DATBI>=CURRENT_DATE()
WHERE a.RLDNR='0L'
  AND a.PRCTR IS NOT NULL AND a.PRCTR <> ''
GROUP BY a.tenant_id, a.KOKRS, a.RBUKRS, a.GJAHR, a.POPER, date_trunc('month', a.BUDAT),
         a.PRCTR, pc.KTEXT, a.SEGMENT, a.RACCT, a.RHCUR;;

-- mv_fi_ap_aging
CREATE MATERIALIZED VIEW `mv_fi_ap_aging` (`tenant_id`, `company_code`, `vendor`, `vendor_name`, `accounting_doc`, `fiscal_year`, `line_no`, `reference`, `posting_date`, `baseline_date`, `payment_terms`, `net_due_date`, `days_overdue`, `open_amount`, `aging_bucket`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `company_code`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    l.tenant_id,
    l.BUKRS                                    AS company_code,
    l.LIFNR                                    AS vendor,
    lf.NAME1                                   AS vendor_name,
    l.BELNR                                    AS accounting_doc,
    l.GJAHR                                    AS fiscal_year,
    l.BUZEI                                    AS line_no,
    h.XBLNR                                    AS reference,
    h.BUDAT                                    AS posting_date,
    l.ZFBDT                                    AS baseline_date,
    l.ZTERM                                    AS payment_terms,
    DATE_ADD(l.ZFBDT, INTERVAL CAST(COALESCE(l.ZBD1T,0) AS INT) DAY) AS net_due_date,
    DATEDIFF(CURRENT_DATE(),
             DATE_ADD(l.ZFBDT, INTERVAL CAST(COALESCE(l.ZBD1T,0) AS INT) DAY)) AS days_overdue,
    CASE WHEN l.SHKZG='H' THEN l.DMBTR ELSE -l.DMBTR END AS open_amount,
    CASE
      WHEN DATEDIFF(CURRENT_DATE(), DATE_ADD(l.ZFBDT, INTERVAL CAST(COALESCE(l.ZBD1T,0) AS INT) DAY)) <= 0   THEN 'NOT_DUE'
      WHEN DATEDIFF(CURRENT_DATE(), DATE_ADD(l.ZFBDT, INTERVAL CAST(COALESCE(l.ZBD1T,0) AS INT) DAY)) <= 30  THEN '0-30'
      WHEN DATEDIFF(CURRENT_DATE(), DATE_ADD(l.ZFBDT, INTERVAL CAST(COALESCE(l.ZBD1T,0) AS INT) DAY)) <= 60  THEN '31-60'
      WHEN DATEDIFF(CURRENT_DATE(), DATE_ADD(l.ZFBDT, INTERVAL CAST(COALESCE(l.ZBD1T,0) AS INT) DAY)) <= 90  THEN '61-90'
      ELSE '90+' END                          AS aging_bucket
FROM BSEG l
JOIN BKPF h
     ON h.tenant_id=l.tenant_id AND h.BUKRS=l.BUKRS AND h.BELNR=l.BELNR AND h.GJAHR=l.GJAHR
LEFT JOIN LFA1 lf
     ON lf.tenant_id=l.tenant_id AND lf.LIFNR=l.LIFNR
WHERE l.KOART='K'
  AND (l.AUGBL IS NULL OR l.AUGBL='');;

-- mv_fi_ap_cleared
CREATE MATERIALIZED VIEW `mv_fi_ap_cleared` (`tenant_id`, `company_code`, `vendor`, `vendor_name`, `accounting_doc`, `fiscal_year`, `line_no`, `posting_date`, `clearing_doc`, `clearing_date`, `clearing_year`, `cleared_amount`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `company_code`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    l.tenant_id,
    l.BUKRS                                    AS company_code,
    l.LIFNR                                    AS vendor,
    lf.NAME1                                   AS vendor_name,
    l.BELNR                                    AS accounting_doc,
    l.GJAHR                                    AS fiscal_year,
    l.BUZEI                                    AS line_no,
    h.BUDAT                                    AS posting_date,
    l.AUGBL                                    AS clearing_doc,
    l.AUGDT                                    AS clearing_date,
    l.AUGGJ                                    AS clearing_year,
    CASE WHEN l.SHKZG='H' THEN l.DMBTR ELSE -l.DMBTR END AS cleared_amount
FROM BSEG l
JOIN BKPF h
     ON h.tenant_id=l.tenant_id AND h.BUKRS=l.BUKRS AND h.BELNR=l.BELNR AND h.GJAHR=l.GJAHR
LEFT JOIN LFA1 lf
     ON lf.tenant_id=l.tenant_id AND lf.LIFNR=l.LIFNR
WHERE l.KOART='K'
  AND l.AUGBL IS NOT NULL AND l.AUGBL <> '';;

-- mv_fi_ar_aging
CREATE MATERIALIZED VIEW `mv_fi_ar_aging` (`tenant_id`, `company_code`, `customer`, `customer_name`, `accounting_doc`, `fiscal_year`, `line_no`, `reference`, `posting_date`, `baseline_date`, `payment_terms`, `net_due_date`, `days_overdue`, `open_amount`, `aging_bucket`, `billing_doc`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `company_code`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    l.tenant_id,
    l.BUKRS                                    AS company_code,
    l.KUNNR                                    AS customer,
    kn.NAME1                                   AS customer_name,
    l.BELNR                                    AS accounting_doc,
    l.GJAHR                                    AS fiscal_year,
    l.BUZEI                                    AS line_no,
    h.XBLNR                                    AS reference,
    h.BUDAT                                    AS posting_date,
    l.ZFBDT                                    AS baseline_date,
    l.ZTERM                                    AS payment_terms,
    DATE_ADD(l.ZFBDT, INTERVAL CAST(COALESCE(l.ZBD1T,0) AS INT) DAY) AS net_due_date,
    DATEDIFF(CURRENT_DATE(),
             DATE_ADD(l.ZFBDT, INTERVAL CAST(COALESCE(l.ZBD1T,0) AS INT) DAY)) AS days_overdue,
    CASE WHEN l.SHKZG='S' THEN l.DMBTR ELSE -l.DMBTR END AS open_amount,
    CASE
      WHEN DATEDIFF(CURRENT_DATE(), DATE_ADD(l.ZFBDT, INTERVAL CAST(COALESCE(l.ZBD1T,0) AS INT) DAY)) <= 0   THEN 'NOT_DUE'
      WHEN DATEDIFF(CURRENT_DATE(), DATE_ADD(l.ZFBDT, INTERVAL CAST(COALESCE(l.ZBD1T,0) AS INT) DAY)) <= 30  THEN '0-30'
      WHEN DATEDIFF(CURRENT_DATE(), DATE_ADD(l.ZFBDT, INTERVAL CAST(COALESCE(l.ZBD1T,0) AS INT) DAY)) <= 60  THEN '31-60'
      WHEN DATEDIFF(CURRENT_DATE(), DATE_ADD(l.ZFBDT, INTERVAL CAST(COALESCE(l.ZBD1T,0) AS INT) DAY)) <= 90  THEN '61-90'
      ELSE '90+' END                          AS aging_bucket,
    COALESCE(
      NULLIF(l.VBELN, ''),
      CASE WHEN l.AWTYP = 'VBRK' THEN SUBSTRING(l.AWKEY, 1, 10) END
    )                                          AS billing_doc
FROM BSEG l
JOIN BKPF h
     ON h.tenant_id=l.tenant_id AND h.BUKRS=l.BUKRS AND h.BELNR=l.BELNR AND h.GJAHR=l.GJAHR
LEFT JOIN KNA1 kn
     ON kn.tenant_id=l.tenant_id AND kn.KUNNR=l.KUNNR
WHERE l.KOART='D'
  AND (l.AUGBL IS NULL OR l.AUGBL='');;

-- mv_fi_customer_advance
CREATE MATERIALIZED VIEW `mv_fi_customer_advance` (`tenant_id`, `company_code`, `customer`, `customer_name`, `accounting_doc`, `fiscal_year`, `line_no`, `special_gl_indicator`, `reference`, `posting_date`, `baseline_date`, `sales_document`, `advance_amount`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `company_code`) BUCKETS 16
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    l.tenant_id,
    l.BUKRS                                    AS company_code,
    l.KUNNR                                    AS customer,
    kn.NAME1                                   AS customer_name,
    l.BELNR                                    AS accounting_doc,
    l.GJAHR                                    AS fiscal_year,
    l.BUZEI                                    AS line_no,
    l.UMSKZ                                    AS special_gl_indicator,
    h.XBLNR                                    AS reference,
    h.BUDAT                                    AS posting_date,
    l.ZFBDT                                    AS baseline_date,
    l.VBEL2                                    AS sales_document,
    CASE WHEN l.SHKZG='H' THEN l.DMBTR ELSE -l.DMBTR END AS advance_amount
FROM BSEG l
JOIN BKPF h
     ON h.tenant_id=l.tenant_id AND h.BUKRS=l.BUKRS AND h.BELNR=l.BELNR AND h.GJAHR=l.GJAHR
LEFT JOIN KNA1 kn
     ON kn.tenant_id=l.tenant_id AND kn.KUNNR=l.KUNNR
WHERE l.KOART='D'
  AND l.UMSKZ='A'
  AND (l.AUGBL IS NULL OR l.AUGBL='');;

-- mv_fi_vendor_advance
CREATE MATERIALIZED VIEW `mv_fi_vendor_advance` (`tenant_id`, `company_code`, `vendor`, `vendor_name`, `accounting_doc`, `fiscal_year`, `line_no`, `special_gl_indicator`, `reference`, `posting_date`, `posting_year`, `posting_month`, `purchase_order`, `advance_amount`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `company_code`) BUCKETS 16
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    a.tenant_id,
    a.RBUKRS                                   AS company_code,
    a.LIFNR                                    AS vendor,
    lf.NAME1                                   AS vendor_name,
    a.BELNR                                    AS accounting_doc,
    a.GJAHR                                    AS fiscal_year,
    a.DOCLN                                    AS line_no,
    a.UMSKZ                                    AS special_gl_indicator,
    a.ZUONR                                    AS reference,
    a.BUDAT                                    AS posting_date,
    YEAR(a.BUDAT)                              AS posting_year,
    MONTH(a.BUDAT)                             AS posting_month,
    a.EBELN                                    AS purchase_order,
    a.HSL                                      AS advance_amount
FROM ACDOCA a
LEFT JOIN LFA1 lf
       ON lf.tenant_id = a.tenant_id AND lf.LIFNR = a.LIFNR
WHERE a.RLDNR = '0L'
  AND a.LIFNR IS NOT NULL AND a.LIFNR <> ''   -- vendor lines (KOART unreliable in ACDOCA here)
  AND a.UMSKZ = 'K'                           -- vendor down-payment special-G/L indicator in this lake
  AND a.HSL > 0                               -- advance paid out, not the clearing leg
  AND (a.AUGBL IS NULL OR a.AUGBL = '')       -- OPEN advances only; remove for all advances
  AND (a.XREVERSING IS NULL OR a.XREVERSING <> 'X');;

-- mv_fi_asset_transactions
CREATE MATERIALIZED VIEW `mv_fi_asset_transactions` (`tenant_id`, `company_code`, `asset`, `sub_asset`, `fiscal_year`, `line_seq`, `depreciation_area`, `posting_doc`, `value_date`, `transaction_type`, `transaction_amount`, `depreciation_posted`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `asset`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 6 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    e.tenant_id,
    e.BUKRS  AS company_code,
    e.ANLN1  AS asset,
    e.ANLN2  AS sub_asset,
    e.GJAHR  AS fiscal_year,
    e.LNRAN  AS line_seq,
    e.AFABE  AS depreciation_area,
    e.BELNR  AS posting_doc,
    e.BZDAT  AS value_date,
    e.BWASL  AS transaction_type,
    e.ANBTR  AS transaction_amount,
    e.NAFAB  AS depreciation_posted
FROM ANEP e
WHERE e.AFABE = '01';;

-- mv_fi_currency_rates
CREATE MATERIALIZED VIEW `mv_fi_currency_rates` (`tenant_id`, `rate_type`, `from_currency`, `to_currency`, `rate_date`, `exchange_rate`, `from_factor`, `to_factor`, `effective_rate`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `from_currency`) BUCKETS 8 
REFRESH ASYNC EVERY(INTERVAL 6 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    tenant_id, rate_type, from_currency, to_currency, rate_date,
    exchange_rate, from_factor, to_factor, effective_rate
FROM (
    SELECT
        r.tenant_id,
        r.KURST                              AS rate_type,
        r.FCURR                              AS from_currency,
        r.TCURR                              AS to_currency,
        r.GDATU                              AS rate_date,
        r.UKURS                              AS exchange_rate,
        COALESCE(r.FFACT, 1)                 AS from_factor,
        COALESCE(r.TFACT, 1)                 AS to_factor,
        CASE
            WHEN r.UKURS >= 0
                THEN  r.UKURS               * COALESCE(r.TFACT,1) / NULLIF(COALESCE(r.FFACT,1),0)
            ELSE     (1.0 / ABS(r.UKURS))   * COALESCE(r.TFACT,1) / NULLIF(COALESCE(r.FFACT,1),0)
        END                                  AS effective_rate,
        ROW_NUMBER() OVER (
            PARTITION BY r.tenant_id, r.KURST, r.FCURR, r.TCURR
            ORDER BY r.GDATU DESC
        )                                    AS rn
    FROM TCURR r
    WHERE r.GDATU <= CURRENT_DATE()
) t
WHERE rn = 1;;

-- mv_fi_doc_header_detail
CREATE MATERIALIZED VIEW `mv_fi_doc_header_detail` (`tenant_id`, `company_code`, `accounting_doc`, `fiscal_year`, `line_no`, `doc_type`, `posting_date`, `document_date`, `fiscal_period`, `document_currency`, `reference`, `entered_by`, `transaction_code`, `account_type`, `gl_account`, `debit_credit`, `customer`, `vendor`, `cost_center`, `order_no`, `wbs_element_int`, `material`, `plant`, `tax_code`, `amount_company_currency`, `amount_document_currency`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `company_code`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    h.tenant_id,
    h.BUKRS                                    AS company_code,
    h.BELNR                                    AS accounting_doc,
    h.GJAHR                                    AS fiscal_year,
    l.BUZEI                                    AS line_no,
    h.BLART                                    AS doc_type,
    h.BUDAT                                    AS posting_date,
    h.BLDAT                                    AS document_date,
    h.MONAT                                    AS fiscal_period,
    h.WAERS                                    AS document_currency,
    h.XBLNR                                    AS reference,
    h.USNAM                                    AS entered_by,
    h.TCODE                                    AS transaction_code,
    l.KOART                                    AS account_type,
    l.HKONT                                    AS gl_account,
    l.SHKZG                                    AS debit_credit,
    l.KUNNR                                    AS customer,
    l.LIFNR                                    AS vendor,
    l.KOSTL                                    AS cost_center,
    l.AUFNR                                    AS order_no,
    l.PROJK                                    AS wbs_element_int,
    l.MATNR                                    AS material,
    l.WERKS                                    AS plant,
    l.MWSKZ                                    AS tax_code,
    SUM(l.DMBTR)                               AS amount_company_currency,
    SUM(l.WRBTR)                               AS amount_document_currency
FROM BKPF h
JOIN BSEG l
     ON l.tenant_id = h.tenant_id AND l.BUKRS = h.BUKRS
    AND l.BELNR = h.BELNR AND l.GJAHR = h.GJAHR
WHERE (h.STBLG IS NULL OR h.STBLG = '')
GROUP BY h.tenant_id, h.BUKRS, h.BELNR, h.GJAHR, l.BUZEI, h.BLART, h.BUDAT,
         h.BLDAT, h.MONAT, h.WAERS, h.XBLNR, h.USNAM, h.TCODE, l.KOART, l.HKONT,
         l.SHKZG, l.KUNNR, l.LIFNR, l.KOSTL, l.AUFNR, l.PROJK, l.MATNR, l.WERKS, l.MWSKZ;;

-- mv_fi_fixed_asset_balances
CREATE MATERIALIZED VIEW `mv_fi_fixed_asset_balances` (`tenant_id`, `company_code`, `asset`, `sub_asset`, `asset_desc`, `asset_class`, `cost_center`, `plant`, `capitalization_date`, `deactivation_date`, `deletion_flag`, `fiscal_year`, `depreciation_area`, `acquisition_cost`, `write_ups`, `accum_ordinary_dep`, `accum_special_dep`, `current_year_acquisitions`, `current_year_retirements`, `planned_dep_year`, `net_book_value`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `company_code`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 12 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    a.tenant_id,
    a.BUKRS                                  AS company_code,
    a.ANLN1                                  AS asset,
    a.ANLN2                                  AS sub_asset,
    a.TXT50                                  AS asset_desc,
    a.ANLKL                                  AS asset_class,
    z.KOSTL                                  AS cost_center,
    z.WERKS                                  AS plant,
    a.AKTIV                                  AS capitalization_date,
    a.DEAKT                                  AS deactivation_date,
    a.XLOEV                                  AS deletion_flag,
    c.GJAHR                                  AS fiscal_year,
    c.AFABE                                  AS depreciation_area,
    c.KANSW                                  AS acquisition_cost,
    c.KAUFW                                  AS write_ups,
    c.KNAFA                                  AS accum_ordinary_dep,
    c.KAAFA                                  AS accum_special_dep,
    c.ANSWL                                  AS current_year_acquisitions,
    c.ABGAN                                  AS current_year_retirements,
    c.NAFAG                                  AS planned_dep_year,
    (COALESCE(c.KANSW,0) + COALESCE(c.KAUFW,0)
     + COALESCE(c.KNAFA,0) + COALESCE(c.KAAFA,0)) AS net_book_value
FROM ANLA a
JOIN (
    SELECT * FROM (
        SELECT c.*,
               ROW_NUMBER() OVER (
                   PARTITION BY c.tenant_id, c.BUKRS, c.ANLN1, c.ANLN2
                   ORDER BY c.GJAHR DESC
               ) AS rn
        FROM ANLC c
        WHERE c.AFABE = '01'
    ) cc WHERE rn = 1
) c
  ON c.tenant_id = a.tenant_id
 AND c.BUKRS     = a.BUKRS
 AND c.ANLN1     = a.ANLN1
 AND c.ANLN2     = a.ANLN2
LEFT JOIN (
    SELECT * FROM (
        SELECT z.tenant_id, z.BUKRS, z.ANLN1, z.ANLN2, z.KOSTL, z.WERKS, z.BDATU,
               ROW_NUMBER() OVER (
                   PARTITION BY z.tenant_id, z.BUKRS, z.ANLN1, z.ANLN2
                   ORDER BY z.BDATU DESC
               ) AS rn
        FROM ANLZ z
    ) zz WHERE rn = 1
) z
  ON z.tenant_id = a.tenant_id
 AND z.BUKRS     = a.BUKRS
 AND z.ANLN1     = a.ANLN1
 AND z.ANLN2     = a.ANLN2
WHERE (a.XLOEV IS NULL OR a.XLOEV <> 'X');;

-- mv_fi_gl_balance_monthly
CREATE MATERIALIZED VIEW `mv_fi_gl_balance_monthly` (`tenant_id`, `company_code`, `ledger`, `fiscal_year`, `fiscal_period`, `posting_month`, `gl_account`, `gl_account_name`, `profit_center`, `cost_center`, `segment`, `functional_area`, `company_currency`, `debit_amount`, `credit_amount`, `balance_amount`, `document_count`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `company_code`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    a.tenant_id,
    a.RBUKRS                                              AS company_code,
    a.RLDNR                                               AS ledger,
    a.GJAHR                                               AS fiscal_year,
    a.POPER                                               AS fiscal_period,
    date_trunc('month', a.BUDAT)                          AS posting_month,
    a.RACCT                                               AS gl_account,
    sk.TXT50                                              AS gl_account_name,
    a.PRCTR                                               AS profit_center,
    a.RCNTR                                               AS cost_center,
    a.SEGMENT                                             AS segment,
    a.RFAREA                                              AS functional_area,
    a.RHCUR                                               AS company_currency,
    SUM(CASE WHEN a.DRCRK='S' THEN a.HSL ELSE 0 END)      AS debit_amount,
    SUM(CASE WHEN a.DRCRK='H' THEN a.HSL ELSE 0 END)      AS credit_amount,
    SUM(a.HSL)                                            AS balance_amount,
    COUNT(DISTINCT a.BELNR)                               AS document_count
FROM ACDOCA a
LEFT JOIN SKAT sk
       ON sk.tenant_id = a.tenant_id AND sk.SAKNR = a.RACCT AND sk.SPRAS = 'E'
WHERE a.RLDNR = '0L'
  AND (a.XREVERSING IS NULL OR a.XREVERSING <> 'X')
GROUP BY a.tenant_id, a.RBUKRS, a.RLDNR, a.GJAHR, a.POPER, date_trunc('month', a.BUDAT),
         a.RACCT, sk.TXT50, a.PRCTR, a.RCNTR, a.SEGMENT, a.RFAREA, a.RHCUR;;

-- mv_fi_gl_line
CREATE MATERIALIZED VIEW `mv_fi_gl_line` (`tenant_id`, `company_code`, `ledger`, `fiscal_year`, `fiscal_period`, `posting_date`, `document_date`, `accounting_doc`, `line_no`, `doc_type`, `gl_account`, `gl_account_name`, `debit_credit`, `cost_center`, `profit_center`, `segment`, `functional_area`, `business_area`, `controlling_area`, `material`, `plant`, `customer`, `vendor`, `order_no`, `sales_order`, `sales_order_item`, `company_currency`, `transaction_currency`, `amount_company_currency`, `amount_transaction_currency`, `quantity`, `line_count`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `company_code`) BUCKETS 32 
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    a.tenant_id,
    a.RBUKRS                                   AS company_code,
    a.RLDNR                                    AS ledger,
    a.GJAHR                                    AS fiscal_year,
    a.POPER                                    AS fiscal_period,
    a.BUDAT                                    AS posting_date,
    a.BLDAT                                    AS document_date,
    a.BELNR                                    AS accounting_doc,
    a.DOCLN                                    AS line_no,
    a.BLART                                    AS doc_type,
    a.RACCT                                    AS gl_account,
    sk.TXT50                                   AS gl_account_name,
    a.DRCRK                                    AS debit_credit,
    a.RCNTR                                    AS cost_center,
    a.PRCTR                                    AS profit_center,
    a.SEGMENT                                  AS segment,
    a.RFAREA                                   AS functional_area,
    a.RBUSA                                    AS business_area,
    a.KOKRS                                    AS controlling_area,
    a.MATNR                                    AS material,
    a.WERKS                                    AS plant,
    a.KUNNR                                    AS customer,
    a.LIFNR                                    AS vendor,
    a.AUFNR                                    AS order_no,
    a.KDAUF                                    AS sales_order,
    a.KDPOS                                    AS sales_order_item,
    a.RHCUR                                    AS company_currency,
    a.RTCUR                                    AS transaction_currency,
    SUM(a.HSL)                                 AS amount_company_currency,
    SUM(a.WSL)                                 AS amount_transaction_currency,
    SUM(a.MSL)                                 AS quantity,
    COUNT(*)                                   AS line_count
FROM ACDOCA a
LEFT JOIN SKAT sk
       ON sk.tenant_id = a.tenant_id AND sk.SAKNR = a.RACCT AND sk.SPRAS = 'E'
WHERE a.RLDNR = '0L'
  AND (a.XREVERSING IS NULL OR a.XREVERSING <> 'X')
  AND (a.XREVERSED  IS NULL OR a.XREVERSED  <> 'X')
GROUP BY a.tenant_id, a.RBUKRS, a.RLDNR, a.GJAHR, a.POPER, a.BUDAT, a.BLDAT,
         a.BELNR, a.DOCLN, a.BLART, a.RACCT, sk.TXT50, a.DRCRK, a.RCNTR, a.PRCTR,
         a.SEGMENT, a.RFAREA, a.RBUSA, a.KOKRS, a.MATNR, a.WERKS, a.KUNNR,
         a.LIFNR, a.AUFNR, a.KDAUF, a.KDPOS, a.RHCUR, a.RTCUR;;

-- mv_fi_payment_run
CREATE MATERIALIZED VIEW `mv_fi_payment_run` (`tenant_id`, `company_code`, `run_date`, `run_id`, `payment_doc`, `vendor`, `vendor_name`, `country`, `currency`, `payment_amount`, `value_date`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `company_code`) BUCKETS 8 
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    CAST(h.tenant_id AS VARCHAR(20))         AS tenant_id,
    CAST(h.zbukr AS VARCHAR(8))              AS company_code,
    h.laufd                                  AS run_date,        -- raw SAP run date (string yyyymmdd)
    h.laufi                                  AS run_id,
    h.vblnr                                  AS payment_doc,
    h.lifnr                                  AS vendor,
    h.name1                                  AS vendor_name,
    h.land1                                  AS country,
    h.waers                                  AS currency,
    CAST(h.rbetr AS DECIMAL(23, 2))          AS payment_amount,
    h.valut                                  AS value_date
FROM REGUH h
WHERE (h.xvorl IS NULL OR h.xvorl <> 'X')          -- exclude proposal-only rows
  AND h.lifnr IS NOT NULL AND h.lifnr <> '';;

-- mv_fi_revenue_gl
CREATE MATERIALIZED VIEW `mv_fi_revenue_gl` (`tenant_id`, `company_code`, `fiscal_year`, `fiscal_period`, `posting_month`, `gl_account`, `gl_account_name`, `profit_center`, `segment`, `customer`, `material`, `sales_order`, `company_currency`, `revenue_amount`, `quantity`, `quantity_unit`)
DISTRIBUTED BY HASH(`tenant_id`, `company_code`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 6 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    a.tenant_id,
    a.RBUKRS                                   AS company_code,
    a.GJAHR                                    AS fiscal_year,
    a.POPER                                    AS fiscal_period,
    date_trunc('month', a.BUDAT)               AS posting_month,
    a.RACCT                                    AS gl_account,
    sk.TXT50                                   AS gl_account_name,
    a.PRCTR                                    AS profit_center,
    a.SEGMENT                                  AS segment,
    a.KUNNR                                    AS customer,
    a.MATNR                                    AS material,
    a.KDAUF                                    AS sales_order,
    a.RHCUR                                    AS company_currency,
    SUM(CASE WHEN a.DRCRK='H' THEN a.HSL ELSE -a.HSL END) AS revenue_amount,
    SUM(a.MSL)                                 AS quantity,
    a.RUNIT                                    AS quantity_unit
FROM ACDOCA a
LEFT JOIN SKAT sk
       ON sk.tenant_id = a.tenant_id
      AND sk.KTOPL     = a.KTOPL
      AND sk.SAKNR     = a.RACCT
      AND sk.SPRAS     = 'E'
WHERE a.RLDNR = '0L'
  AND a.GLACCOUNT_TYPE IN ('P','X')                    
  AND (a.XREVERSING IS NULL OR a.XREVERSING <> 'X')    
GROUP BY
    a.tenant_id, a.RBUKRS, a.GJAHR, a.POPER, date_trunc('month', a.BUDAT),
    a.RACCT, sk.TXT50, a.PRCTR, a.SEGMENT, a.KUNNR, a.MATNR, a.KDAUF, a.RHCUR, a.RUNIT;;

-- mv_fi_tax_lines
CREATE MATERIALIZED VIEW `mv_fi_tax_lines` (`tenant_id`, `company_code`, `fiscal_year`, `fiscal_period`, `posting_month`, `tax_code`, `tax_country`, `gl_account`, `profit_center`, `cost_center`, `company_currency`, `tax_amount`, `document_count`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `company_code`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    a.tenant_id,
    a.RBUKRS                                   AS company_code,
    a.GJAHR                                    AS fiscal_year,
    a.POPER                                    AS fiscal_period,
    date_trunc('month', a.BUDAT)               AS posting_month,
    a.MWSKZ                                    AS tax_code,
    a.TAX_COUNTRY                              AS tax_country,
    a.RACCT                                    AS gl_account,
    a.PRCTR                                    AS profit_center,
    a.RCNTR                                    AS cost_center,
    a.RHCUR                                    AS company_currency,
    SUM(CASE WHEN a.DRCRK='S' THEN a.HSL ELSE -a.HSL END) AS tax_amount,
    COUNT(DISTINCT a.BELNR)                    AS document_count
FROM ACDOCA a
WHERE a.RLDNR='0L'
  AND a.MWSKZ IS NOT NULL AND a.MWSKZ <> ''
GROUP BY a.tenant_id, a.RBUKRS, a.GJAHR, a.POPER, date_trunc('month', a.BUDAT),
         a.MWSKZ, a.TAX_COUNTRY, a.RACCT, a.PRCTR, a.RCNTR, a.RHCUR;;

-- mv_fi_tds_lines
CREATE MATERIALIZED VIEW `mv_fi_tds_lines` (`tenant_id`, `company_code`, `accounting_doc`, `fiscal_year`, `line_no`, `posting_date`, `withholding_tax_type`, `withholding_tax_code`, `vendor`, `vendor_name`, `profit_center`, `cost_center`, `tax_rate`, `withholding_base`, `withholding_tax`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `company_code`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    w.tenant_id,
    w.BUKRS                                    AS company_code,
    w.BELNR                                    AS accounting_doc,
    w.GJAHR                                    AS fiscal_year,
    w.BUZEI                                    AS line_no,
    h.BUDAT                                    AS posting_date,
    w.WITHT                                    AS withholding_tax_type,
    w.WT_WITHCD                                AS withholding_tax_code,
    w.LIFNR                                    AS vendor,
    lf.NAME1                                   AS vendor_name,
    b.PRCTR                                    AS profit_center,
    b.KOSTL                                    AS cost_center,
    w.QSATZ                                    AS tax_rate,
    SUM(w.WT_QSSHB)                            AS withholding_base,
    SUM(w.WT_QBSHB)                            AS withholding_tax
FROM WITH_ITEM w
JOIN BKPF h
     ON h.tenant_id=w.tenant_id AND h.BUKRS=w.BUKRS AND h.BELNR=w.BELNR AND h.GJAHR=w.GJAHR
LEFT JOIN BSEG b
     ON b.tenant_id=w.tenant_id AND b.BUKRS=w.BUKRS AND b.BELNR=w.BELNR
    AND b.GJAHR=w.GJAHR AND b.BUZEI=w.BUZEI
LEFT JOIN LFA1 lf
     ON lf.tenant_id=w.tenant_id AND lf.LIFNR=w.LIFNR
GROUP BY w.tenant_id, w.BUKRS, w.BELNR, w.GJAHR, w.BUZEI, h.BUDAT, w.WITHT,
         w.WT_WITHCD, w.LIFNR, lf.NAME1, b.PRCTR, b.KOSTL, w.QSATZ;;

-- mv_fi_trial_balance
CREATE MATERIALIZED VIEW `mv_fi_trial_balance` (`tenant_id`, `company_code`, `fiscal_year`, `fiscal_period`, `posting_month`, `gl_account`, `gl_account_name`, `is_balance_sheet`, `gl_account_type`, `company_currency`, `period_balance`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `company_code`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    a.tenant_id,
    a.RBUKRS                                   AS company_code,
    a.GJAHR                                    AS fiscal_year,
    a.POPER                                    AS fiscal_period,
    date_trunc('month', a.BUDAT)               AS posting_month,
    a.RACCT                                    AS gl_account,
    sk.TXT50                                   AS gl_account_name,
    ska.XBILK                                  AS is_balance_sheet,
    ska.GLACCOUNT_TYPE                         AS gl_account_type,
    a.RHCUR                                    AS company_currency,
    SUM(a.HSL)                                 AS period_balance
FROM ACDOCA a
LEFT JOIN SKAT sk
       ON sk.tenant_id = a.tenant_id AND sk.SAKNR = a.RACCT AND sk.SPRAS='E'
LEFT JOIN SKA1 ska
       ON ska.tenant_id = a.tenant_id AND ska.SAKNR = a.RACCT
WHERE a.RLDNR = '0L'
GROUP BY a.tenant_id, a.RBUKRS, a.GJAHR, a.POPER, date_trunc('month', a.BUDAT),
         a.RACCT, sk.TXT50, ska.XBILK, ska.GLACCOUNT_TYPE, a.RHCUR;;

-- mv_mm_actual_costing
CREATE MATERIALIZED VIEW `mv_mm_actual_costing` (`tenant_id`, `material`, `material_desc`, `valuation_area`, `valuation_type`, `fiscal_year`, `period`, `currency_type`, `standard_price`, `periodic_unit_price`, `total_stock_value`, `price_unit`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `material`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 4 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    cr.tenant_id,
    hd.MATNR                                   AS material,
    mk.MAKTX                                   AS material_desc,
    hd.BWKEY                                   AS valuation_area,
    hd.BWTAR                                   AS valuation_type,
    cr.BDATJ                                   AS fiscal_year,
    cr.POPER                                   AS period,
    cr.CURTP                                   AS currency_type,
    cr.STPRS                                   AS standard_price,
    cr.PVPRS                                   AS periodic_unit_price,
    cr.SALK3                                   AS total_stock_value,
    cr.PEINH                                   AS price_unit
FROM CKMLCR cr
JOIN CKMLHD hd
     ON hd.tenant_id=cr.tenant_id AND hd.KALNR=cr.KALNR
LEFT JOIN MAKT mk
     ON mk.tenant_id=hd.tenant_id AND mk.MATNR=hd.MATNR AND mk.SPRAS='E';;

-- mv_mm_gr_fulfillment
CREATE MATERIALIZED VIEW `mv_mm_gr_fulfillment` (`tenant_id`, `purchase_order`, `item`, `gr_date`, `material`, `plant`, `movement_type`, `currency`, `gr_qty`, `gr_value`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `purchase_order`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    b.tenant_id,
    b.EBELN                                    AS purchase_order,
    b.EBELP                                    AS item,
    b.BUDAT                                    AS gr_date,
    b.MATNR                                    AS material,
    b.WERKS                                    AS plant,
    b.BWART                                    AS movement_type,
    b.WAERS                                    AS currency,
    SUM(CASE WHEN b.SHKZG='S' THEN b.MENGE ELSE -b.MENGE END) AS gr_qty,
    SUM(CASE WHEN b.SHKZG='S' THEN b.DMBTR ELSE -b.DMBTR END) AS gr_value
FROM EKBE b
WHERE b.VGABE='1'           -- goods receipt
GROUP BY b.tenant_id, b.EBELN, b.EBELP, b.BUDAT, b.MATNR, b.WERKS, b.BWART, b.WAERS;;

-- mv_mm_info_record_prices
CREATE MATERIALIZED VIEW `mv_mm_info_record_prices` (`tenant_id`, `info_record`, `vendor`, `vendor_name`, `material`, `material_desc`, `material_group`, `purch_org`, `plant`, `net_price`, `price_unit`, `currency`, `planned_deliv_time`, `tax_code`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `vendor`) BUCKETS 8 
REFRESH ASYNC EVERY(INTERVAL 4 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    a.tenant_id,
    a.INFNR                                    AS info_record,
    a.LIFNR                                    AS vendor,
    lf.NAME1                                   AS vendor_name,
    a.MATNR                                    AS material,
    mk.MAKTX                                   AS material_desc,
    a.MATKL                                    AS material_group,
    e.EKORG                                    AS purch_org,
    e.WERKS                                    AS plant,
    e.NETPR                                    AS net_price,
    e.PEINH                                    AS price_unit,
    e.WAERS                                    AS currency,
    e.APLFZ                                    AS planned_deliv_time,
    e.MWSKZ                                    AS tax_code
FROM EINA a
JOIN EINE e
     ON e.tenant_id=a.tenant_id AND e.INFNR=a.INFNR
LEFT JOIN LFA1 lf ON lf.tenant_id=a.tenant_id AND lf.LIFNR=a.LIFNR
LEFT JOIN MAKT mk ON mk.tenant_id=a.tenant_id AND mk.MATNR=a.MATNR AND mk.SPRAS='E'
WHERE (a.LOEKZ IS NULL OR a.LOEKZ='');;

-- mv_mm_material_movements_daily
CREATE MATERIALIZED VIEW `mv_mm_material_movements_daily` (`tenant_id`, `posting_date`, `plant`, `storage_location`, `material`, `movement_type`, `batch`, `vendor`, `customer`, `purchase_order`, `order_no`, `currency`, `base_unit`, `movement_qty`, `movement_value`, `line_count`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `plant`) BUCKETS 32 
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    m.tenant_id,
    m.BUDAT                                    AS posting_date,
    m.WERKS                                    AS plant,
    m.LGORT                                    AS storage_location,
    m.MATNR                                    AS material,
    m.BWART                                    AS movement_type,
    m.CHARG                                    AS batch,
    m.LIFNR                                    AS vendor,
    m.KUNNR                                    AS customer,
    m.EBELN                                    AS purchase_order,
    m.AUFNR                                    AS order_no,
    m.WAERS                                    AS currency,
    m.MEINS                                    AS base_unit,
    SUM(CASE WHEN m.SHKZG='S' THEN m.MENGE ELSE -m.MENGE END) AS movement_qty,
    SUM(CASE WHEN m.SHKZG='S' THEN m.DMBTR ELSE -m.DMBTR END) AS movement_value,
    COUNT(*)                                   AS line_count
FROM MATDOC m
WHERE (m.CANCELLED IS NULL OR m.CANCELLED <> 'X')
GROUP BY m.tenant_id, m.BUDAT, m.WERKS, m.LGORT, m.MATNR, m.BWART, m.CHARG,
         m.LIFNR, m.KUNNR, m.EBELN, m.AUFNR, m.WAERS, m.MEINS;;

-- mv_mm_material_valuation
CREATE MATERIALIZED VIEW `mv_mm_material_valuation` (`tenant_id`, `material`, `material_desc`, `valuation_area`, `valuation_type`, `material_group`, `price_control`, `standard_price`, `moving_avg_price`, `price_unit`, `total_stock_qty`, `total_stock_value`, `valuation_class`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `valuation_area`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    v.tenant_id,
    v.MATNR                                    AS material,
    mk.MAKTX                                   AS material_desc,
    v.BWKEY                                    AS valuation_area,
    v.BWTAR                                    AS valuation_type,
    ma.MATKL                                   AS material_group,
    v.VPRSV                                    AS price_control,
    v.STPRS                                    AS standard_price,
    v.VERPR                                    AS moving_avg_price,
    v.PEINH                                    AS price_unit,
    v.LBKUM                                    AS total_stock_qty,
    v.SALK3                                    AS total_stock_value,
    v.BKLAS                                    AS valuation_class
FROM MBEW v
LEFT JOIN MARA ma ON ma.tenant_id=v.tenant_id AND ma.MATNR=v.MATNR
LEFT JOIN MAKT mk ON mk.tenant_id=v.tenant_id AND mk.MATNR=v.MATNR AND mk.SPRAS='E';;

-- mv_mm_open_purchase_orders
CREATE MATERIALIZED VIEW `mv_mm_open_purchase_orders` (`tenant_id`, `po_date`, `purchase_order`, `item`, `po_changed_on`, `purch_org`, `vendor`, `vendor_name`, `material`, `plant`, `po_qty`, `order_unit`, `net_value`, `currency`, `delivery_date`, `received_qty`, `open_qty`)
DISTRIBUTED BY HASH(`tenant_id`, `purch_org`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 30 MINUTE)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    h.tenant_id,
    h.BEDAT                                    AS po_date,        -- = EKKO partition column
    h.EBELN                                    AS purchase_order,
    i.EBELP                                    AS item,
    h.AEDAT                                    AS po_changed_on,  -- ordinary column, fine to keep
    h.EKORG                                    AS purch_org,
    h.LIFNR                                    AS vendor,
    lf.NAME1                                   AS vendor_name,
    i.MATNR                                    AS material,
    i.WERKS                                    AS plant,
    i.MENGE                                    AS po_qty,
    i.MEINS                                    AS order_unit,
    i.NETWR                                    AS net_value,
    h.WAERS                                    AS currency,
    et.EINDT                                   AS delivery_date,
    et.WEMNG                                   AS received_qty,
    (i.MENGE - COALESCE(et.WEMNG,0))           AS open_qty
FROM EKKO h
JOIN EKPO i
     ON i.tenant_id=h.tenant_id AND i.EBELN=h.EBELN
LEFT JOIN EKET et
     ON et.tenant_id=i.tenant_id AND et.EBELN=i.EBELN AND et.EBELP=i.EBELP
LEFT JOIN LFA1 lf
     ON lf.tenant_id=h.tenant_id AND lf.LIFNR=h.LIFNR
WHERE (i.LOEKZ IS NULL OR i.LOEKZ='')
  AND (i.ELIKZ IS NULL OR i.ELIKZ <> 'X');;

-- mv_mm_purchase_order_flat
CREATE MATERIALIZED VIEW `mv_mm_purchase_order_flat` (`tenant_id`, `purchase_order`, `item`, `po_date`, `po_type`, `po_category`, `company_code`, `purch_org`, `purch_group`, `vendor`, `vendor_name`, `currency`, `material`, `material_desc`, `material_group`, `plant`, `storage_location`, `po_qty`, `order_unit`, `net_price`, `price_unit`, `net_value`, `tax_code`, `delivery_completed`, `final_invoice`, `purchase_req`, `cost_center`, `profit_center`, `deletion_flag`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `purch_org`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    h.tenant_id,
    h.EBELN                                    AS purchase_order,
    i.EBELP                                    AS item,
    h.BEDAT                                    AS po_date,
    h.BSART                                    AS po_type,
    h.BSTYP                                    AS po_category,
    h.BUKRS                                    AS company_code,
    h.EKORG                                    AS purch_org,
    h.EKGRP                                    AS purch_group,
    h.LIFNR                                    AS vendor,
    lf.NAME1                                   AS vendor_name,
    h.WAERS                                    AS currency,
    i.MATNR                                    AS material,
    mk.MAKTX                                   AS material_desc,
    i.MATKL                                    AS material_group,
    i.WERKS                                    AS plant,
    i.LGORT                                    AS storage_location,
    i.MENGE                                    AS po_qty,
    i.MEINS                                    AS order_unit,
    i.NETPR                                    AS net_price,
    i.PEINH                                    AS price_unit,
    i.NETWR                                    AS net_value,
    i.MWSKZ                                    AS tax_code,
    i.ELIKZ                                    AS delivery_completed,
    i.EREKZ                                    AS final_invoice,
    i.BANFN                                    AS purchase_req,
    ak.KOSTL                                   AS cost_center,
    ak.PRCTR                                   AS profit_center,
    i.LOEKZ                                    AS deletion_flag
FROM EKKO h
JOIN EKPO i
     ON i.tenant_id=h.tenant_id AND i.EBELN=h.EBELN
LEFT JOIN LFA1 lf
     ON lf.tenant_id=h.tenant_id AND lf.LIFNR=h.LIFNR
LEFT JOIN MAKT mk
     ON mk.tenant_id=h.tenant_id AND mk.MATNR=i.MATNR AND mk.SPRAS='E'
LEFT JOIN (
    SELECT tenant_id, EBELN, EBELP, KOSTL, PRCTR,
           ROW_NUMBER() OVER (PARTITION BY tenant_id, EBELN, EBELP ORDER BY ZEKKN) AS rn
    FROM EKKN
    WHERE (LOEKZ IS NULL OR LOEKZ = '')
) ak
     ON ak.tenant_id=h.tenant_id AND ak.EBELN=i.EBELN AND ak.EBELP=i.EBELP AND ak.rn=1;;

-- mv_mm_stock_on_hand
CREATE MATERIALIZED VIEW `mv_mm_stock_on_hand` (`tenant_id`, `material`, `material_desc`, `plant`, `plant_name`, `storage_location`, `base_unit`, `material_group`, `unrestricted_qty`, `quality_inspection_qty`, `blocked_qty`, `restricted_qty`, `total_stock_qty`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `plant`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 30 MINUTE)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    d.tenant_id,
    d.MATNR                                    AS material,
    mk.MAKTX                                   AS material_desc,
    d.WERKS                                    AS plant,
    pl.NAME1                                   AS plant_name,
    d.LGORT                                    AS storage_location,
    ma.MEINS                                   AS base_unit,
    ma.MATKL                                   AS material_group,
    d.LABST                                    AS unrestricted_qty,
    d.INSME                                    AS quality_inspection_qty,
    d.SPEME                                    AS blocked_qty,
    d.EINME                                    AS restricted_qty,
    (COALESCE(d.LABST,0)+COALESCE(d.INSME,0)+COALESCE(d.SPEME,0)+COALESCE(d.EINME,0)) AS total_stock_qty
FROM MARD d
LEFT JOIN MARA ma ON ma.tenant_id=d.tenant_id AND ma.MATNR=d.MATNR
LEFT JOIN MAKT mk ON mk.tenant_id=d.tenant_id AND mk.MATNR=d.MATNR AND mk.SPRAS='E'
LEFT JOIN T001W pl ON pl.tenant_id=d.tenant_id AND pl.WERKS=d.WERKS;;

-- mv_mm_batch_stock
-- Batch-level on-hand stock from MCHB (only meaningful for batch-managed materials).
-- Same stock-category split as StockOnHand but one row per material/plant/storage-loc/BATCH.
CREATE MATERIALIZED VIEW `mv_mm_batch_stock` (`tenant_id`, `material`, `material_desc`, `plant`, `plant_name`, `storage_location`, `batch`, `base_unit`, `material_group`, `unrestricted_qty`, `quality_inspection_qty`, `blocked_qty`, `restricted_qty`, `total_stock_qty`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `plant`) BUCKETS 16
REFRESH ASYNC EVERY(INTERVAL 30 MINUTE)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    c.tenant_id,
    c.MATNR                                    AS material,
    mk.MAKTX                                   AS material_desc,
    c.WERKS                                    AS plant,
    pl.NAME1                                   AS plant_name,
    c.LGORT                                    AS storage_location,
    c.CHARG                                    AS batch,
    ma.MEINS                                   AS base_unit,
    ma.MATKL                                   AS material_group,
    c.CLABS                                    AS unrestricted_qty,
    c.CINSM                                    AS quality_inspection_qty,
    c.CSPEM                                    AS blocked_qty,
    c.CEINM                                    AS restricted_qty,
    (COALESCE(c.CLABS,0)+COALESCE(c.CINSM,0)+COALESCE(c.CSPEM,0)+COALESCE(c.CEINM,0)) AS total_stock_qty
FROM MCHB c
LEFT JOIN MARA ma ON ma.tenant_id=c.tenant_id AND ma.MATNR=c.MATNR
LEFT JOIN MAKT mk ON mk.tenant_id=c.tenant_id AND mk.MATNR=c.MATNR AND mk.SPRAS='E'
LEFT JOIN T001W pl ON pl.tenant_id=c.tenant_id AND pl.WERKS=c.WERKS;;

-- mv_mm_sales_order_stock
-- Make-to-order / sales-order-assigned special stock (special stock indicator 'E') from MSKA.
-- One row per material/plant/storage-loc/batch reserved against a specific sales order line.
CREATE MATERIALIZED VIEW `mv_mm_sales_order_stock` (`tenant_id`, `material`, `material_desc`, `plant`, `plant_name`, `storage_location`, `batch`, `sales_order`, `sales_order_item`, `special_stock_ind`, `base_unit`, `material_group`, `unrestricted_qty`, `quality_inspection_qty`, `blocked_qty`, `restricted_qty`, `total_stock_qty`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `plant`) BUCKETS 16
REFRESH ASYNC EVERY(INTERVAL 30 MINUTE)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    k.tenant_id,
    k.MATNR                                    AS material,
    mk.MAKTX                                   AS material_desc,
    k.WERKS                                    AS plant,
    pl.NAME1                                   AS plant_name,
    k.LGORT                                    AS storage_location,
    k.CHARG                                    AS batch,
    k.VBELN                                    AS sales_order,
    k.POSNR                                    AS sales_order_item,
    k.SOBKZ                                    AS special_stock_ind,
    ma.MEINS                                   AS base_unit,
    ma.MATKL                                   AS material_group,
    k.KALAB                                    AS unrestricted_qty,
    k.KAINS                                    AS quality_inspection_qty,
    k.KASPE                                    AS blocked_qty,
    k.KAEIN                                    AS restricted_qty,
    (COALESCE(k.KALAB,0)+COALESCE(k.KAINS,0)+COALESCE(k.KASPE,0)+COALESCE(k.KAEIN,0)) AS total_stock_qty
FROM MSKA k
LEFT JOIN MARA ma ON ma.tenant_id=k.tenant_id AND ma.MATNR=k.MATNR
LEFT JOIN MAKT mk ON mk.tenant_id=k.tenant_id AND mk.MATNR=k.MATNR AND mk.SPRAS='E'
LEFT JOIN T001W pl ON pl.tenant_id=k.tenant_id AND pl.WERKS=k.WERKS;;

-- mv_mm_vendor_spend
CREATE MATERIALIZED VIEW `mv_mm_vendor_spend` (`tenant_id`, `vendor`, `vendor_name`, `purch_org`, `posting_date`, `material`, `plant`, `history_category`, `transaction_type`, `currency`, `amount_lc`, `quantity`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `vendor`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    b.tenant_id,
    h.LIFNR                                    AS vendor,
    lf.NAME1                                   AS vendor_name,
    h.EKORG                                    AS purch_org,
    b.BUDAT                                    AS posting_date,
    b.MATNR                                    AS material,
    b.WERKS                                    AS plant,
    b.BEWTP                                    AS history_category,
    b.VGABE                                    AS transaction_type,
    b.WAERS                                    AS currency,
    SUM(CASE WHEN b.SHKZG='S' THEN b.DMBTR ELSE -b.DMBTR END) AS amount_lc,
    SUM(CASE WHEN b.SHKZG='S' THEN b.MENGE ELSE -b.MENGE END) AS quantity
FROM EKBE b
JOIN EKKO h
     ON h.tenant_id=b.tenant_id AND h.EBELN=b.EBELN
LEFT JOIN LFA1 lf
     ON lf.tenant_id=h.tenant_id AND lf.LIFNR=h.LIFNR
GROUP BY b.tenant_id, h.LIFNR, lf.NAME1, h.EKORG, b.BUDAT, b.MATNR, b.WERKS,
         b.BEWTP, b.VGABE, b.WAERS;;

-- mv_pm_maintenance_orders
CREATE MATERIALIZED VIEW `mv_pm_maintenance_orders` (`tenant_id`, `maintenance_order`, `order_type`, `created_on`, `order_text`, `maintenance_plant`, `equipment`, `equipment_type`, `manufacturer`, `functional_location`, `floc_category`, `main_work_center`, `priority`, `planner_group`, `activity_type`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `maintenance_plant`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    k.tenant_id,
    k.AUFNR                                    AS maintenance_order,
    k.AUART                                    AS order_type,
    k.ERDAT                                    AS created_on,
    k.KTEXT                                    AS order_text,
    ih.IWERK                                   AS maintenance_plant,
    ih.EQUNR                                   AS equipment,
    eq.EQART                                   AS equipment_type,
    eq.HERST                                   AS manufacturer,
    ih.TPLNR                                   AS functional_location,
    fl.FLTYP                                   AS floc_category,
    ih.GEWRK                                   AS main_work_center,
    ih.PRIOK                                   AS priority,
    ih.INGRP                                   AS planner_group,
    ih.ILART                                   AS activity_type
FROM AUFK k
JOIN AFIH ih
     ON ih.tenant_id=k.tenant_id AND ih.AUFNR=k.AUFNR
LEFT JOIN EQUI eq
     ON eq.tenant_id=ih.tenant_id AND eq.EQUNR=ih.EQUNR
LEFT JOIN IFLOT fl
     ON fl.tenant_id=ih.tenant_id AND fl.TPLNR=ih.TPLNR
WHERE k.AUTYP='30';;

-- mv_pp_component_consumption
CREATE MATERIALIZED VIEW `mv_pp_component_consumption` (`tenant_id`, `production_order`, `reservation_item`, `component`, `component_desc`, `plant`, `required_qty`, `withdrawn_qty`, `open_qty`, `unit`)
DISTRIBUTED BY HASH(`tenant_id`, `production_order`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    CAST(r.tenant_id AS VARCHAR(20))                                 AS tenant_id,
    CAST(r.AUFNR     AS VARCHAR(24))                                 AS production_order,
    CAST(r.RSPOS     AS VARCHAR(8))                                  AS reservation_item,
    CAST(r.MATNR     AS VARCHAR(40))                                 AS component,
    mk.MAKTX                                                         AS component_desc,
    CAST(r.WERKS     AS VARCHAR(8))                                  AS plant,
    CAST(r.BDMNG     AS DECIMAL(18,3))                               AS required_qty,
    CAST(r.ENMNG     AS DECIMAL(18,3))                               AS withdrawn_qty,
    CAST(COALESCE(r.BDMNG,0) - COALESCE(r.ENMNG,0) AS DECIMAL(18,3)) AS open_qty,
    CAST(r.MEINS     AS VARCHAR(6))                                  AS unit
FROM RESB r
LEFT JOIN MAKT mk
       ON mk.tenant_id = r.tenant_id
      AND mk.MATNR     = r.MATNR
      AND mk.SPRAS     = 'E'
WHERE (r.XLOEK IS NULL OR r.XLOEK <> 'X')
  AND r.AUFNR IS NOT NULL AND r.AUFNR <> '';;

-- mv_pp_open_production_orders
CREATE MATERIALIZED VIEW `mv_pp_open_production_orders` (`tenant_id`, `production_order`, `order_type`, `plant`, `material`, `basic_finish_date`, `order_qty`, `delivered_qty`, `open_qty`, `order_unit`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `plant`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 30 MINUTE)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    k.tenant_id,
    k.AUFNR                                    AS production_order,
    k.AUART                                    AS order_type,
    k.WERKS                                    AS plant,
    p.MATNR                                    AS material,
    h.GLTRP                                    AS basic_finish_date,
    h.GAMNG                                    AS order_qty,
    p.WEMNG                                    AS delivered_qty,
    (h.GAMNG - COALESCE(p.WEMNG,0))            AS open_qty,
    h.GMEIN                                    AS order_unit
FROM AUFK k
JOIN AFKO h ON h.tenant_id=k.tenant_id AND h.AUFNR=k.AUFNR
JOIN AFPO p ON p.tenant_id=k.tenant_id AND p.AUFNR=k.AUFNR
WHERE k.AUTYP='10'
  AND (p.ELIKZ IS NULL OR p.ELIKZ <> 'X');;

-- mv_pp_operation_efficiency
CREATE MATERIALIZED VIEW `mv_pp_operation_efficiency` (`tenant_id`, `production_order`, `operation`, `work_center_id`, `plant`, `operation_text`, `planned_op_qty`, `yield_qty`, `scrap_qty`, `unit`, `planned_work`, `actual_work`, `sched_start_date`, `sched_finish_date`, `actual_start_date`, `actual_finish_date`, `finish_delay_days`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `plant`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    c.tenant_id,
    h.AUFNR                                    AS production_order,
    c.VORNR                                    AS operation,
    c.ARBID                                    AS work_center_id,
    c.WERKS                                    AS plant,
    c.LTXA1                                    AS operation_text,
    v.MGVRG                                    AS planned_op_qty,
    v.LMNGA                                    AS yield_qty,
    v.XMNGA                                    AS scrap_qty,
    v.MEINH                                    AS unit,
    v.ARBEI                                    AS planned_work,
    v.ISMNW                                    AS actual_work,
    v.FSAVD                                    AS sched_start_date,
    v.FSEDD                                    AS sched_finish_date,
    v.ISDD                                     AS actual_start_date,
    v.IEDD                                     AS actual_finish_date,
    DATEDIFF(v.IEDD, v.FSEDD)                  AS finish_delay_days
FROM AFVC c
JOIN AFVV v
     ON v.tenant_id=c.tenant_id AND v.AUFPL=c.AUFPL AND v.APLZL=c.APLZL
JOIN AFKO h
     ON h.tenant_id=c.tenant_id AND h.AUFPL=c.AUFPL;;

-- mv_pp_order_confirmations
CREATE MATERIALIZED VIEW `mv_pp_order_confirmations` (`tenant_id`, `production_order`, `confirmation`, `confirmation_counter`, `posting_date`, `plant`, `work_center_id`, `operation`, `personnel_no`, `unit`, `yield_qty`, `scrap_qty`, `actual_work`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `plant`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    c.tenant_id,
    c.AUFNR                                    AS production_order,
    c.RUECK                                    AS confirmation,
    c.RMZHL                                    AS confirmation_counter,
    c.BUDAT                                    AS posting_date,
    c.WERKS                                    AS plant,
    c.ARBID                                    AS work_center_id,
    c.VORNR                                    AS operation,
    c.PERNR                                    AS personnel_no,
    c.GMEIN                                    AS unit,
    SUM(c.LMNGA)                               AS yield_qty,
    SUM(c.XMNGA)                               AS scrap_qty,
    SUM(c.ISMNW)                               AS actual_work
FROM AFRU c
WHERE (c.STOKZ IS NULL OR c.STOKZ <> 'X')   -- not a reversal
GROUP BY c.tenant_id, c.AUFNR, c.RUECK, c.RMZHL, c.BUDAT, c.WERKS, c.ARBID,
         c.VORNR, c.PERNR, c.GMEIN;;

-- mv_pp_production_order_flat
CREATE MATERIALIZED VIEW `mv_pp_production_order_flat` (`tenant_id`, `production_order`, `item`, `order_type`, `plant`, `controlling_area`, `profit_center`, `responsible_cost_center`, `planned_material`, `material`, `material_desc`, `basic_start_date`, `basic_finish_date`, `actual_start_date`, `actual_finish_date`, `order_qty`, `order_unit`, `delivered_qty`, `production_plant`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `plant`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    k.tenant_id,
    k.AUFNR                                    AS production_order,
    p.POSNR                                    AS item,
    k.AUART                                    AS order_type,
    k.WERKS                                    AS plant,
    k.KOKRS                                    AS controlling_area,
    k.PRCTR                                    AS profit_center,
    k.KOSTV                                    AS responsible_cost_center,
    h.PLNBEZ                                   AS planned_material,
    p.MATNR                                    AS material,
    mk.MAKTX                                   AS material_desc,
    h.GSTRP                                    AS basic_start_date,
    h.GLTRP                                    AS basic_finish_date,
    h.GSTRI                                    AS actual_start_date,
    h.GLTRI                                    AS actual_finish_date,
    h.GAMNG                                    AS order_qty,
    h.GMEIN                                    AS order_unit,
    p.WEMNG                                    AS delivered_qty,
    p.PWERK                                    AS production_plant
FROM AUFK k
JOIN AFKO h ON h.tenant_id=k.tenant_id AND h.AUFNR=k.AUFNR
JOIN AFPO p ON p.tenant_id=k.tenant_id AND p.AUFNR=k.AUFNR
LEFT JOIN MAKT mk ON mk.tenant_id=k.tenant_id AND mk.MATNR=p.MATNR AND mk.SPRAS='E'
WHERE k.AUTYP='10';;

-- mv_pp_yield_variance
CREATE MATERIALIZED VIEW `mv_pp_yield_variance` (`tenant_id`, `production_order`, `plant`, `material`, `basic_finish_date`, `planned_qty`, `delivered_qty`, `yield_variance_qty`, `unit`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `plant`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    k.tenant_id,
    k.AUFNR                                    AS production_order,
    k.WERKS                                    AS plant,
    p.MATNR                                    AS material,
    h.GLTRP                                    AS basic_finish_date,
    h.GAMNG                                    AS planned_qty,
    p.WEMNG                                    AS delivered_qty,
    (p.WEMNG - h.GAMNG)                        AS yield_variance_qty,
    h.GMEIN                                    AS unit
FROM AUFK k
JOIN AFKO h ON h.tenant_id=k.tenant_id AND h.AUFNR=k.AUFNR
JOIN AFPO p ON p.tenant_id=k.tenant_id AND p.AUFNR=k.AUFNR
WHERE k.AUTYP='10';;

-- mv_process_change_log
CREATE MATERIALIZED VIEW `mv_process_change_log` (`tenant_id`, `object_class`, `object_id`, `change_no`, `change_date`, `change_time`, `changed_by`, `transaction_code`, `table_name`, `field_name`, `change_type`, `old_value`, `new_value`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `object_id`) BUCKETS 32 
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    h.tenant_id,
    h.OBJECTCLAS                               AS object_class,
    h.OBJECTID                                 AS object_id,
    h.CHANGENR                                 AS change_no,
    h.UDATE                                    AS change_date,
    h.UTIME                                    AS change_time,
    h.USERNAME                                 AS changed_by,
    h.TCODE                                    AS transaction_code,
    p.TABNAME                                  AS table_name,
    p.FNAME                                    AS field_name,
    p.CHNGIND                                  AS change_type,
    p.VALUE_OLD                                AS old_value,
    p.VALUE_NEW                                AS new_value
FROM CDHDR h
JOIN CDPOS p
     ON p.tenant_id=h.tenant_id AND p.OBJECTCLAS=h.OBJECTCLAS
    AND p.OBJECTID=h.OBJECTID AND p.CHANGENR=h.CHANGENR;;

-- mv_ps_project_cost_summary
CREATE MATERIALIZED VIEW `mv_ps_project_cost_summary` (`tenant_id`, `project_id`, `project_name`, `wbs_element`, `wbs_name`, `company_code`, `controlling_area`, `profit_center`, `fiscal_year`, `value_type`, `currency`, `amount_year`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `project_id`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 4 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    ws.tenant_id,
    pr.PSPID                                   AS project_id,
    pr.POST1                                   AS project_name,
    ws.POSID                                   AS wbs_element,
    ws.POST1                                   AS wbs_name,
    ws.PBUKR                                   AS company_code,
    ws.PKOKR                                   AS controlling_area,
    ws.PRCTR                                   AS profit_center,
    r.GJAHR                                    AS fiscal_year,
    r.WRTTP                                    AS value_type,
    r.TWAER                                    AS currency,
    SUM(COALESCE(r.WLP01,0)+COALESCE(r.WLP02,0)+COALESCE(r.WLP03,0)+COALESCE(r.WLP04,0)
       +COALESCE(r.WLP05,0)+COALESCE(r.WLP06,0)+COALESCE(r.WLP07,0)+COALESCE(r.WLP08,0)
       +COALESCE(r.WLP09,0)+COALESCE(r.WLP10,0)+COALESCE(r.WLP11,0)+COALESCE(r.WLP12,0)) AS amount_year
FROM PRPS ws
JOIN PROJ pr ON pr.tenant_id=ws.tenant_id AND pr.PSPNR=ws.PSPHI
LEFT JOIN RPSCO r ON r.tenant_id=ws.tenant_id AND r.OBJNR=ws.OBJNR
WHERE (ws.LOEVM IS NULL OR ws.LOEVM <> 'X')
GROUP BY ws.tenant_id, pr.PSPID, pr.POST1, ws.POSID, ws.POST1, ws.PBUKR, ws.PKOKR,
         ws.PRCTR, r.GJAHR, r.WRTTP, r.TWAER;;

-- mv_qm_inspection_results
CREATE MATERIALIZED VIEW `mv_qm_inspection_results` (`tenant_id`, `inspection_lot`, `lot_created_on`, `plant`, `material`, `material_desc`, `inspection_type`, `lot_origin`, `vendor`, `purchase_order`, `order_no`, `batch`, `lot_qty`, `unit`, `ud_code`, `ud_valuation`, `ud_date`, `rejected_qty`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `plant`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    l.tenant_id,
    l.PRUEFLOS                                 AS inspection_lot,
    l.ERSTELDAT                                AS lot_created_on,
    l.WERK                                     AS plant,
    l.MATNR                                    AS material,
    mk.MAKTX                                   AS material_desc,
    l.ART                                      AS inspection_type,
    l.HERKUNFT                                 AS lot_origin,
    l.LIFNR                                    AS vendor,
    l.EBELN                                    AS purchase_order,
    l.AUFNR                                    AS order_no,
    l.CHARG                                    AS batch,
    l.LOSMENGE                                 AS lot_qty,
    l.MEINS                                    AS unit,
    ud.VCODE                                   AS ud_code,
    ud.VBEWERTG                                AS ud_valuation,
    ud.VDATUM                                  AS ud_date,
    CASE WHEN ud.VBEWERTG='R' THEN l.LOSMENGE ELSE 0 END AS rejected_qty
FROM QALS l
LEFT JOIN QAVE ud
     ON ud.tenant_id=l.tenant_id AND ud.PRUEFLOS=l.PRUEFLOS
LEFT JOIN MAKT mk
     ON mk.tenant_id=l.tenant_id AND mk.MATNR=l.MATNR AND mk.SPRAS='E';;

-- mv_qm_notifications
CREATE MATERIALIZED VIEW `mv_qm_notifications` (`tenant_id`, `notification_no`, `notification_date`, `notification_type`, `short_text`, `plant`, `material`, `material_desc`, `vendor`, `customer`, `effect`, `order_no`, `complaint_qty`, `notification_count`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `plant`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    q.tenant_id,
    q.QMNUM                                    AS notification_no,
    q.ERDAT                                    AS notification_date,
    q.QMART                                    AS notification_type,
    q.QMTXT                                    AS short_text,
    q.MAWERK                                   AS plant,
    q.MATNR                                    AS material,
    mk.MAKTX                                   AS material_desc,
    q.LIFNUM                                   AS vendor,
    q.KUNUM                                    AS customer,
    q.AUSWIRK                                  AS effect,
    q.AUFNR                                    AS order_no,
    SUM(q.RKMNG)                               AS complaint_qty,
    COUNT(*)                                   AS notification_count
FROM QMEL q
LEFT JOIN MAKT mk
     ON mk.tenant_id=q.tenant_id AND mk.MATNR=q.MATNR AND mk.SPRAS='E'
GROUP BY q.tenant_id, q.QMNUM, q.ERDAT, q.QMART, q.QMTXT, q.MAWERK, q.MATNR,
         mk.MAKTX, q.LIFNUM, q.KUNUM, q.AUSWIRK, q.AUFNR;;

-- mv_sd_billing_flat
CREATE MATERIALIZED VIEW `mv_sd_billing_flat` (`tenant_id`, `billing_doc`, `item`, `billing_date`, `billing_type`, `doc_category`, `sales_org`, `distribution_channel`, `company_code`, `sold_to`, `payer`, `customer_name`, `material`, `material_desc`, `material_group`, `plant`, `profit_center`, `sales_office`, `sales_group`, `sales_order`, `delivery_doc`, `billed_qty`, `sales_unit`, `currency`, `net_value`, `tax_amount`, `cost_value`, `margin_amount`, `customer_region`, `supplier_region`, `is_interstate`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `sales_org`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    h.tenant_id,
    h.VBELN                                    AS billing_doc,
    i.POSNR                                    AS item,
    h.FKDAT                                    AS billing_date,
    h.FKART                                    AS billing_type,
    h.VBTYP                                    AS doc_category,
    h.VKORG                                    AS sales_org,
    h.VTWEG                                    AS distribution_channel,
    h.BUKRS                                    AS company_code,
    h.KUNAG                                    AS sold_to,
    h.KUNRG                                    AS payer,
    kn.NAME1                                   AS customer_name,
    i.MATNR                                    AS material,
    mk.MAKTX                                   AS material_desc,
    i.MATKL                                    AS material_group,
    i.WERKS                                    AS plant,
    i.PRCTR                                    AS profit_center,
    i.VKBUR                                    AS sales_office,
    i.VKGRP                                    AS sales_group,
    i.AUBEL                                    AS sales_order,
    i.VGBEL                                    AS delivery_doc,
    i.FKIMG                                    AS billed_qty,
    i.VRKME                                    AS sales_unit,
    h.WAERK                                    AS currency,
    i.NETWR                                    AS net_value,
    i.MWSBP                                    AS tax_amount,
    i.WAVWR                                    AS cost_value,
    (i.NETWR - i.WAVWR)                        AS margin_amount,
    kn.REGIO                                   AS customer_region,
    pw.REGIO                                   AS supplier_region,
    CASE WHEN pw.REGIO IS NULL OR kn.REGIO IS NULL OR pw.REGIO='' OR kn.REGIO='' THEN NULL
         WHEN pw.REGIO <> kn.REGIO THEN TRUE
         ELSE FALSE END                        AS is_interstate
FROM VBRK h
JOIN VBRP i
     ON i.tenant_id=h.tenant_id AND i.VBELN=h.VBELN
LEFT JOIN KNA1 kn
     ON kn.tenant_id=h.tenant_id AND kn.KUNNR=h.KUNAG
LEFT JOIN T001W pw
     ON pw.tenant_id=h.tenant_id AND pw.WERKS=i.WERKS
LEFT JOIN MAKT mk
     ON mk.tenant_id=h.tenant_id AND mk.MATNR=i.MATNR AND mk.SPRAS='E'
WHERE (h.FKSTO IS NULL OR h.FKSTO <> 'X');;

-- mv_sd_credit_exposure
CREATE MATERIALIZED VIEW `mv_sd_credit_exposure` (`tenant_id`, `customer`, `customer_name`, `credit_control_area`, `credit_limit`, `receivables`, `special_liabilities`, `total_exposure`, `available_credit`, `risk_category`, `last_review_date`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `customer`) BUCKETS 8 
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    k.tenant_id,
    k.KUNNR                                    AS customer,
    kn.NAME1                                   AS customer_name,
    k.KKBER                                    AS credit_control_area,
    k.KLIMK                                    AS credit_limit,
    k.SKFOR                                    AS receivables,
    k.SSOBL                                    AS special_liabilities,
    (COALESCE(k.SKFOR,0) + COALESCE(k.SSOBL,0))                       AS total_exposure,
    (COALESCE(k.KLIMK,0) - COALESCE(k.SKFOR,0) - COALESCE(k.SSOBL,0)) AS available_credit,
    k.CTLPC                                    AS risk_category,
    k.DTREV                                    AS last_review_date
FROM KNKK k
LEFT JOIN KNA1 kn
     ON kn.tenant_id=k.tenant_id AND kn.KUNNR=k.KUNNR;;

-- mv_sd_delivery_flat
CREATE MATERIALIZED VIEW `mv_sd_delivery_flat` (`tenant_id`, `delivery`, `item`, `created_on`, `delivery_type`, `ship_point`, `sales_org`, `delivery_date`, `planned_gi_date`, `actual_gi_date`, `ship_to`, `sold_to`, `customer_name`, `material`, `material_desc`, `plant`, `storage_location`, `batch`, `sales_order`, `sales_order_item`, `delivery_qty`, `base_unit`, `goods_movement_status`, `route`, `means_of_transport`, `external_delivery`, `gross_weight`, `net_weight`, `weight_unit`, `volume`, `num_packages`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `ship_point`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    h.tenant_id,
    h.VBELN                                    AS delivery,
    i.POSNR                                    AS item,
    h.ERDAT                                    AS created_on,
    h.LFART                                    AS delivery_type,
    h.VSTEL                                    AS ship_point,
    h.VKORG                                    AS sales_org,
    h.LFDAT                                    AS delivery_date,
    h.WADAT                                    AS planned_gi_date,
    h.WADAT_IST                                AS actual_gi_date,
    h.KUNNR                                    AS ship_to,
    h.KUNAG                                    AS sold_to,
    kn.NAME1                                   AS customer_name,
    i.MATNR                                    AS material,
    mk.MAKTX                                   AS material_desc,
    i.WERKS                                    AS plant,
    i.LGORT                                    AS storage_location,
    i.CHARG                                    AS batch,
    i.VGBEL                                    AS sales_order,
    i.VGPOS                                    AS sales_order_item,
    i.LFIMG                                    AS delivery_qty,
    i.MEINS                                    AS base_unit,
    h.WBSTK                                    AS goods_movement_status,
    h.ROUTE                                    AS route,
    h.TRAID                                    AS means_of_transport,
    h.LIFEX                                    AS external_delivery,
    h.BTGEW                                    AS gross_weight,
    h.NTGEW                                    AS net_weight,
    h.GEWEI                                    AS weight_unit,
    h.VOLUM                                    AS volume,
    h.ANZPK                                    AS num_packages
FROM LIKP h
JOIN LIPS i
     ON i.tenant_id=h.tenant_id AND i.VBELN=h.VBELN
LEFT JOIN KNA1 kn
     ON kn.tenant_id=h.tenant_id AND kn.KUNNR=h.KUNNR
LEFT JOIN MAKT mk
     ON mk.tenant_id=h.tenant_id AND mk.MATNR=i.MATNR AND mk.SPRAS='E';;

-- mv_sd_delivery_performance
CREATE MATERIALIZED VIEW `mv_sd_delivery_performance` (`tenant_id`, `delivery`, `item`, `ship_point`, `sales_org`, `planned_gi_date`, `actual_gi_date`, `gi_delay_days`, `on_time_flag`, `material`, `plant`, `delivery_qty`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `ship_point`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    h.tenant_id,
    h.VBELN                                    AS delivery,
    i.POSNR                                    AS item,
    h.VSTEL                                    AS ship_point,
    h.VKORG                                    AS sales_org,
    h.WADAT                                    AS planned_gi_date,
    h.WADAT_IST                                AS actual_gi_date,
    DATEDIFF(h.WADAT_IST, h.WADAT)             AS gi_delay_days,
    CASE WHEN h.WADAT_IST IS NOT NULL AND h.WADAT_IST <= h.WADAT THEN 1 ELSE 0 END AS on_time_flag,
    i.MATNR                                    AS material,
    i.WERKS                                    AS plant,
    i.LFIMG                                    AS delivery_qty
FROM LIKP h
JOIN LIPS i
     ON i.tenant_id=h.tenant_id AND i.VBELN=h.VBELN;;

-- mv_sd_open_credit_notes
CREATE MATERIALIZED VIEW `mv_sd_open_credit_notes` (`tenant_id`, `billing_doc`, `item`, `billing_date`, `billing_type`, `doc_category`, `sales_org`, `company_code`, `customer`, `customer_name`, `material`, `credit_qty`, `currency`, `credit_value`, `tax_amount`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `sales_org`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    h.tenant_id,
    h.VBELN                                    AS billing_doc,
    i.POSNR                                    AS item,
    h.FKDAT                                    AS billing_date,
    h.FKART                                    AS billing_type,
    h.VBTYP                                    AS doc_category,
    h.VKORG                                    AS sales_org,
    h.BUKRS                                    AS company_code,
    h.KUNAG                                    AS customer,
    kn.NAME1                                   AS customer_name,
    i.MATNR                                    AS material,
    i.FKIMG                                    AS credit_qty,
    h.WAERK                                    AS currency,
    i.NETWR                                    AS credit_value,
    i.MWSBP                                    AS tax_amount
FROM VBRK h
JOIN VBRP i
     ON i.tenant_id=h.tenant_id AND i.VBELN=h.VBELN
LEFT JOIN KNA1 kn
     ON kn.tenant_id=h.tenant_id AND kn.KUNNR=h.KUNAG
WHERE h.VBTYP = 'O'                              -- credit memo
  AND (h.FKSTO IS NULL OR h.FKSTO <> 'X');;

-- mv_sd_open_orders_backlog
CREATE MATERIALIZED VIEW `mv_sd_open_orders_backlog` (`tenant_id`, `sales_order`, `item`, `created_on`, `sales_org`, `sold_to`, `material`, `plant`, `order_qty`, `sales_unit`, `net_value`, `currency`, `delivery_status`, `overall_status`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `sales_org`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    h.tenant_id,
    h.VBELN                                    AS sales_order,
    i.POSNR                                    AS item,
    h.ERDAT                                    AS created_on,
    h.VKORG                                    AS sales_org,
    h.KUNNR                                    AS sold_to,
    i.MATNR                                    AS material,
    i.WERKS                                    AS plant,
    i.KWMENG                                   AS order_qty,
    i.VRKME                                    AS sales_unit,
    i.NETWR                                    AS net_value,
    h.WAERK                                    AS currency,
    i.LFSTA                                    AS delivery_status,
    i.GBSTA                                    AS overall_status
FROM VBAK h
JOIN VBAP i
     ON i.tenant_id=h.tenant_id AND i.VBELN=h.VBELN
WHERE (i.ABGRU IS NULL OR i.ABGRU='')          -- not rejected
  AND (i.LFSTA IS NULL OR i.LFSTA <> 'C');;

-- mv_sd_partner_addresses
CREATE MATERIALIZED VIEW `mv_sd_partner_addresses` (`tenant_id`, `sales_doc`, `item`, `partner_function`, `customer`, `customer_name`, `vendor`, `personnel_no`, `address_no`, `country`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `sales_doc`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 4 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    p.tenant_id,
    p.VBELN                                    AS sales_doc,
    p.POSNR                                    AS item,
    p.PARVW                                    AS partner_function,
    p.KUNNR                                    AS customer,
    kn.NAME1                                   AS customer_name,
    p.LIFNR                                    AS vendor,
    p.PERNR                                    AS personnel_no,
    p.ADRNR                                    AS address_no,
    p.LAND1                                    AS country
FROM VBPA p
LEFT JOIN KNA1 kn
     ON kn.tenant_id=p.tenant_id AND kn.KUNNR=p.KUNNR;;

-- mv_sd_rejection_analysis
CREATE MATERIALIZED VIEW `mv_sd_rejection_analysis` (`tenant_id`, `created_on`, `sales_org`, `rejection_reason`, `material`, `material_group`, `customer`, `rejected_value`, `rejected_qty`, `rejected_item_count`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `sales_org`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    h.tenant_id,
    h.ERDAT                                    AS created_on,
    h.VKORG                                    AS sales_org,
    i.ABGRU                                    AS rejection_reason,
    i.MATNR                                    AS material,
    i.MATKL                                    AS material_group,
    h.KUNNR                                    AS customer,
    SUM(i.NETWR)                               AS rejected_value,
    SUM(i.KWMENG)                              AS rejected_qty,
    COUNT(*)                                   AS rejected_item_count
FROM VBAK h
JOIN VBAP i
     ON i.tenant_id=h.tenant_id AND i.VBELN=h.VBELN
WHERE i.ABGRU IS NOT NULL AND i.ABGRU <> ''
GROUP BY h.tenant_id, h.ERDAT, h.VKORG, i.ABGRU, i.MATNR, i.MATKL, h.KUNNR;;

-- mv_sd_sales_daily_agg
CREATE MATERIALIZED VIEW `mv_sd_sales_daily_agg` (`tenant_id`, `billing_date`, `sales_org`, `distribution_channel`, `customer`, `material`, `plant`, `currency`, `net_revenue`, `tax_amount`, `cost_value`, `margin_amount`, `billed_qty`, `billing_doc_count`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `sales_org`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 30 MINUTE)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"enable_query_rewrite" = "FALSE",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    h.tenant_id,
    h.FKDAT                                    AS billing_date,
    h.VKORG                                    AS sales_org,
    h.VTWEG                                    AS distribution_channel,
    h.KUNAG                                    AS customer,
    i.MATNR                                    AS material,
    i.WERKS                                    AS plant,
    h.WAERK                                    AS currency,
    SUM(i.NETWR)                               AS net_revenue,
    SUM(i.MWSBP)                               AS tax_amount,
    SUM(i.WAVWR)                               AS cost_value,
    SUM(i.NETWR - i.WAVWR)                     AS margin_amount,
    SUM(i.FKIMG)                               AS billed_qty,
    COUNT(DISTINCT h.VBELN)                    AS billing_doc_count
FROM VBRK h
JOIN VBRP i
     ON i.tenant_id=h.tenant_id AND i.VBELN=h.VBELN
WHERE (h.FKSTO IS NULL OR h.FKSTO <> 'X')
GROUP BY h.tenant_id, h.FKDAT, h.VKORG, h.VTWEG, h.KUNAG, i.MATNR, i.WERKS, h.WAERK;;

-- mv_sd_sales_order_flat
CREATE MATERIALIZED VIEW `mv_sd_sales_order_flat` (`tenant_id`, `sales_order`, `item`, `created_on`, `document_date`, `order_type`, `sales_org`, `distribution_channel`, `division`, `sales_office`, `sales_group`, `sold_to`, `sold_to_name`, `material`, `material_desc`, `material_group`, `plant`, `item_category`, `rejection_reason`, `po_number`, `customer_group`, `order_qty`, `sales_unit`, `currency`, `net_value`, `cost_value`, `overall_status`, `delivery_status`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `sales_org`) BUCKETS 32 
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    h.tenant_id,
    h.VBELN                                    AS sales_order,
    i.POSNR                                    AS item,
    h.ERDAT                                    AS created_on,
    h.AUDAT                                    AS document_date,
    h.AUART                                    AS order_type,
    h.VKORG                                    AS sales_org,
    h.VTWEG                                    AS distribution_channel,
    h.SPART                                    AS division,
    h.VKBUR                                    AS sales_office,
    h.VKGRP                                    AS sales_group,
    h.KUNNR                                    AS sold_to,
    kn.NAME1                                   AS sold_to_name,
    i.MATNR                                    AS material,
    mk.MAKTX                                   AS material_desc,
    i.MATKL                                    AS material_group,
    i.WERKS                                    AS plant,
    i.PSTYV                                    AS item_category,
    i.ABGRU                                    AS rejection_reason,
    COALESCE(bd.BSTKD, bdh.BSTKD)              AS po_number,
    COALESCE(bd.KDGRP, bdh.KDGRP)             AS customer_group,
    i.KWMENG                                   AS order_qty,
    i.VRKME                                    AS sales_unit,
    h.WAERK                                    AS currency,
    i.NETWR                                    AS net_value,
    i.WAVWR                                    AS cost_value,
    i.GBSTA                                    AS overall_status,
    i.LFSTA                                    AS delivery_status
FROM VBAK h
JOIN VBAP i
     ON i.tenant_id=h.tenant_id AND i.VBELN=h.VBELN
LEFT JOIN VBKD bd
     ON bd.tenant_id=h.tenant_id AND bd.VBELN=i.VBELN AND bd.POSNR=i.POSNR
LEFT JOIN VBKD bdh
     ON bdh.tenant_id=h.tenant_id AND bdh.VBELN=i.VBELN AND bdh.POSNR='000000'
LEFT JOIN KNA1 kn
     ON kn.tenant_id=h.tenant_id AND kn.KUNNR=h.KUNNR
LEFT JOIN MAKT mk
     ON mk.tenant_id=h.tenant_id AND mk.MATNR=i.MATNR AND mk.SPRAS='E';;

-- mv_status_duration
CREATE MATERIALIZED VIEW `mv_status_duration` (`tenant_id`, `object_no`, `status_code`, `status_short_text`, `status_inactive`, `status_from_date`, `changed_by`, `status_to_date`, `days_in_status`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `object_no`) BUCKETS 32 
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    j.tenant_id,
    j.OBJNR                                    AS object_no,
    j.STAT                                     AS status_code,
    t.TXT04                                    AS status_short_text,
    j.INACT                                    AS status_inactive,
    j.UDATE                                    AS status_from_date,
    j.USNAM                                    AS changed_by,
    LEAD(j.UDATE) OVER (PARTITION BY j.tenant_id, j.OBJNR, j.STAT ORDER BY j.UDATE, j.CHGNR) AS status_to_date,
    DATEDIFF(
        LEAD(j.UDATE) OVER (PARTITION BY j.tenant_id, j.OBJNR, j.STAT ORDER BY j.UDATE, j.CHGNR),
        j.UDATE)                               AS days_in_status
FROM JCDS j
LEFT JOIN TJ02T t
     ON t.tenant_id=j.tenant_id AND t.ISTAT=j.STAT AND t.SPRAS='E';;

-- mv_x_billing_true_margin
CREATE MATERIALIZED VIEW `mv_x_billing_true_margin` (`tenant_id`, `billing_month`, `sales_org`, `sold_to`, `customer_name`, `material`, `material_desc`, `currency`, `net_revenue`, `cost_of_goods`, `margin_amount`, `billed_qty`, `margin_pct`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `sold_to`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    b.tenant_id,
    date_trunc('month', b.billing_date)        AS billing_month,
    b.sales_org                                AS sales_org,
    b.sold_to                                  AS sold_to,
    b.customer_name                            AS customer_name,
    b.material                                 AS material,
    b.material_desc                            AS material_desc,
    b.currency                                 AS currency,
    SUM(b.net_value)                           AS net_revenue,
    SUM(b.cost_value)                          AS cost_of_goods,
    SUM(b.margin_amount)                       AS margin_amount,
    SUM(b.billed_qty)                          AS billed_qty,
    CASE WHEN SUM(b.net_value) <> 0
         THEN SUM(b.margin_amount) / SUM(b.net_value)
         ELSE NULL END                         AS margin_pct
FROM mv_sd_billing_flat b
GROUP BY b.tenant_id, date_trunc('month', b.billing_date), b.sales_org,
         b.sold_to, b.customer_name, b.material, b.material_desc, b.currency;;

-- mv_x_customer_360
CREATE MATERIALIZED VIEW `mv_x_customer_360` (`tenant_id`, `customer`, `customer_name`, `country`, `city`, `billed_net_amount`, `billing_doc_count`, `last_billing_date`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `customer`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 6 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    k.tenant_id,
    k.KUNNR                                    AS customer,
    k.NAME1                                   AS customer_name,
    k.LAND1                                    AS country,
    k.ORT01                                    AS city,
    COALESCE(b.billed_net, 0)                  AS billed_net_amount,
    COALESCE(b.billing_docs, 0)                AS billing_doc_count,
    COALESCE(b.last_billing_date, NULL)        AS last_billing_date
FROM KNA1 k
LEFT JOIN (
    SELECT h.tenant_id, h.KUNAG AS kunnr,
           SUM(i.NETWR) AS billed_net,
           COUNT(DISTINCT h.VBELN) AS billing_docs,
           MAX(h.FKDAT) AS last_billing_date
    FROM VBRK h JOIN VBRP i
      ON i.tenant_id=h.tenant_id AND i.VBELN=h.VBELN
    WHERE (h.FKSTO IS NULL OR h.FKSTO <> 'X')
    GROUP BY h.tenant_id, h.KUNAG
) b ON b.tenant_id=k.tenant_id AND b.kunnr=k.KUNNR;;

-- mv_x_material_360
CREATE MATERIALIZED VIEW `mv_x_material_360` (`tenant_id`, `material`, `material_desc`, `material_type`, `material_group`, `base_unit`, `deletion_flag`, `total_stock_value`, `total_stock_qty`, `sold_qty_lifetime`, `sold_net_lifetime`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `material`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 6 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    m.tenant_id,
    m.MATNR                                    AS material,
    mk.MAKTX                                   AS material_desc,
    m.MTART                                    AS material_type,
    m.MATKL                                    AS material_group,
    m.MEINS                                    AS base_unit,
    m.LVORM                                    AS deletion_flag,
    COALESCE(val.total_value, 0)               AS total_stock_value,
    COALESCE(stk.total_qty, 0)                 AS total_stock_qty,
    COALESCE(sal.sold_qty, 0)                  AS sold_qty_lifetime,
    COALESCE(sal.sold_net, 0)                  AS sold_net_lifetime
FROM MARA m
LEFT JOIN MAKT mk ON mk.tenant_id=m.tenant_id AND mk.MATNR=m.MATNR AND mk.SPRAS='E'
LEFT JOIN (
    SELECT tenant_id, MATNR, SUM(SALK3) AS total_value
    FROM MBEW GROUP BY tenant_id, MATNR
) val ON val.tenant_id=m.tenant_id AND val.MATNR=m.MATNR
LEFT JOIN (
    SELECT tenant_id, MATNR,
           SUM(COALESCE(LABST,0)+COALESCE(INSME,0)+COALESCE(SPEME,0)) AS total_qty
    FROM MARD GROUP BY tenant_id, MATNR
) stk ON stk.tenant_id=m.tenant_id AND stk.MATNR=m.MATNR
LEFT JOIN (
    SELECT i.tenant_id, i.MATNR,
           SUM(i.FKIMG) AS sold_qty, SUM(i.NETWR) AS sold_net
    FROM VBRP i GROUP BY i.tenant_id, i.MATNR
) sal ON sal.tenant_id=m.tenant_id AND sal.MATNR=m.MATNR;;

-- mv_x_stock_coverage
CREATE MATERIALIZED VIEW `mv_x_stock_coverage` (`tenant_id`, `material`, `material_desc`, `plant`, `total_stock_qty`, `issue_qty_90d`, `avg_daily_issue`, `coverage_days`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `plant`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    s.tenant_id,
    s.MATNR                                    AS material,
    mk.MAKTX                                   AS material_desc,
    s.WERKS                                    AS plant,
    s.total_stock_qty                          AS total_stock_qty,
    COALESCE(iss.issue_qty_90d, 0)             AS issue_qty_90d,
    (COALESCE(iss.issue_qty_90d,0) / 90.0)     AS avg_daily_issue,
    CASE WHEN COALESCE(iss.issue_qty_90d,0) > 0
         THEN s.total_stock_qty / (iss.issue_qty_90d / 90.0)
         ELSE NULL END                         AS coverage_days
FROM (
    SELECT tenant_id, MATNR, WERKS,
           SUM(COALESCE(LABST,0)+COALESCE(INSME,0)+COALESCE(SPEME,0)+COALESCE(EINME,0)) AS total_stock_qty
    FROM MARD GROUP BY tenant_id, MATNR, WERKS
) s
LEFT JOIN (
    SELECT tenant_id, MATNR, WERKS, SUM(MENGE) AS issue_qty_90d
    FROM MATDOC
    WHERE SHKZG='H'
      AND BUDAT >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
      AND (CANCELLED IS NULL OR CANCELLED <> 'X')
    GROUP BY tenant_id, MATNR, WERKS
) iss ON iss.tenant_id=s.tenant_id AND iss.MATNR=s.MATNR AND iss.WERKS=s.WERKS
LEFT JOIN MAKT mk
     ON mk.tenant_id=s.tenant_id AND mk.MATNR=s.MATNR AND mk.SPRAS='E';;

-- mv_x_vendor_360
CREATE MATERIALIZED VIEW `mv_x_vendor_360` (`tenant_id`, `vendor`, `vendor_name`, `vendor_group`, `country`, `region`, `city`, `po_net_value`, `po_count`, `gr_value`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `vendor`) BUCKETS 16 
REFRESH ASYNC EVERY(INTERVAL 6 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    l.tenant_id,
    l.LIFNR                                    AS vendor,
    l.NAME1                                   AS vendor_name,
    l.KTOKK                                    AS vendor_group,
    l.LAND1                                    AS country,
    l.REGIO                                    AS region,
    l.ORT01                                    AS city,
    COALESCE(po.po_net, 0)                     AS po_net_value,
    COALESCE(po.po_count, 0)                   AS po_count,
    COALESCE(gr.gr_value, 0)                   AS gr_value
FROM LFA1 l
LEFT JOIN (
    SELECT h.tenant_id, h.LIFNR, SUM(i.NETWR) AS po_net,
           COUNT(DISTINCT h.EBELN) AS po_count
    FROM EKKO h JOIN EKPO i
      ON i.tenant_id=h.tenant_id AND i.EBELN=h.EBELN
    GROUP BY h.tenant_id, h.LIFNR
) po ON po.tenant_id=l.tenant_id AND po.LIFNR=l.LIFNR
LEFT JOIN (
    SELECT h.tenant_id, h.LIFNR,
           SUM(CASE WHEN b.SHKZG='S' THEN b.DMBTR ELSE -b.DMBTR END) AS gr_value
    FROM EKBE b JOIN EKKO h
      ON h.tenant_id=b.tenant_id AND h.EBELN=b.EBELN
    WHERE b.VGABE='1'
    GROUP BY h.tenant_id, h.LIFNR
) gr ON gr.tenant_id=l.tenant_id AND gr.LIFNR=l.LIFNR;;


-- default_catalog.tatva_datalack.vw_ai_control_center source

CREATE VIEW `vw_ai_control_center` (`tenant_id`,
`domain`,
`entity_id`,
`entity_name`,
`status`,
`severity`,
`metric_value`,
`metric_label`,
`reason`,
`recommended_action`) SECURITY NONE AS
SELECT
    tenant_id,
    'CUSTOMER' AS domain,
    customer AS entity_id,
    customer_name AS entity_name,
    CASE
        segment
      WHEN 'AT_RISK_STOPPED' THEN 'CRITICAL'
        WHEN 'DECLINING' THEN 'RISK'
        WHEN 'CREDIT_BLOCKED' THEN 'RISK'
        WHEN 'LOW_MARGIN' THEN 'WATCH'
        ELSE 'GOOD'
    END AS status,
    CASE
        segment WHEN 'AT_RISK_STOPPED' THEN 4
        WHEN 'DECLINING' THEN 3
        WHEN 'CREDIT_BLOCKED' THEN 3
        WHEN 'LOW_MARGIN' THEN 2
        ELSE 1
    END AS severity,
    rev_12m AS metric_value,
    'Revenue last 12m' AS metric_label,
    reason AS reason,
    CASE
        segment
      WHEN 'AT_RISK_STOPPED' THEN 'Win-back outreach within 7 days, check open returns/complaints'
        WHEN 'DECLINING' THEN 'Account review call, investigate competitor or quality issue'
        WHEN 'CREDIT_BLOCKED' THEN 'Clear overdue with AR before next order, review credit limit'
        WHEN 'LOW_MARGIN' THEN 'Renegotiate pricing/discount, review product mix'
        WHEN 'GROWING_LOYAL' THEN 'Protect & grow: upsell / cross-sell'
        ELSE 'Maintain relationship'
    END AS recommended_action
FROM
    mv_ai_customer_health
UNION ALL
-- VENDOR
SELECT
    tenant_id,
    'VENDOR' AS domain,
    vendor AS entity_id,
    vendor_name AS entity_name,
    CASE
        WHEN max_days_late > 15 THEN 'CRITICAL'
        WHEN overdue_items > 0 THEN 'RISK'
        ELSE 'GOOD'
    END AS status,
    CASE
        WHEN max_days_late > 15 THEN 4
        WHEN overdue_items > 0 THEN 3
        ELSE 1
    END AS severity,
    overdue_value AS metric_value,
    'Overdue PO value' AS metric_label,
    CASE
        WHEN overdue_items > 0
         THEN CONCAT(CAST(overdue_items AS STRING), ' overdue lines, worst ',
                     CAST(max_days_late AS STRING), ' days late')
        ELSE 'All open POs on schedule'
    END AS reason,
    CASE
        WHEN max_days_late > 15 THEN 'Escalate to vendor mgmt, activate backup source, expedite'
        WHEN overdue_items > 0 THEN 'Chase delivery, confirm new committed date'
        ELSE 'No action'
    END AS recommended_action
FROM
    mv_ai_vendor_risk
UNION ALL
-- INVENTORY
SELECT
    tenant_id,
    'INVENTORY' AS domain,
    CONCAT(material, '@', plant) AS entity_id,
    material_desc AS entity_name,
    CASE
        stock_state
      WHEN 'STOCKOUT_IMMINENT' THEN 'CRITICAL'
        WHEN 'DEAD_STOCK' THEN 'RISK'
        WHEN 'STOCKOUT_RISK' THEN 'RISK'
        WHEN 'OVERSTOCK' THEN 'WATCH'
        ELSE 'GOOD'
    END AS status,
    CASE
        stock_state WHEN 'STOCKOUT_IMMINENT' THEN 4
        WHEN 'DEAD_STOCK' THEN 3
        WHEN 'STOCKOUT_RISK' THEN 3
        WHEN 'OVERSTOCK' THEN 2
        ELSE 1
    END AS severity,
    coverage_days AS metric_value,
    'Days of cover' AS metric_label,
    CASE
        stock_state
      WHEN 'DEAD_STOCK' THEN 'No consumption in 90 days, stock still held'
        WHEN 'STOCKOUT_IMMINENT' THEN CONCAT('Only ', CAST(ROUND(coverage_days) AS STRING), ' days of cover')
        WHEN 'STOCKOUT_RISK' THEN CONCAT(CAST(ROUND(coverage_days) AS STRING), ' days of cover')
        WHEN 'OVERSTOCK' THEN 'Over a year of cover on hand'
        ELSE 'Coverage healthy'
    END AS reason,
    CASE
        stock_state
      WHEN 'DEAD_STOCK' THEN 'Stop replenishment, liquidate/return, review MRP'
        WHEN 'STOCKOUT_IMMINENT' THEN 'Expedite open PO/production now, raise safety stock'
        WHEN 'STOCKOUT_RISK' THEN 'Review reorder point, confirm inbound supply'
        WHEN 'OVERSTOCK' THEN 'Reduce reorder qty, review forecast'
        ELSE 'No action'
    END AS recommended_action
FROM
    mv_ai_inventory_risk
WHERE
    stock_state <> 'HEALTHY'
UNION ALL
-- PRODUCTION
SELECT
    tenant_id,
    'PRODUCTION' AS domain,
    production_order AS entity_id,
    material AS entity_name,
    CASE
        WHEN days_late > 7 THEN 'CRITICAL'
        WHEN days_late > 0 THEN 'RISK'
        WHEN yield_var_pct < -0.10 THEN 'WATCH'
        ELSE 'GOOD'
    END AS status,
    CASE
        WHEN days_late > 7 THEN 4
        WHEN days_late > 0 THEN 3
        WHEN yield_var_pct < -0.10 THEN 2
        ELSE 1
    END AS severity,
    open_qty AS metric_value,
    'Open quantity' AS metric_label,
    CASE
        WHEN days_late > 0 THEN CONCAT('Order ', CAST(days_late AS STRING), ' days past finish date')
        WHEN yield_var_pct < -0.10 THEN 'Yield short of plan by >10%'
        ELSE 'On track'
    END AS reason,
    CASE
        WHEN days_late > 7 THEN 'Re-sequence on line, check component shortage, expedite'
        WHEN days_late > 0 THEN 'Confirm new finish date, check capacity'
        WHEN yield_var_pct < -0.10 THEN 'Investigate scrap cause at work center, QM check'
        ELSE 'No action'
    END AS recommended_action
FROM
    mv_ai_production_risk
UNION ALL
-- CASH / AR
SELECT
    tenant_id,
    'CASH_AR' AS domain,
    customer AS entity_id,
    customer_name AS entity_name,
    CASE
        WHEN bucket_90plus > 0 THEN 'CRITICAL'
        WHEN bucket_61_90 > 0 THEN 'RISK'
        WHEN bucket_31_60 > 0 THEN 'WATCH'
        ELSE 'GOOD'
    END AS status,
    CASE
        WHEN bucket_90plus > 0 THEN 4
        WHEN bucket_61_90 > 0 THEN 3
        WHEN bucket_31_60 > 0 THEN 2
        ELSE 1
    END AS severity,
    total_open AS metric_value,
    'Open receivables' AS metric_label,
    CONCAT('Max ', CAST(max_days_overdue AS STRING), ' days overdue') AS reason,
    CASE
        WHEN bucket_90plus > 0 THEN 'Collections call today, consider delivery block / dunning'
        WHEN bucket_61_90 > 0 THEN 'Send reminder, confirm payment date'
        WHEN bucket_31_60 > 0 THEN 'Monitor, gentle reminder'
        ELSE 'No action'
    END AS recommended_action
FROM
    mv_ai_ar_risk;


CREATE MATERIALIZED VIEW `mv_fi_ar_cleared` (
  `tenant_id`, `company_code`, `customer`, `customer_name`, `accounting_doc`,
  `fiscal_year`, `line_no`, `posting_date`, `baseline_date`, `payment_terms`,
  `clearing_doc`, `clearing_date`, `clearing_year`, `cleared_amount`, `days_to_pay`,
  `billing_doc`
)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `company_code`) BUCKETS 16
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
  "replicated_storage" = "true",
  "replication_num"    = "1",
  "compression"        = "ZSTD",
  "storage_medium"     = "HDD"
)
AS SELECT
    l.tenant_id,
    l.BUKRS                                              AS company_code,
    l.KUNNR                                              AS customer,
    kn.NAME1                                             AS customer_name,
    l.BELNR                                              AS accounting_doc,
    l.GJAHR                                              AS fiscal_year,
    l.BUZEI                                              AS line_no,
    h.BUDAT                                              AS posting_date,
    l.ZFBDT                                              AS baseline_date,
    l.ZTERM                                              AS payment_terms,
    l.AUGBL                                              AS clearing_doc,
    l.AUGDT                                              AS clearing_date,
    l.AUGGJ                                              AS clearing_year,
    CASE WHEN l.SHKZG='S' THEN l.DMBTR ELSE -l.DMBTR END AS cleared_amount,
    DATEDIFF(
        STR_TO_DATE(NULLIF(l.AUGDT,''), '%Y%m%d'),
        STR_TO_DATE(NULLIF(l.ZFBDT,''), '%Y%m%d')
    )                                                    AS days_to_pay,
    COALESCE(
      NULLIF(l.VBELN, ''),
      CASE WHEN l.AWTYP = 'VBRK' THEN SUBSTRING(l.AWKEY, 1, 10) END
    )                                                    AS billing_doc
FROM BSEG l
JOIN BKPF h
     ON h.tenant_id=l.tenant_id AND h.BUKRS=l.BUKRS AND h.BELNR=l.BELNR AND h.GJAHR=l.GJAHR
LEFT JOIN KNA1 kn
     ON kn.tenant_id=l.tenant_id AND kn.KUNNR=l.KUNNR
WHERE l.KOART='D'
  AND l.AUGBL IS NOT NULL AND l.AUGBL <> '';

-- mv_sd_pricing_conditions  (PDF SD: VBRK-KNUMV = KONV-KNUMV; KONV is now PRCD_ELEMENTS)
CREATE MATERIALIZED VIEW `mv_sd_pricing_conditions` (`tenant_id`, `billing_doc`, `item`, `billing_date`, `sales_org`, `sold_to`, `material`, `material_desc`, `condition_type`, `condition_step`, `condition_rate`, `condition_unit`, `condition_base`, `condition_value`, `currency`, `is_statistical`, `is_inactive`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `sales_org`) BUCKETS 32
REFRESH ASYNC EVERY(INTERVAL 2 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    c.tenant_id,
    h.VBELN                                    AS billing_doc,
    i.POSNR                                    AS item,
    h.FKDAT                                    AS billing_date,
    h.VKORG                                    AS sales_org,
    h.KUNAG                                    AS sold_to,
    i.MATNR                                    AS material,
    mk.MAKTX                                   AS material_desc,
    c.KSCHL                                    AS condition_type,
    c.STUNR                                    AS condition_step,
    c.KBETR                                    AS condition_rate,
    c.KMEIN                                    AS condition_unit,
    c.KAWRT                                    AS condition_base,
    c.KWERT                                    AS condition_value,
    c.WAERS                                    AS currency,
    c.KSTAT                                    AS is_statistical,
    c.KINAK                                    AS is_inactive
FROM PRCD_ELEMENTS c
JOIN VBRK h
     ON h.tenant_id=c.tenant_id AND h.KNUMV=c.KNUMV
JOIN VBRP i
     ON i.tenant_id=h.tenant_id AND i.VBELN=h.VBELN AND i.POSNR=c.KPOSN
LEFT JOIN MAKT mk
     ON mk.tenant_id=i.tenant_id AND mk.MATNR=i.MATNR AND mk.SPRAS='E'
WHERE (h.FKSTO IS NULL OR h.FKSTO <> 'X')
  AND (c.KINAK IS NULL OR c.KINAK = '');;

-- mv_mm_purchase_requisitions  (PDF MM Purchasing: EBAN; follow-on PO via EBAN.EBELN)
CREATE MATERIALIZED VIEW `mv_mm_purchase_requisitions` (`tenant_id`, `purchase_req`, `item`, `pr_type`, `created_on`, `requisitioner`, `purch_group`, `material`, `material_desc`, `material_group`, `plant`, `storage_location`, `req_qty`, `order_unit`, `requirement_date`, `delivery_date`, `valuation_price`, `price_unit`, `vendor`, `vendor_name`, `purchase_order`, `po_item`, `ordered_qty`, `open_qty`, `release_indicator`, `cost_center`, `gl_account`, `deletion_flag`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `purch_group`) BUCKETS 16
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    r.tenant_id,
    r.BANFN                                    AS purchase_req,
    r.BNFPO                                    AS item,
    r.BSART                                    AS pr_type,
    r.ERDAT                                    AS created_on,
    r.AFNAM                                    AS requisitioner,
    r.EKGRP                                    AS purch_group,
    r.MATNR                                    AS material,
    mk.MAKTX                                   AS material_desc,
    r.MATKL                                    AS material_group,
    r.WERKS                                    AS plant,
    r.LGORT                                    AS storage_location,
    r.MENGE                                    AS req_qty,
    r.MEINS                                    AS order_unit,
    r.BADAT                                    AS requirement_date,
    r.LFDAT                                    AS delivery_date,
    r.PREIS                                    AS valuation_price,
    r.PEINH                                    AS price_unit,
    r.LIFNR                                    AS vendor,
    lf.NAME1                                   AS vendor_name,
    r.EBELN                                    AS purchase_order,
    r.EBELP                                    AS po_item,
    r.BSMNG                                    AS ordered_qty,
    (r.MENGE - COALESCE(r.BSMNG,0))            AS open_qty,
    r.FRGKZ                                    AS release_indicator,
    r.KOSTL                                    AS cost_center,
    r.SAKTO                                    AS gl_account,
    r.LOEKZ                                    AS deletion_flag
FROM EBAN r
LEFT JOIN MAKT mk
     ON mk.tenant_id=r.tenant_id AND mk.MATNR=r.MATNR AND mk.SPRAS='E'
LEFT JOIN LFA1 lf
     ON lf.tenant_id=r.tenant_id AND lf.LIFNR=r.LIFNR
WHERE (r.LOEKZ IS NULL OR r.LOEKZ = '');;

-- mv_sd_schedule_lines  (PDF SD: VBEP schedule lines; VBEP-VBELN/POSNR = VBAP)
CREATE MATERIALIZED VIEW `mv_sd_schedule_lines` (`tenant_id`, `sales_order`, `item`, `schedule_line`, `schedule_category`, `request_delivery_date`, `material_avail_date`, `goods_issue_date`, `loading_date`, `order_qty`, `confirmed_qty`, `required_qty`, `sales_unit`, `delivery_block`, `material`, `material_desc`, `plant`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `sales_order`) BUCKETS 16
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    e.tenant_id,
    e.VBELN                                    AS sales_order,
    e.POSNR                                    AS item,
    e.ETENR                                    AS schedule_line,
    e.ETTYP                                    AS schedule_category,
    e.EDATU                                    AS request_delivery_date,
    e.MBDAT                                    AS material_avail_date,
    e.WADAT                                    AS goods_issue_date,
    e.LDDAT                                    AS loading_date,
    e.WMENG                                    AS order_qty,
    e.BMENG                                    AS confirmed_qty,
    e.LMENG                                    AS required_qty,
    e.VRKME                                    AS sales_unit,
    e.LIFSP                                    AS delivery_block,
    i.MATNR                                    AS material,
    mk.MAKTX                                   AS material_desc,
    i.WERKS                                    AS plant
FROM VBEP e
LEFT JOIN VBAP i
     ON i.tenant_id=e.tenant_id AND i.VBELN=e.VBELN AND i.POSNR=e.POSNR
LEFT JOIN MAKT mk
     ON mk.tenant_id=e.tenant_id AND mk.MATNR=i.MATNR AND mk.SPRAS='E';;

-- mv_mm_source_list  (PDF MM Purchasing: EORD approved source list)
CREATE MATERIALIZED VIEW `mv_mm_source_list` (`tenant_id`, `material`, `material_desc`, `plant`, `source_list_no`, `valid_from`, `valid_to`, `vendor`, `vendor_name`, `agreement`, `agreement_item`, `purch_org`, `fixed_vendor`, `blocked`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `plant`) BUCKETS 8
REFRESH ASYNC EVERY(INTERVAL 6 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    o.tenant_id,
    o.MATNR                                    AS material,
    mk.MAKTX                                   AS material_desc,
    o.WERKS                                    AS plant,
    o.ZEORD                                    AS source_list_no,
    o.VDATU                                    AS valid_from,
    o.BDATU                                    AS valid_to,
    o.LIFNR                                    AS vendor,
    lf.NAME1                                   AS vendor_name,
    o.EBELN                                    AS agreement,
    o.EBELP                                    AS agreement_item,
    o.EKORG                                    AS purch_org,
    o.FLIFN                                    AS fixed_vendor,
    o.NOTKZ                                    AS blocked
FROM EORD o
LEFT JOIN MAKT mk
     ON mk.tenant_id=o.tenant_id AND mk.MATNR=o.MATNR AND mk.SPRAS='E'
LEFT JOIN LFA1 lf
     ON lf.tenant_id=o.tenant_id AND lf.LIFNR=o.LIFNR;;

-- mv_mm_mrp_material  (MD04/MRP alternative: MARC planning parameters per material/plant;
--                      combine with StockOnHand + Open* supply/demand views for coverage)
CREATE MATERIALIZED VIEW `mv_mm_mrp_material` (`tenant_id`, `material`, `material_desc`, `material_group`, `plant`, `base_unit`, `mrp_type`, `mrp_controller`, `procurement_type`, `special_procurement`, `reorder_point`, `safety_stock`, `max_stock`, `min_lot_size`, `max_lot_size`, `rounding_value`, `planned_deliv_time`, `gr_processing_time`, `range_coverage_profile`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `plant`) BUCKETS 16
REFRESH ASYNC EVERY(INTERVAL 4 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    mc.tenant_id,
    mc.MATNR                                   AS material,
    mk.MAKTX                                   AS material_desc,
    ma.MATKL                                   AS material_group,
    mc.WERKS                                   AS plant,
    ma.MEINS                                   AS base_unit,
    mc.DISMM                                   AS mrp_type,
    mc.DISPO                                   AS mrp_controller,
    mc.BESKZ                                   AS procurement_type,
    mc.SOBSL                                   AS special_procurement,
    mc.MINBE                                   AS reorder_point,
    mc.EISBE                                   AS safety_stock,
    mc.MABST                                   AS max_stock,
    mc.BSTMI                                   AS min_lot_size,
    mc.BSTMA                                   AS max_lot_size,
    mc.BSTRF                                   AS rounding_value,
    mc.PLIFZ                                   AS planned_deliv_time,
    mc.WEBAZ                                   AS gr_processing_time,
    mc.RWPRO                                   AS range_coverage_profile
FROM MARC mc
LEFT JOIN MARA ma ON ma.tenant_id=mc.tenant_id AND ma.MATNR=mc.MATNR
LEFT JOIN MAKT mk ON mk.tenant_id=mc.tenant_id AND mk.MATNR=mc.MATNR AND mk.SPRAS='E';;    
-- mv_sd_customer_material_info — VD59 Customer-Material Info Record (from KNMT).
-- One row per sales-org × channel × customer × material: the customer's own
-- material number, delivery priority and ordering defaults. Filter tenant_id.
CREATE MATERIALIZED VIEW `mv_sd_customer_material_info` (
  `tenant_id`, `sales_org`, `distribution_channel`, `customer`, `customer_name`,
  `material`, `material_desc`, `customer_material_no`, `delivery_priority`,
  `partial_delivery_ind`, `max_partial_deliveries`, `min_delivery_qty`,
  `sales_unit`, `material_freight_group`, `deletion_flag`
)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `customer`) BUCKETS 16
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
  "replicated_storage" = "true",
  "replication_num"    = "1",
  "compression"        = "ZSTD",
  "storage_medium"     = "HDD"
)
AS
SELECT
    tenant_id,
    sales_org,
    distribution_channel,
    customer,
    customer_name,
    material,
    material_desc,
    customer_material_no,
    delivery_priority,
    partial_delivery_ind,
    max_partial_deliveries,
    min_delivery_qty,
    sales_unit,
    material_freight_group,
    deletion_flag
FROM (
    SELECT
        h.tenant_id                                AS tenant_id,
        h.vkorg                                    AS sales_org,
        h.vtweg                                    AS distribution_channel,
        h.kunnr                                    AS customer,
        kc.name1                                   AS customer_name,
        i.matnr                                    AS material,
        mk.maktx                                   AS material_desc,
        i.kdmat                                    AS customer_material_no,
        i.lprio                                    AS delivery_priority,
        i.kztlf                                    AS partial_delivery_ind,
        i.antlf                                    AS max_partial_deliveries,
        i.lfmng                                    AS min_delivery_qty,
        i.vrkme                                    AS sales_unit,
        i.mfrgr                                    AS material_freight_group,
        i.abgru                                    AS deletion_flag,
        ROW_NUMBER() OVER (
            PARTITION BY h.tenant_id, h.vkorg, h.vtweg, h.kunnr, i.matnr
            ORDER BY i.erdat DESC, i.vbeln DESC, i.posnr DESC
        ) AS rn
    FROM VBAP i
    JOIN VBAK h
        ON h.tenant_id = i.tenant_id AND h.vbeln = i.vbeln
    LEFT JOIN KNA1 kc
        ON kc.tenant_id = h.tenant_id AND kc.kunnr = h.kunnr
    LEFT JOIN MAKT mk
        ON mk.tenant_id = i.tenant_id AND mk.matnr = i.matnr AND mk.spras = 'E'
) t
WHERE rn = 1;

-- mv_mm_gr_ir_balance — GR/IR clearing balance (MB5S) from PO history EKBE.
-- One row per PO line: goods-received vs invoice-received quantity/value and the
-- open GR/IR balance (received but not yet invoiced). VGABE 1 = goods receipt,
-- 2 = invoice receipt; SHKZG S/H is the debit/credit sign. Filter tenant_id.
CREATE MATERIALIZED VIEW `mv_mm_gr_ir_balance` (`tenant_id`, `purchase_order`, `item`, `vendor`, `vendor_name`, `material`, `material_desc`, `plant`, `currency`, `gr_qty`, `gr_value`, `invoice_qty`, `invoice_value`, `balance_qty`, `balance_value`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `purchase_order`) BUCKETS 16
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    b.tenant_id,
    b.EBELN                                    AS purchase_order,
    b.EBELP                                    AS item,
    k.LIFNR                                    AS vendor,
    lf.NAME1                                   AS vendor_name,
    b.MATNR                                    AS material,
    mk.MAKTX                                   AS material_desc,
    b.WERKS                                    AS plant,
    b.WAERS                                    AS currency,
    SUM(CASE WHEN b.VGABE='1' THEN (CASE WHEN b.SHKZG='S' THEN b.MENGE ELSE -b.MENGE END) ELSE 0 END) AS gr_qty,
    SUM(CASE WHEN b.VGABE='1' THEN (CASE WHEN b.SHKZG='S' THEN b.DMBTR ELSE -b.DMBTR END) ELSE 0 END) AS gr_value,
    SUM(CASE WHEN b.VGABE='2' THEN (CASE WHEN b.SHKZG='S' THEN b.MENGE ELSE -b.MENGE END) ELSE 0 END) AS invoice_qty,
    SUM(CASE WHEN b.VGABE='2' THEN (CASE WHEN b.SHKZG='S' THEN b.DMBTR ELSE -b.DMBTR END) ELSE 0 END) AS invoice_value,
    SUM(CASE WHEN b.VGABE='1' THEN (CASE WHEN b.SHKZG='S' THEN b.MENGE ELSE -b.MENGE END)
             WHEN b.VGABE='2' THEN (CASE WHEN b.SHKZG='S' THEN -b.MENGE ELSE b.MENGE END) ELSE 0 END) AS balance_qty,
    SUM(CASE WHEN b.VGABE='1' THEN (CASE WHEN b.SHKZG='S' THEN b.DMBTR ELSE -b.DMBTR END)
             WHEN b.VGABE='2' THEN (CASE WHEN b.SHKZG='S' THEN -b.DMBTR ELSE b.DMBTR END) ELSE 0 END) AS balance_value
FROM EKBE b
LEFT JOIN EKKO k ON k.tenant_id=b.tenant_id AND k.EBELN=b.EBELN
LEFT JOIN LFA1 lf ON lf.tenant_id=b.tenant_id AND lf.LIFNR=k.LIFNR
LEFT JOIN MAKT mk ON mk.tenant_id=b.tenant_id AND mk.MATNR=b.MATNR AND mk.SPRAS='E'
WHERE b.VGABE IN ('1','2')
GROUP BY b.tenant_id, b.EBELN, b.EBELP, k.LIFNR, lf.NAME1, b.MATNR, mk.MAKTX, b.WERKS, b.WAERS;;

-- mv_mm_consignment_stock — Consignment / special stock with vendor (MB54) from MKOL.
-- One row per material × plant × batch × special-stock-indicator × vendor. Four
-- stock categories mirror StockOnHand. SOBKZ K = vendor consignment, O = RTP at
-- vendor. Filter tenant_id.
CREATE MATERIALIZED VIEW `mv_mm_consignment_stock` (`tenant_id`, `material`, `material_desc`, `plant`, `plant_name`, `batch`, `vendor`, `vendor_name`, `special_stock_ind`, `base_unit`, `material_group`, `unrestricted_qty`, `quality_inspection_qty`, `blocked_qty`, `restricted_qty`, `total_stock_qty`)
COMMENT "MATERIALIZED_VIEW"
DISTRIBUTED BY HASH(`tenant_id`, `plant`) BUCKETS 16
REFRESH ASYNC EVERY(INTERVAL 30 MINUTE)
PROPERTIES (
"replicated_storage" = "true",
"replication_num" = "1",
"compression" = "ZSTD",
"storage_medium" = "HDD"
)
AS SELECT
    c.tenant_id,
    c.MATNR                                    AS material,
    mk.MAKTX                                   AS material_desc,
    c.WERKS                                    AS plant,
    pl.NAME1                                   AS plant_name,
    c.CHARG                                    AS batch,
    c.LIFNR                                    AS vendor,
    lf.NAME1                                   AS vendor_name,
    c.SOBKZ                                    AS special_stock_ind,
    ma.MEINS                                   AS base_unit,
    ma.MATKL                                   AS material_group,
    c.SLABS                                    AS unrestricted_qty,
    c.SINSM                                    AS quality_inspection_qty,
    c.SSPEM                                    AS blocked_qty,
    c.SEINM                                    AS restricted_qty,
    (COALESCE(c.SLABS,0)+COALESCE(c.SINSM,0)+COALESCE(c.SSPEM,0)+COALESCE(c.SEINM,0)) AS total_stock_qty
FROM MKOL c
LEFT JOIN MARA ma ON ma.tenant_id=c.tenant_id AND ma.MATNR=c.MATNR
LEFT JOIN MAKT mk ON mk.tenant_id=c.tenant_id AND mk.MATNR=c.MATNR AND mk.SPRAS='E'
LEFT JOIN T001W pl ON pl.tenant_id=c.tenant_id AND pl.WERKS=c.WERKS
LEFT JOIN LFA1 lf ON lf.tenant_id=c.tenant_id AND lf.LIFNR=c.LIFNR;;
