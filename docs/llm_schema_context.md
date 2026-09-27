# Approved schema and metric definitions (sent to the LLM)

This file is loaded by `src/ask.py` and sent to the model with every question. It is the **only** description of the database the model sees. Edit it to change what the model knows.

## Database

SQLite. Insurance agency performance data, 2005–2015, six US states. Read-only.

## Tables

### fact_agency_product_performance
Grain: one row per agency × product × state × reporting year.

| Column | Meaning | How to aggregate |
|---|---|---|
| agency_key | FK → dim_agency | |
| product_key | FK → dim_product | |
| state_key | FK → dim_state | |
| year_key | FK → dim_year (the year itself, e.g. 2014) | |
| wrtn_prem_amt | Written premium in the year (USD) | SUM |
| nb_wrtn_prem_amt | Written premium from new business (USD) | SUM |
| prev_wrtn_prem_amt | Prior-year written premium on this row (USD); NULL if unknown | SUM |
| prd_ernd_prem_amt | Earned premium in the period (USD) | SUM |
| prd_incrd_losses_amt | Incurred losses in the period (USD); can be negative | SUM |
| poly_inforce_qty | Policies in force at the reporting date | SUM within one year only; never add different years together |
| prev_poly_inforce_qty | Policies in force a year earlier; NULL if unknown | SUM within one year only |
| retention_poly_qty | Policies retained from the prior year | SUM within one year only |
| months_reported | Months of data in that row's year (1–12) | do not sum |
| src_loss_ratio, src_retention_ratio, src_loss_ratio_3yr, src_growth_rate_3yr | Ratios as delivered by the source, per row | NEVER SUM or AVG. Row-level display only |

### fact_agency_quote_activity
Grain: one row per agency × product line × quote platform. A single snapshot per agency; **it has no year**.

| Column | Meaning |
|---|---|
| agency_key | FK → dim_agency |
| prod_line | 'CL' or 'PL' |
| quote_platform | CL: 'MDS', 'SBZ', 'eQT'. PL: 'ELINKS', 'PLRANK', 'eQTte', 'APPLIED', 'TRANSACTNOW' |
| quote_count | Number of quotes (NULL if unknown) |
| bound_count | Number of quotes bound into policies (NULL if unknown) |

### dim_agency
| Column | Meaning |
|---|---|
| agency_key | PK |
| agency_id | Agency identifier shown to users |
| primary_agency_id | Primary (parent) agency id; NULL if none |
| agency_appointment_year | Year the agency was appointed |
| active_producers | Number of active producers (single snapshot, not by year) |
| max_producer_age, min_producer_age | Oldest / youngest producer age (snapshot) |
| vendor_ind | 'Y' or 'N' |
| vendor | 'A'–'J' or 'Unknown' |
| pl_start_year, pl_end_year, cl_start_year, cl_end_year, commissions_start_year, commissions_end_year, activity_notes_start_year, activity_notes_end_year | Years a system/feature was used; NULL if never / not ended |

### dim_product
| Column | Meaning |
|---|---|
| product_key | PK |
| prod_abbr | Raw product code (may contain padding spaces; prefer product_code) |
| product_code | Clean product code, e.g. 'HOMEOWNERS', 'COMMAUTO', 'ANNIV 12' |
| base_product | Product family; the '…12' variants roll up to their base (e.g. 'ANNIV 12' → 'ANNIV') |
| is_12_variant | 1 for the five '…12' variant codes (exist from 2012 only) |
| prod_line | 'CL' or 'PL' |
| prod_line_name | 'Commercial Lines' or 'Personal Lines' |

Product codes (product_code): BOILERMACH, BOP, COMMAUTO, COMMINLMAR, COMMPOL, COMMUMBREL, CRIME, FIREALLIED, GARAGE, GENERALIAB, WORKCOMP (CL); ANNIV, ANNIV 12, CYCLES, CYCLES 12, DTALK, DTALK 12, DWELLFIRE, HOMEOWNERS, MOBILEHOME, MOTORHOME, MOTORHOM12, PERSAIP, PERSINLMAR, PERSUMBREL, SNOWMOBILE, SNOWMOBI12, YACHT (PL).

### dim_state
| Column | Meaning |
|---|---|
| state_key | PK |
| state_abbr | 'IN', 'KY', 'MI', 'OH', 'PA', 'WV' |
| state_name | Full name, e.g. 'Ohio' |

### dim_year
| Column | Meaning |
|---|---|
| year_key | PK, the year (2005–2015) |
| max_months_reported | Months of data available that year |
| is_complete_year | 1 for 2006–2014. 0 for 2005 (8 months) and 2015 (5 months) |

## Metric definitions

| Metric | SQL definition |
|---|---|
| Written premium | `SUM(f.wrtn_prem_amt)` |
| Earned premium | `SUM(f.prd_ernd_prem_amt)` |
| Incurred losses | `SUM(f.prd_incrd_losses_amt)` |
| Loss ratio | `SUM(f.prd_incrd_losses_amt) / NULLIF(SUM(f.prd_ernd_prem_amt), 0)` |
| New-business share | `SUM(f.nb_wrtn_prem_amt) / NULLIF(SUM(f.wrtn_prem_amt), 0)` |
| Policies in force | `SUM(f.poly_inforce_qty)` grouped by year (or filtered to one year) |
| Retention rate | `1.0 * SUM(f.retention_poly_qty) / NULLIF(SUM(f.prev_poly_inforce_qty), 0)` with `WHERE f.prev_poly_inforce_qty > 0` |
| Premium growth A→B | `SUM(premium in year B) / NULLIF(SUM(premium in year A), 0) - 1` |
| Quote-to-bind rate | `1.0 * SUM(q.bound_count) / NULLIF(SUM(q.quote_count), 0)` with both counts NOT NULL |

## Rules

1. Recalculate ratios from summed amounts using the definitions above. Never SUM or AVG a ratio column.
2. Never add policy counts across different years.
3. When comparing years or showing trends, prefer complete years (`dim_year.is_complete_year = 1`) and mention that 2005 and 2015 are partial.
4. Quote/bound data has no year. Do not join it to years or to products.
5. Join dimensions on surrogate keys, e.g. `JOIN dim_state s ON s.state_key = f.state_key`.
6. "Latest complete year" means 2014.
7. Round money to 2 decimals and ratios to 4 decimals.
8. If the data cannot answer the question (e.g. customer names, claims counts, profit, commissions paid, months other than year-level, anything after 2015), say it is not answerable.
