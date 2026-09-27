-- =====================================================================
-- Reference business queries (manually reviewed).
-- Each query starts with a "-- name:" line so src/run_query.py can run it by name:
--     python src/run_query.py written_premium_by_year
--
-- Rules followed everywhere:
--   * Ratios are recalculated from summed amounts, never averaged or summed.
--   * Policy counts (semi-additive) are summed within a year, never across years.
--   * 2005 (8 months) and 2015 (5 months) are partial years; trend queries flag them.
-- =====================================================================

-- name: written_premium_by_year
-- Total written premium per reporting year, with partial-year flag.
SELECT y.year_key                      AS year,
       y.is_complete_year,
       ROUND(SUM(f.wrtn_prem_amt), 2)  AS written_premium
FROM fact_agency_product_performance f
JOIN dim_year y ON y.year_key = f.year_key
GROUP BY y.year_key, y.is_complete_year
ORDER BY y.year_key;

-- name: written_premium_by_line_and_state
-- Written premium by product line and state, 2014 (latest complete year).
SELECT p.prod_line_name,
       s.state_name,
       ROUND(SUM(f.wrtn_prem_amt), 2) AS written_premium
FROM fact_agency_product_performance f
JOIN dim_product p ON p.product_key = f.product_key
JOIN dim_state   s ON s.state_key   = f.state_key
WHERE f.year_key = 2014
GROUP BY p.prod_line_name, s.state_name
ORDER BY written_premium DESC;

-- name: loss_ratio_by_year
-- Earned premium, incurred losses and recalculated loss ratio per year.
SELECT f.year_key                                   AS year,
       ROUND(SUM(f.prd_ernd_prem_amt), 2)           AS earned_premium,
       ROUND(SUM(f.prd_incrd_losses_amt), 2)        AS incurred_losses,
       ROUND(SUM(f.prd_incrd_losses_amt) / NULLIF(SUM(f.prd_ernd_prem_amt), 0), 4) AS loss_ratio
FROM fact_agency_product_performance f
GROUP BY f.year_key
ORDER BY f.year_key;

-- name: loss_ratio_by_product_line
-- Recalculated loss ratio by product line over complete years only (2006-2014).
SELECT p.prod_line_name,
       ROUND(SUM(f.prd_ernd_prem_amt), 2)    AS earned_premium,
       ROUND(SUM(f.prd_incrd_losses_amt), 2) AS incurred_losses,
       ROUND(SUM(f.prd_incrd_losses_amt) / NULLIF(SUM(f.prd_ernd_prem_amt), 0), 4) AS loss_ratio
FROM fact_agency_product_performance f
JOIN dim_product p ON p.product_key = f.product_key
JOIN dim_year    y ON y.year_key    = f.year_key
WHERE y.is_complete_year = 1
GROUP BY p.prod_line_name;

-- name: new_business_share_by_year
-- New-business written premium and its share of total written premium.
SELECT f.year_key AS year,
       ROUND(SUM(f.nb_wrtn_prem_amt), 2) AS new_business_premium,
       ROUND(SUM(f.nb_wrtn_prem_amt) / NULLIF(SUM(f.wrtn_prem_amt), 0), 4) AS new_business_share
FROM fact_agency_product_performance f
GROUP BY f.year_key
ORDER BY f.year_key;

-- name: policies_in_force_by_year
-- Semi-additive: summed across agencies/products/states WITHIN each year only.
SELECT f.year_key AS year,
       SUM(f.poly_inforce_qty) AS policies_in_force
FROM fact_agency_product_performance f
GROUP BY f.year_key
ORDER BY f.year_key;

-- name: retention_by_year
-- Retention = retained policies / prior-year policies in force.
-- Only rows where the prior-year count is known and positive are valid.
SELECT f.year_key AS year,
       SUM(f.retention_poly_qty)    AS retained_policies,
       SUM(f.prev_poly_inforce_qty) AS prior_year_policies,
       ROUND(1.0 * SUM(f.retention_poly_qty) / NULLIF(SUM(f.prev_poly_inforce_qty), 0), 4) AS retention_rate
FROM fact_agency_product_performance f
WHERE f.prev_poly_inforce_qty > 0
GROUP BY f.year_key
ORDER BY f.year_key;

-- name: top_agencies_2012_2014
-- "High performing" = written premium >= $1M over 2012-2014 AND recalculated
-- loss ratio below 60% over the same years, ranked by written premium.
SELECT a.agency_id,
       ROUND(SUM(f.wrtn_prem_amt), 2) AS written_premium_2012_2014,
       ROUND(SUM(f.prd_incrd_losses_amt) / NULLIF(SUM(f.prd_ernd_prem_amt), 0), 4) AS loss_ratio_2012_2014
FROM fact_agency_product_performance f
JOIN dim_agency a ON a.agency_key = f.agency_key
WHERE f.year_key BETWEEN 2012 AND 2014
GROUP BY a.agency_id
HAVING SUM(f.wrtn_prem_amt) >= 1000000
   AND SUM(f.prd_incrd_losses_amt) / NULLIF(SUM(f.prd_ernd_prem_amt), 0) < 0.60
ORDER BY written_premium_2012_2014 DESC
LIMIT 10;

-- name: growing_agencies_acceptable_loss
-- Agencies whose written premium grew from 2012 to 2014 while their
-- 2012-2014 loss ratio stayed below 65%. Minimum $250k premium in 2012.
WITH by_agency AS (
    SELECT f.agency_key,
           SUM(CASE WHEN f.year_key = 2012 THEN f.wrtn_prem_amt END) AS wp_2012,
           SUM(CASE WHEN f.year_key = 2014 THEN f.wrtn_prem_amt END) AS wp_2014,
           SUM(f.prd_incrd_losses_amt) / NULLIF(SUM(f.prd_ernd_prem_amt), 0) AS loss_ratio
    FROM fact_agency_product_performance f
    WHERE f.year_key BETWEEN 2012 AND 2014
    GROUP BY f.agency_key
)
SELECT a.agency_id,
       ROUND(b.wp_2012, 2) AS written_premium_2012,
       ROUND(b.wp_2014, 2) AS written_premium_2014,
       ROUND(b.wp_2014 / b.wp_2012 - 1, 4) AS growth_2012_to_2014,
       ROUND(b.loss_ratio, 4) AS loss_ratio_2012_2014
FROM by_agency b
JOIN dim_agency a ON a.agency_key = b.agency_key
WHERE b.wp_2012 >= 250000 AND b.wp_2014 > b.wp_2012 AND b.loss_ratio < 0.65
ORDER BY growth_2012_to_2014 DESC
LIMIT 10;

-- name: quote_to_bind_by_platform
-- Uses the agency-level snapshot table (no year available in the source).
SELECT q.prod_line,
       q.quote_platform,
       SUM(q.quote_count) AS quotes,
       SUM(q.bound_count) AS bound,
       ROUND(1.0 * SUM(q.bound_count) / NULLIF(SUM(q.quote_count), 0), 4) AS bind_rate
FROM fact_agency_quote_activity q
WHERE q.quote_count IS NOT NULL AND q.bound_count IS NOT NULL
GROUP BY q.prod_line, q.quote_platform
ORDER BY q.prod_line, bind_rate DESC;
