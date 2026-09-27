# Insurance Agency AI Performance Analyst

**Ask business questions about insurance agency performance in plain English, and get answers backed by validated, read-only SQL.**

A proof of concept that turns a raw public insurance dataset (213,328 rows, 49 columns) into a tested Kimball star schema in SQLite, then puts an LLM on top with strict guardrails. The LLM writes the SQL and explains the results. The database does every calculation, and a safety layer makes sure generated SQL can only read approved tables.

> **Status:** proof of concept on public Kaggle data. Not a production system.

<!-- Add a screenshot of the web chat here: docs/images/web_chat.png -->

---

## What this project demonstrates

| Area | What was done |
|---|---|
| **Data profiling** | Loaded the raw CSV into a staging table and profiled every column with SQL. Proved the table's grain, traced the `99999` placeholder value column by column, and found columns that looked yearly but were really one fixed value per agency |
| **Dimensional modeling** | Designed a Kimball star schema: 4 dimensions and 2 fact tables, surrogate keys, and each measure classified as additive, semi-additive or non-additive |
| **Data engineering** | Repeatable build pipeline (Python standard library + SQL) that loads, transforms and validates the database in about 4 seconds |
| **Data quality** | 16 automated validation checks: row and amount reconciliation, grain uniqueness, referential integrity, the snapshot assumptions, and `99999` handling |
| **SQL analytics** | 10 reviewed business queries: loss ratio, retention, new-business share, agency ranking, quote-to-bind |
| **LLM integration** | Text-to-SQL using structured JSON output, a curated schema and metric definitions, and explanations grounded only in the returned rows |
| **AI safety** | Two-layer SQL guard: text checks, plus the SQLite authorizer on a read-only connection. Row limit, time limit, table allow-list, 12 unit tests |
| **Evaluation** | 12 evaluation cases comparing generated SQL results against hand-written reference SQL, including ambiguous, unanswerable and unsafe questions |
| **Application** | Local web chat with charts, result tables and the SQL behind each answer, plus a command-line interface |
| **Engineering practice** | Git feature branches, small descriptive commits, milestone tags, secrets kept in `.env`, raw data and database kept out of Git |

---

## Architecture

```
finalapi.csv (Kaggle, 213,328 rows)
   │  src/build_database.py  (Python stdlib: csv + sqlite3)
   ▼
stg_agency_performance        raw staging, every column TEXT, exactly as received
   │  sql/transformations/*.sql
   ▼
Star schema (SQLite)          dim_agency · dim_product · dim_state · dim_year
                              fact_agency_product_performance · fact_agency_quote_activity
   │  sql/tests/validation_checks.sql  (16 checks, run on every build)
   ▼
┌──────────────────────── Text-to-SQL pipeline (src/ask.py) ────────────────────────┐
│ question                                                                         │
│   → LLM call 1: approved schema + metric definitions → JSON {answerable, sql,    │
│                 assumptions, reason}                                             │
│   → sql_guard: validate → run read-only with row and time limits                 │
│   → LLM call 2: explain ONLY the returned rows                                   │
└──────────────────────────────────────────────────────────────────────────────────┘
   ▲                                   ▲
 web chat (src/web_app.py + web/)    command line (python src/ask.py "...")
```

---

## Dataset

