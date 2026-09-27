-- =====================================================================
-- Load dimensions from stg_agency_performance (all staging columns are TEXT).
-- 99999 is replaced with NULL only in columns where profiling showed it is
-- a missing/not-applicable marker. See docs/data_model.md for each decision.
-- =====================================================================

-- dim_year ------------------------------------------------------------
INSERT INTO dim_year (year_key, max_months_reported, is_complete_year)
SELECT CAST(STAT_PROFILE_DATE_YEAR AS INTEGER),
       MAX(CAST(MONTHS AS INTEGER)),
       CASE WHEN MAX(CAST(MONTHS AS INTEGER)) = 12 THEN 1 ELSE 0 END
FROM stg_agency_performance
GROUP BY CAST(STAT_PROFILE_DATE_YEAR AS INTEGER);

-- dim_state -----------------------------------------------------------
INSERT INTO dim_state (state_abbr, state_name)
SELECT DISTINCT STATE_ABBR,
       CASE STATE_ABBR
           WHEN 'IN' THEN 'Indiana'
           WHEN 'KY' THEN 'Kentucky'
           WHEN 'MI' THEN 'Michigan'
           WHEN 'OH' THEN 'Ohio'
           WHEN 'PA' THEN 'Pennsylvania'
           WHEN 'WV' THEN 'West Virginia'
           ELSE 'Unknown'
       END
FROM stg_agency_performance
ORDER BY STATE_ABBR;

-- dim_product ---------------------------------------------------------
-- product_code collapses the fixed-width padding ('ANNIV   12' -> 'ANNIV 12').
INSERT INTO dim_product (prod_abbr, product_code, base_product, is_12_variant, prod_line, prod_line_name)
SELECT prod_abbr,
       REPLACE(REPLACE(REPLACE(prod_abbr, '   ', ' '), '  ', ' '), '  ', ' '),
       CASE prod_abbr
           WHEN 'ANNIV   12' THEN 'ANNIV'
           WHEN 'CYCLES  12' THEN 'CYCLES'
           WHEN 'DTALK   12' THEN 'DTALK'
           WHEN 'MOTORHOM12' THEN 'MOTORHOME'
           WHEN 'SNOWMOBI12' THEN 'SNOWMOBILE'
           ELSE prod_abbr
       END,
       CASE WHEN prod_abbr LIKE '%12' THEN 1 ELSE 0 END,
       prod_line,
       CASE prod_line WHEN 'CL' THEN 'Commercial Lines' ELSE 'Personal Lines' END
FROM (SELECT DISTINCT PROD_ABBR AS prod_abbr, PROD_LINE AS prod_line FROM stg_agency_performance)
ORDER BY prod_line, prod_abbr;

-- dim_agency ----------------------------------------------------------
-- Attributes are constant per agency (tested in sql/tests), so MAX() just
-- picks that single value.
INSERT INTO dim_agency (
    agency_id, primary_agency_id, agency_appointment_year, active_producers,
    max_producer_age, min_producer_age, vendor_ind, vendor,
    pl_start_year, pl_end_year, commissions_start_year, commissions_end_year,
    cl_start_year, cl_end_year, activity_notes_start_year, activity_notes_end_year
)
SELECT CAST(AGENCY_ID AS INTEGER),
       NULLIF(MAX(CAST(PRIMARY_AGENCY_ID         AS INTEGER)), 99999),
       NULLIF(MAX(CAST(AGENCY_APPOINTMENT_YEAR   AS INTEGER)), 99999),
       NULLIF(MAX(CAST(ACTIVE_PRODUCERS          AS INTEGER)), 99999),
       NULLIF(MAX(CAST(MAX_AGE                   AS INTEGER)), 99999),
       NULLIF(MAX(CAST(MIN_AGE                   AS INTEGER)), 99999),
       MAX(VENDOR_IND),
       MAX(VENDOR),
       NULLIF(MAX(CAST(PL_START_YEAR             AS INTEGER)), 99999),
       NULLIF(MAX(CAST(PL_END_YEAR               AS INTEGER)), 99999),
       NULLIF(MAX(CAST(COMMISIONS_START_YEAR     AS INTEGER)), 99999),
       NULLIF(MAX(CAST(COMMISIONS_END_YEAR       AS INTEGER)), 99999),
       NULLIF(MAX(CAST(CL_START_YEAR             AS INTEGER)), 99999),
       NULLIF(MAX(CAST(CL_END_YEAR               AS INTEGER)), 99999),
       NULLIF(MAX(CAST(ACTIVITY_NOTES_START_YEAR AS INTEGER)), 99999),
       NULLIF(MAX(CAST(ACTIVITY_NOTES_END_YEAR   AS INTEGER)), 99999)
FROM stg_agency_performance
GROUP BY CAST(AGENCY_ID AS INTEGER)
ORDER BY CAST(AGENCY_ID AS INTEGER);
