# Insurance Agency AI Performance Analyst

A learning proof of concept that turns public insurance agency data into a Kimball-style star schema in SQLite, then lets a user ask business questions in plain English. An LLM translates each question into validated, read-only SQL; the database does every calculation; the LLM explains only the rows that come back.

> **Status:** Day 1 of a four-day learning sprint. This is a proof of concept built on public data, not a production system.

## Business problem

Insurance carriers distribute products through independent agencies. Managers want quick answers to questions such as:

- Which agencies are growing written premium while keeping loss ratios acceptable?
- How do new-business premium and policies in force trend by product line and state?
- Which agencies retain their book of business, and which convert quotes into bound policies?

Answering these usually means writing SQL by hand. This project explores whether an LLM can do that translation safely, with guardrails that keep the numbers correct and traceable.

## Dataset

**Source:** [Insurance Agency Performance, Kaggle (moneystore)](https://www.kaggle.com/datasets/moneystore/agencyperformance)

Verified on the downloaded file `finalapi.csv`:

| Property | Value |
|---|---|
| File size | ~47 MB |
| Rows (excluding header) | 213,328 |
| Columns | 49 |
| Reporting years (`STAT_PROFILE_DATE_YEAR`) | 2005–2015 (11 years) |
| Agencies (`AGENCY_ID`) | 1,623 |
| Products (`PROD_ABBR`) | 28 distinct values |
| Product lines (`PROD_LINE`) | CL (commercial lines), PL (personal lines) |
| States (`STATE_ABBR`) | IN, KY, MI, OH, PA, WV |

**Candidate source grain:** one row per agency × product × state × reporting year. The combination `AGENCY_ID + PROD_ABBR + STATE_ABBR + STAT_PROFILE_DATE_YEAR` produced 213,328 distinct values on an initial check, matching the row count. This will be tested formally on Day 2.

**Column groups:** agency identifiers; product and state; policy counts (in force, retained, prior year); premium amounts (written, new-business written, prior-year written, earned); incurred losses; stored ratios (retention, loss ratio, 3-year loss ratio, 3-year growth rate); agency attributes (appointment year, active producers, producer ages, vendor); system start/end years; and quote/bound counts by quoting platform.

The raw file is **not committed**. To reproduce, download it from Kaggle and place `finalapi.csv` in `data/raw/`.

### Known data-quality concerns (to be validated on Day 2)

- `99999` appears to be a sentinel for missing or unavailable data in several columns. Its meaning will be checked column by column before any value is replaced with NULL.
- `RETENTION_RATIO`, `LOSS_RATIO`, `LOSS_RATIO_3YR`, and `GROWTH_RATE_3YR` are non-additive. They will not be summed or averaged; aggregate ratios will be recalculated from underlying amounts, e.g. loss ratio = `SUM(PRD_INCRD_LOSSES_AMT) / NULLIF(SUM(PRD_ERND_PREM_AMT), 0)`.
- Agency-level attributes repeat on every product-state-year row and could be double-counted if aggregated from the fact grain.
- Negative incurred losses may reflect recoveries or reserve changes and will be investigated before being treated as errors.
- Some `PROD_ABBR` values contain embedded whitespace (e.g. `ANNIV   12`) and need a cleaning decision.

## Proposed architecture

```
finalapi.csv
   │  Python + pandas: profile, clean, validate
   ▼
SQLite staging table (raw, as-received)
   │  SQL transformations
   ▼
Star schema
   fact_agency_product_performance
   dim_agency · dim_product · dim_state · dim_year
   │
   ▼
Read-only query layer  ◄── SQL validator (single SELECT/WITH, row limit, timeout)
   ▲
   │  generated SQL
LLM (text-to-SQL, then result explanation)
   ▲
   │
Controlled agent loop with approved tools
(get_schema, get_metric_definition, run_readonly_query, inspect_distinct_values)
```

The dimensional model above is a starting proposal and will be refined on Day 2 (grain, keys, measure additivity, attribute dependencies, slowly changing dimensions).

## Tech stack

Python 3 · pandas · SQLite · SQL · Git/GitHub · a direct LLM API · a small custom tool-calling loop.

Deliberately out of scope for this sprint: LangChain/LangGraph, vector databases/RAG, Docker, cloud deployment, and a frontend.

## Project structure

```
insurance-agency-ai-analyst/
├── data/
│   ├── raw/          # Original Kaggle file (git-ignored)
│   └── processed/    # Cleaned intermediate outputs (git-ignored)
├── database/         # SQLite database file (git-ignored; rebuilt from code)
├── docs/             # Data dictionary, source-to-target mapping, schema diagram
├── notebooks/        # Exploratory profiling
├── sql/
│   ├── ddl/              # CREATE TABLE statements
│   ├── transformations/  # Staging → dimensions → fact
│   ├── analysis/         # Verified business queries
│   └── tests/            # Validation queries (keys, row counts, duplicates)
├── src/              # Python ingestion, SQL validator, LLM and agent code
├── tests/            # Automated tests and AI evaluation cases
├── .env.example      # Names of required environment variables, no real keys
├── .gitignore
├── README.md
└── requirements.txt
```

Folders are added as they gain real content.

## Learning goals

- Practise Git workflow: small commits, branches, pull requests, tags.
- Profile a real dataset and prove its grain with code, not assumptions.
- Design a Kimball star schema and classify additive, semi-additive, and non-additive measures.
- Build a repeatable Python + SQL load into SQLite with validation checks.
- Integrate an LLM for text-to-SQL with strict read-only guardrails.
- Build a small, bounded agent and explain how it differs from a single LLM call.
- Evaluate AI output against manually written reference SQL.

## Sprint plan

| Day | Focus | Milestone tag |
|---|---|---|
| 1 | Repository, environment, project foundation | `v0.1-foundation` |
| 2 | Profiling, grain validation, star schema, SQLite load, business SQL | `v0.2-dimensional-model` |
| 3 | Direct LLM text-to-SQL with validation and grounded explanations | `v0.3-text-to-sql` |
| 4 | Controlled tool-calling agent, logging, evaluation suite | `v0.4-agent-poc` |

## Setup

```bash
git clone https://github.com/Bsharma4/insurance-agency-ai-analyst.git
cd insurance-agency-ai-analyst
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
```

Then download `finalapi.csv` from Kaggle into `data/raw/`.

## Disclaimer

Built for learning with publicly available data. Results are illustrative and not intended for business decisions.