[Insurance Agency Performance (Kaggle)](https://www.kaggle.com/datasets/moneystore/agencyperformance): annual results for 1,623 agencies, 28 products (commercial and personal lines), 6 states (IN, KY, MI, OH, PA, WV), 2005–2015.

The raw file is **not** in this repository. Download `finalapi.csv` into `data/raw/`.

### What profiling found

All of these were tested with SQL in `notebooks/01_profiling.ipynb` and are enforced by checks in `sql/tests/`.

- **Grain proven:** agency × product × state × year is unique. Grouping by those columns and keeping groups with more than one row returns 0 rows, and distinct keys = total rows = 213,328.
- **Hidden snapshot columns:** 16 quote/bound columns and all agency attributes are **identical on every row of an agency across all 11 years**. Summing them multiplies the true value by the number of rows. For example, one agency with 44 rows shows 288 quotes on each, so a `SUM` gives 12,672 instead of 288. These were moved to their true level: `dim_agency`, and a separate `fact_agency_quote_activity`.
- **`99999` is a placeholder, but not everywhere:** it marks missing values in groups of columns, so it's replaced with NULL there. The one occurrence in `NB_WRTN_PREM_AMT` is kept, because it's a plausible real amount.
- **Product codes that look messy are real products:** `ANNIV   12` is a fixed-width code, not whitespace noise. The five `…12` variants exist alongside their base product for the same agency, state and year (5,615 cases), and only from 2012 onward.
- **Partial years:** 2005 has at most 8 months of data and 2015 at most 5, so they're flagged in `dim_year.is_complete_year`.
- **Stored ratios aren't reliable:** the source `LOSS_RATIO` disagrees with losses ÷ earned premium on about 31% of rows. Every aggregate ratio is recalculated from the underlying amounts.
- **Negative losses and premiums are kept:** 7,294 rows have negative incurred losses and 4,796 have negative written premium. These are consistent with recoveries, reserve releases and cancellations.

---

## Data model

Full details: [`docs/data_model.md`](docs/data_model.md). That file has the ER diagram, column classification, source-to-target mapping, `99999` decisions and known limitations.

| Table | Grain | Rows |
|---|---|---|
| `fact_agency_product_performance` | agency × product × state × year | 213,328 |
| `fact_agency_quote_activity` | agency × product line × quote platform (snapshot, no year) | 5,722 |
| `dim_agency` | one row per agency (no history in source, so no SCD Type 2) | 1,623 |
| `dim_product` | one row per product code | 28 |
| `dim_state` | one row per state | 6 |
| `dim_year` | one row per year, with a partial-year flag | 11 |

**How measures may be aggregated:**
- **Additive:** premium and loss amounts can be summed across everything.
- **Semi-additive:** policy counts are summed within a year only, never across years.
- **Non-additive:** ratios are never summed or averaged. They're recalculated, e.g. loss ratio = `SUM(losses) / NULLIF(SUM(earned premium), 0)`.

---

## LLM safety design

Generated SQL is treated as **untrusted input**. `src/sql_guard.py` applies two layers:

1. **Text checks** give clear error messages. Only one `SELECT`/`WITH` statement is allowed, with no `;`, no comments and no write keywords.
2. **The database enforces it.** The connection is read-only (`mode=ro`) with `PRAGMA query_only`, and an SQLite **authorizer** allows only reads from the six star-schema tables. Staging and system tables are blocked, even when hidden inside a CTE (a `WITH` subquery). Queries are limited to 200 rows and 5 seconds.

Further safeguards:
- The LLM **never calculates numbers**. Its explanation call receives only the rows the database returned, and is told to use only those.
- It must set `answerable: false` when the data can't answer a question.
- It must state its assumptions whenever a question is ambiguous.
- Every question, the SQL generated for it and the outcome are logged to `logs/ask_log.jsonl` (git-ignored).
- LLM calls retry with backoff on rate limits and temporary server errors, 3 retries at most.

---

## How to run it

**Requirements:** Python 3.10+, Git. No third-party packages are needed to run the app. Jupyter (`requirements-dev.txt`) is only for the profiling notebook.

```bash
# 1. Clone and set up
git clone https://github.com/Bsharma4/insurance-agency-ai-analyst.git
cd insurance-agency-ai-analyst
python -m venv .venv
source .venv/Scripts/activate          # Git Bash on Windows
# .venv\Scripts\Activate.ps1           # PowerShell
# source .venv/bin/activate            # macOS / Linux

# 2. Get the data: download finalapi.csv from Kaggle into data/raw/

# 3. Build and validate the database (about 4 seconds; expect 16 PASS lines)
python src/build_database.py

# 4. Run the safety tests
python -m unittest discover -s tests -v

# 5. Run a reviewed business query
python src/run_query.py                          # list queries
python src/run_query.py loss_ratio_by_product_line
```

### Connect an LLM (free options)

```bash
cp .env.example .env
```
Put your key in `.env`. This file is git-ignored and must never be committed. The default is the Google Gemini free tier (key from [Google AI Studio](https://aistudio.google.com/apikey)). Any OpenAI-compatible API works by changing three lines: Groq, OpenRouter, or a local Ollama model.

```bash
# Web chat: open http://127.0.0.1:8000
python src/web_app.py

# Command line
python src/ask.py "What is the loss ratio by product line for 2014?"

# Evaluation: writes evals/eval_results.csv
python src/run_eval.py
```

---

## Project structure

```
├── data/raw/                      finalapi.csv (git-ignored)
├── database/                      insurance.db (git-ignored, rebuilt by build_database.py)
├── docs/
│   ├── data_model.md              star schema, classification, source-to-target mapping, decisions
│   └── llm_schema_context.md      the approved schema and metric definitions sent to the LLM
├── evals/eval_cases.json          12 evaluation cases with reference SQL
├── notebooks/01_profiling.ipynb   step-by-step SQL profiling and grain proof
├── sql/
│   ├── ddl/                       CREATE TABLE statements
│   ├── transformations/           staging → dimensions → facts
│   ├── tests/                     16 validation checks (0 failures = healthy)
│   └── analysis/                  10 reviewed business queries
├── src/
│   ├── build_database.py          load, transform, validate
│   ├── run_query.py               run a named business query
│   ├── sql_guard.py               read-only SQL validation and execution
│   ├── llm_client.py              OpenAI-compatible client (stdlib urllib, retries)
│   ├── ask.py                     text-to-SQL pipeline + command line
│   ├── run_eval.py                evaluation against reference SQL
│   └── web_app.py                 local web server for the chat UI
├── tests/test_sql_guard.py        12 guard tests (unsafe SQL, blocked tables, limits, timeout)
└── web/index.html                 chat UI: answers, charts, tables, SQL
```

---

## Evaluation

`evals/eval_cases.json` covers:
- simple filtering
- grouped aggregation
- dimension joins
- time trends
- recalculated loss ratio
- retention
- agency ranking
- missing values
- quote-to-bind
- an ambiguous question
- an unanswerable question
- an unsafe request

A generated answer passes if its result has the same number of rows as the reference result and contains all the reference values (numbers rounded to 2 decimals). Column names, order and extra columns are ignored. Results and failure categories are written to `evals/eval_results.csv`.

<!-- After running: add the pass rate and a short failure analysis here. -->

---

## Known limitations

- The dataset has no column documentation. The meanings of the `…12` products, `MONTHS` and the system start/end years are inferred from the data.
- Agency attributes and quote counts are single snapshots with no period stated, so they can't be analyzed by year.
- Ratios with very small denominators swing wildly. For example, one product's 2014 loss ratio is over 27,000% on $1,617 of earned premium.
- LLM output varies from run to run. The guard stops unsafe SQL but can't guarantee that valid SQL reflects the intended interpretation, which is why the SQL and assumptions are always shown.
- This is a local, single-user proof of concept, with no authentication and no deployment.

## Roadmap

- [x] Foundation: repo, environment, README (`v0.1-foundation`)
- [x] Profiling, grain proof, star schema, validation, business queries
- [x] Direct LLM text-to-SQL with a safety guard, evaluation cases and a web chat
- [ ] Controlled tool-calling agent (schema lookup, distinct-value inspection, bounded retries, tool-call logging)
- [ ] Evaluation results table and failure analysis
- [ ] Demo recording and write-up

## How this was built

Built as a hands-on learning sprint. Data profiling was done step by step in the notebook, and the modeling and safety decisions are documented alongside the evidence behind them. An AI coding assistant was used as a mentor and pair programmer.

## Tech stack

Python 3 (standard library only) · SQLite · SQL · HTML/CSS/JavaScript (no framework) · Google Gemini via an OpenAI-compatible API · Git and GitHub

Data: [Kaggle, Insurance Agency Performance](https://www.kaggle.com/datasets/moneystore/agencyperformance). Used for learning and demonstration only.
