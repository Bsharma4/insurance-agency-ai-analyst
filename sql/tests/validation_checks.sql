-- =====================================================================
-- Data validation checks. Every check returns (check_name, failures).
-- A healthy load returns failures = 0 on every row.
-- Run with: python src/build_database.py   (runs automatically after load)
-- =====================================================================

-- 1. Reconciliation: every staging row became exactly one fact row
SELECT 'fact row count equals staging row count' AS check_name,
       ABS((SELECT COUNT(*) FROM stg_agency_performance)
         - (SELECT COUNT(*) FROM fact_agency_product_performance)) AS failures

-- 2. Reconciliation: written premium total survives the load (to the cent)
UNION ALL
SELECT 'written premium total matches staging',
       CASE WHEN ABS((SELECT SUM(CAST(WRTN_PREM_AMT AS REAL)) FROM stg_agency_performance)
                   - (SELECT SUM(wrtn_prem_amt) FROM fact_agency_product_performance)) < 0.01
            THEN 0 ELSE 1 END

-- 3. Reconciliation: incurred losses total survives the load
UNION ALL
SELECT 'incurred losses total matches staging',
       CASE WHEN ABS((SELECT SUM(CAST(PRD_INCRD_LOSSES_AMT AS REAL)) FROM stg_agency_performance)
                   - (SELECT SUM(prd_incrd_losses_amt) FROM fact_agency_product_performance)) < 0.01
            THEN 0 ELSE 1 END

-- 4. Grain: no duplicate agency x product x state x year
UNION ALL
SELECT 'fact grain has no duplicates',
       COUNT(*)
FROM (SELECT 1 FROM fact_agency_product_performance
      GROUP BY agency_key, product_key, state_key, year_key
      HAVING COUNT(*) > 1)

-- 5-8. Referential integrity: no orphan foreign keys
UNION ALL
SELECT 'no orphan agency_key in fact',
       COUNT(*) FROM fact_agency_product_performance f
       LEFT JOIN dim_agency d ON d.agency_key = f.agency_key WHERE d.agency_key IS NULL
UNION ALL
SELECT 'no orphan product_key in fact',
       COUNT(*) FROM fact_agency_product_performance f
       LEFT JOIN dim_product d ON d.product_key = f.product_key WHERE d.product_key IS NULL
UNION ALL
SELECT 'no orphan state_key in fact',
       COUNT(*) FROM fact_agency_product_performance f
       LEFT JOIN dim_state d ON d.state_key = f.state_key WHERE d.state_key IS NULL
UNION ALL
SELECT 'no orphan year_key in fact',
       COUNT(*) FROM fact_agency_product_performance f
       LEFT JOIN dim_year d ON d.year_key = f.year_key WHERE d.year_key IS NULL
UNION ALL
SELECT 'no orphan agency_key in quote fact',
       COUNT(*) FROM fact_agency_quote_activity f
       LEFT JOIN dim_agency d ON d.agency_key = f.agency_key WHERE d.agency_key IS NULL

-- 9-11. Dimension completeness: one row per distinct natural key
UNION ALL
SELECT 'dim_agency has one row per source agency',
       ABS((SELECT COUNT(DISTINCT AGENCY_ID) FROM stg_agency_performance) - (SELECT COUNT(*) FROM dim_agency))
UNION ALL
SELECT 'dim_product has one row per source product',
       ABS((SELECT COUNT(DISTINCT PROD_ABBR) FROM stg_agency_performance) - (SELECT COUNT(*) FROM dim_product))
UNION ALL
SELECT 'every product code maps to exactly one product line',
       COUNT(*) FROM (SELECT PROD_ABBR FROM stg_agency_performance GROUP BY PROD_ABBR HAVING COUNT(DISTINCT PROD_LINE) > 1)

-- 12. Snapshot assumption: agency attributes never vary within an agency
UNION ALL
SELECT 'agency attributes constant per agency',
       COUNT(*)
FROM (SELECT AGENCY_ID FROM stg_agency_performance GROUP BY AGENCY_ID
      HAVING COUNT(DISTINCT PRIMARY_AGENCY_ID) > 1 OR COUNT(DISTINCT ACTIVE_PRODUCERS) > 1
          OR COUNT(DISTINCT VENDOR) > 1 OR COUNT(DISTINCT MAX_AGE) > 1
          OR COUNT(DISTINCT AGENCY_APPOINTMENT_YEAR) > 1 OR COUNT(DISTINCT PL_START_YEAR) > 1)

-- 13. Snapshot assumption: quote/bound counts never vary within an agency
UNION ALL
SELECT 'quote/bound counts constant per agency',
       COUNT(*)
FROM (SELECT AGENCY_ID FROM stg_agency_performance GROUP BY AGENCY_ID
      HAVING COUNT(DISTINCT CL_QUO_CT_MDS) > 1 OR COUNT(DISTINCT CL_BOUND_CT_SBZ) > 1
          OR COUNT(DISTINCT PL_QUO_CT_eQTte) > 1 OR COUNT(DISTINCT PL_BOUND_CT_APPLIED) > 1
          OR COUNT(DISTINCT PL_QUO_CT_TRANSACTNOW) > 1)

-- 14. Sentinel handling: no 99999 left in columns where it means "missing"
UNION ALL
SELECT 'no 99999 left in sentinel columns',
       COUNT(*) FROM fact_agency_product_performance
       WHERE prev_poly_inforce_qty = 99999 OR prev_wrtn_prem_amt = 99999
          OR src_loss_ratio = 99999 OR src_retention_ratio = 99999
          OR src_loss_ratio_3yr = 99999 OR src_growth_rate_3yr = 99999

-- 15. Business rule: stored retention ratio = retained policies / prior-year policies
UNION ALL
SELECT 'src_retention_ratio matches its components',
       COUNT(*) FROM fact_agency_product_performance
       WHERE src_retention_ratio IS NOT NULL AND prev_poly_inforce_qty > 0
         AND ABS(src_retention_ratio - 1.0 * retention_poly_qty / prev_poly_inforce_qty) > 0.001;
