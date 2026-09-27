-- =====================================================================
-- Load facts. Natural keys from staging are swapped for surrogate keys
-- by joining to each dimension.
-- =====================================================================

-- fact_agency_product_performance -------------------------------------
INSERT INTO fact_agency_product_performance (
    agency_key, product_key, state_key, year_key,
    poly_inforce_qty, prev_poly_inforce_qty, retention_poly_qty,
    wrtn_prem_amt, prev_wrtn_prem_amt, nb_wrtn_prem_amt,
    prd_ernd_prem_amt, prd_incrd_losses_amt,
    months_reported,
    src_retention_ratio, src_loss_ratio, src_loss_ratio_3yr, src_growth_rate_3yr
)
SELECT a.agency_key,
       p.product_key,
       s.state_key,
       CAST(stg.STAT_PROFILE_DATE_YEAR AS INTEGER),

       CAST(stg.POLY_INFORCE_QTY AS INTEGER),
       NULLIF(CAST(stg.PREV_POLY_INFORCE_QTY AS INTEGER), 99999),   -- sentinel: no prior-year value
       CAST(stg.RETENTION_POLY_QTY AS INTEGER),

       CAST(stg.WRTN_PREM_AMT AS REAL),
       NULLIF(CAST(stg.PREV_WRTN_PREM_AMT AS REAL), 99999),         -- sentinel: no prior-year value
       CAST(stg.NB_WRTN_PREM_AMT AS REAL),        -- kept as-is: the single 99999 is a plausible real amount
       CAST(stg.PRD_ERND_PREM_AMT AS REAL),
       CAST(stg.PRD_INCRD_LOSSES_AMT AS REAL),

       CAST(stg.MONTHS AS INTEGER),

       NULLIF(CAST(stg.RETENTION_RATIO AS REAL), 99999),
       NULLIF(CAST(stg.LOSS_RATIO      AS REAL), 99999),
       NULLIF(CAST(stg.LOSS_RATIO_3YR  AS REAL), 99999),
       NULLIF(CAST(stg.GROWTH_RATE_3YR AS REAL), 99999)
FROM stg_agency_performance AS stg
JOIN dim_agency  AS a ON a.agency_id  = CAST(stg.AGENCY_ID AS INTEGER)
JOIN dim_product AS p ON p.prod_abbr  = stg.PROD_ABBR
JOIN dim_state   AS s ON s.state_abbr = stg.STATE_ABBR;

-- fact_agency_quote_activity ------------------------------------------
-- Unpivot 16 wide columns (8 platforms x quote/bound) into rows.
-- One staging row per agency is enough because the values are identical
-- on every row of that agency (tested in sql/tests).
WITH one_row_per_agency AS (
    SELECT *
    FROM stg_agency_performance
    WHERE rowid IN (SELECT MIN(rowid) FROM stg_agency_performance GROUP BY AGENCY_ID)
),
unpivoted AS (
    SELECT AGENCY_ID, 'CL' AS prod_line, 'MDS'         AS quote_platform, CL_QUO_CT_MDS         AS q, CL_BOUND_CT_MDS         AS b FROM one_row_per_agency
    UNION ALL SELECT AGENCY_ID, 'CL', 'SBZ',          CL_QUO_CT_SBZ,          CL_BOUND_CT_SBZ          FROM one_row_per_agency
    UNION ALL SELECT AGENCY_ID, 'CL', 'eQT',          CL_QUO_CT_eQT,          CL_BOUND_CT_eQT          FROM one_row_per_agency
    UNION ALL SELECT AGENCY_ID, 'PL', 'ELINKS',       PL_QUO_CT_ELINKS,       PL_BOUND_CT_ELINKS       FROM one_row_per_agency
    UNION ALL SELECT AGENCY_ID, 'PL', 'PLRANK',       PL_QUO_CT_PLRANK,       PL_BOUND_CT_PLRANK       FROM one_row_per_agency
    UNION ALL SELECT AGENCY_ID, 'PL', 'eQTte',        PL_QUO_CT_eQTte,        PL_BOUND_CT_eQTte        FROM one_row_per_agency
    UNION ALL SELECT AGENCY_ID, 'PL', 'APPLIED',      PL_QUO_CT_APPLIED,      PL_BOUND_CT_APPLIED      FROM one_row_per_agency
    UNION ALL SELECT AGENCY_ID, 'PL', 'TRANSACTNOW',  PL_QUO_CT_TRANSACTNOW,  PL_BOUND_CT_TRANSACTNOW  FROM one_row_per_agency
)
INSERT INTO fact_agency_quote_activity (agency_key, prod_line, quote_platform, quote_count, bound_count)
SELECT a.agency_key,
       u.prod_line,
       u.quote_platform,
       NULLIF(CAST(u.q AS INTEGER), 99999),
       NULLIF(CAST(u.b AS INTEGER), 99999)
FROM unpivoted AS u
JOIN dim_agency AS a ON a.agency_id = CAST(u.AGENCY_ID AS INTEGER)
-- skip platforms with no information at all for this agency
WHERE NOT (CAST(u.q AS INTEGER) = 99999 AND CAST(u.b AS INTEGER) = 99999);
