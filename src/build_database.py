"""Build the SQLite star schema from the raw Kaggle CSV.

Usage (from the project root, with .venv active):
    python src/build_database.py

Steps:
    1. Load data/raw/finalapi.csv into stg_agency_performance (all TEXT, as received)
    2. Create the star schema          (sql/ddl/*.sql)
    3. Load dimensions, then facts     (sql/transformations/*.sql, in file-name order)
    4. Run validation checks           (sql/tests/validation_checks.sql)

Uses only the Python standard library. Safe to re-run: every step rebuilds from scratch.
"""

import csv
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # project root, wherever you run from
CSV_PATH = ROOT / "data" / "raw" / "finalapi.csv"
DB_PATH = ROOT / "database" / "insurance.db"
DDL_DIR = ROOT / "sql" / "ddl"
TRANSFORM_DIR = ROOT / "sql" / "transformations"
CHECKS_FILE = ROOT / "sql" / "tests" / "validation_checks.sql"

STAGING_TABLE = "stg_agency_performance"


def load_staging(conn: sqlite3.Connection) -> int:
    """Copy the CSV into a staging table exactly as received (every column TEXT)."""
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        columns_sql = ", ".join(f'"{col}" TEXT' for col in header)
        placeholders = ", ".join("?" for _ in header)

        conn.execute(f"DROP TABLE IF EXISTS {STAGING_TABLE}")
        conn.execute(f"CREATE TABLE {STAGING_TABLE} ({columns_sql})")
        conn.executemany(f"INSERT INTO {STAGING_TABLE} VALUES ({placeholders})", reader)

    return conn.execute(f"SELECT COUNT(*) FROM {STAGING_TABLE}").fetchone()[0]


def run_sql_files(conn: sqlite3.Connection, folder: Path) -> None:
    """Run every .sql file in a folder, in file-name order (01_, 10_, 20_ ...)."""
    for sql_file in sorted(folder.glob("*.sql")):
        print(f"  running {sql_file.relative_to(ROOT)}")
        conn.executescript(sql_file.read_text(encoding="utf-8"))


def run_checks(conn: sqlite3.Connection) -> bool:
    """Run validation checks; return True only if every check has 0 failures."""
    rows = conn.execute(CHECKS_FILE.read_text(encoding="utf-8")).fetchall()
    all_passed = True
    for check_name, failures in rows:
        status = "PASS" if failures == 0 else "FAIL"
        all_passed = all_passed and failures == 0
        print(f"  [{status}] {check_name} (failures: {failures})")
    return all_passed


def main() -> int:
    if not CSV_PATH.exists():
        print(f"Missing {CSV_PATH}. Download finalapi.csv from Kaggle into data/raw/.")
        return 1

    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")   # SQLite enforces FKs only when asked

    try:
        print("1. Loading staging table ...")
        print(f"  {load_staging(conn):,} rows loaded into {STAGING_TABLE}")

        print("2. Creating star schema ...")
        run_sql_files(conn, DDL_DIR)

        print("3. Loading dimensions and facts ...")
        run_sql_files(conn, TRANSFORM_DIR)
        conn.commit()

        for table in ("dim_year", "dim_state", "dim_product", "dim_agency",
                      "fact_agency_product_performance", "fact_agency_quote_activity"):
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:34} {count:>9,} rows")

        print("4. Validation checks ...")
        ok = run_checks(conn)
    finally:
        conn.close()

    print("\nBuild succeeded." if ok else "\nBuild finished with FAILED checks.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
