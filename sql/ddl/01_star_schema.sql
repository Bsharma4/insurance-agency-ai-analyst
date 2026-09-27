-- =====================================================================
-- Star schema: Insurance Agency Performance (proof of concept)
--
-- Business process : annual agency production and loss results
-- Main fact grain  : one row per agency x product x state x reporting year
--                    (proven unique in notebooks/01_profiling.ipynb)
--
-- Re-runnable: every table is dropped and rebuilt from staging.
-- Facts are dropped first because they reference the dimensions.
-- =====================================================================

DROP TABLE IF EXISTS fact_agency_quote_activity;
DROP TABLE IF EXISTS fact_agency_product_performance;
DROP TABLE IF EXISTS dim_agency;
DROP TABLE IF EXISTS dim_product;
DROP TABLE IF EXISTS dim_state;
DROP TABLE IF EXISTS dim_year;

-- ---------------------------------------------------------------------
-- dim_year: the year itself is the key (a "smart key" is normal for
-- calendar dimensions). 2005 and 2015 are partial years in the source.
-- ---------------------------------------------------------------------
CREATE TABLE dim_year (
    year_key              INTEGER PRIMARY KEY,   -- e.g. 2014
    max_months_reported   INTEGER NOT NULL,      -- highest MONTHS value seen that year
    is_complete_year      INTEGER NOT NULL CHECK (is_complete_year IN (0, 1))
);

-- ---------------------------------------------------------------------
-- dim_state
-- ---------------------------------------------------------------------
CREATE TABLE dim_state (
    state_key    INTEGER PRIMARY KEY,
    state_abbr   TEXT NOT NULL UNIQUE,           -- natural key
    state_name   TEXT NOT NULL
);

-- ---------------------------------------------------------------------
-- dim_product: 28 source codes. The "...12" codes are kept as separate
-- products (they co-exist with their base product for the same
-- agency/state/year). base_product lets users roll them up on purpose.
-- ---------------------------------------------------------------------
CREATE TABLE dim_product (
    product_key           INTEGER PRIMARY KEY,
    prod_abbr             TEXT NOT NULL UNIQUE,  -- natural key, exactly as in source
    product_code          TEXT NOT NULL,         -- display code, repeated spaces collapsed
    base_product          TEXT NOT NULL,         -- e.g. 'ANNIV' for 'ANNIV   12'
    is_12_variant         INTEGER NOT NULL CHECK (is_12_variant IN (0, 1)),
    prod_line             TEXT NOT NULL CHECK (prod_line IN ('CL', 'PL')),
    prod_line_name        TEXT NOT NULL          -- 'Commercial Lines' / 'Personal Lines'
);

-- ---------------------------------------------------------------------
-- dim_agency: one row per agency. Every attribute was proven constant
-- per agency across all years, so this is a single snapshot (no SCD
-- history exists in the source). 99999 -> NULL (unknown / not applicable).
-- ---------------------------------------------------------------------
CREATE TABLE dim_agency (
    agency_key                  INTEGER PRIMARY KEY,
    agency_id                   INTEGER NOT NULL UNIQUE,  -- natural key
    primary_agency_id           INTEGER,                  -- parent/primary agency; NULL if 99999
    agency_appointment_year     INTEGER,
    active_producers            INTEGER,
    max_producer_age            INTEGER,
    min_producer_age            INTEGER,
    vendor_ind                  TEXT,                     -- 'Y' / 'N'
    vendor                      TEXT,                     -- 'A'..'J' or 'Unknown'
    pl_start_year               INTEGER,
    pl_end_year                 INTEGER,
    commissions_start_year      INTEGER,
    commissions_end_year        INTEGER,
    cl_start_year               INTEGER,
    cl_end_year                 INTEGER,
    activity_notes_start_year   INTEGER,
    activity_notes_end_year     INTEGER
);

-- ---------------------------------------------------------------------
-- fact_agency_product_performance: the main fact table.
--   Additive      : *_amt columns (premium, losses)
--   Semi-additive : *_qty columns (policy counts at a point in time:
--                   sum across agencies/products/states, NOT across years)
--   Non-additive  : src_* ratios, stored as delivered for row-level
--                   reference only. Never SUM or AVG them; recalculate
--                   from amounts instead.
-- ---------------------------------------------------------------------
CREATE TABLE fact_agency_product_performance (
    agency_key               INTEGER NOT NULL REFERENCES dim_agency (agency_key),
    product_key              INTEGER NOT NULL REFERENCES dim_product (product_key),
    state_key                INTEGER NOT NULL REFERENCES dim_state (state_key),
    year_key                 INTEGER NOT NULL REFERENCES dim_year (year_key),

    -- semi-additive (point-in-time counts)
    poly_inforce_qty         INTEGER NOT NULL,
    prev_poly_inforce_qty    INTEGER,          -- NULL when source had 99999
    retention_poly_qty       INTEGER NOT NULL,

    -- additive (period amounts)
    wrtn_prem_amt            REAL NOT NULL,
    prev_wrtn_prem_amt       REAL,             -- NULL when source had 99999
    nb_wrtn_prem_amt         REAL NOT NULL,
    prd_ernd_prem_amt        REAL NOT NULL,
    prd_incrd_losses_amt     REAL NOT NULL,    -- may be negative (recoveries / reserve releases)

    -- data-coverage field
    months_reported          INTEGER NOT NULL CHECK (months_reported BETWEEN 1 AND 12),

    -- non-additive, as delivered by the source (NULL when 99999)
    src_retention_ratio      REAL,
    src_loss_ratio           REAL,
    src_loss_ratio_3yr       REAL,
    src_growth_rate_3yr      REAL,

    PRIMARY KEY (agency_key, product_key, state_key, year_key)
);

-- ---------------------------------------------------------------------
-- fact_agency_quote_activity: quote/bound counts were proven to be ONE
-- snapshot per agency (identical on every product/state/year row).
-- Keeping them in the main fact would multiply them when summed, so they
-- live here at their true grain: agency x product line x quote platform.
-- There is no year: the source does not say what period they cover.
-- ---------------------------------------------------------------------
CREATE TABLE fact_agency_quote_activity (
    agency_key       INTEGER NOT NULL REFERENCES dim_agency (agency_key),
    prod_line        TEXT NOT NULL CHECK (prod_line IN ('CL', 'PL')),
    quote_platform   TEXT NOT NULL,
    quote_count      INTEGER,          -- NULL when source had 99999
    bound_count      INTEGER,          -- NULL when source had 99999
    PRIMARY KEY (agency_key, prod_line, quote_platform)
);
