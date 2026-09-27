"""Tests for the SQL safety guard. Run from the project root:
    python -m unittest discover -s tests -v
Requires the database to be built first (python src/build_database.py).
"""

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sql_guard import UnsafeQueryError, check_sql, run_readonly  # noqa: E402

DB_PATH = ROOT / "database" / "insurance.db"


class TextChecks(unittest.TestCase):
    def test_simple_select_allowed(self):
        self.assertEqual(check_sql("SELECT 1;"), "SELECT 1")

    def test_with_query_allowed(self):
        check_sql("WITH t AS (SELECT 1 AS x) SELECT x FROM t")

    def test_replace_function_allowed(self):
        check_sql("SELECT REPLACE(product_code, ' ', '') FROM dim_product")

    def test_rejections(self):
        unsafe = [
            "",
            "DELETE FROM dim_state",
            "DROP TABLE dim_year",
            "UPDATE dim_state SET state_name = 'x'",
            "INSERT INTO dim_state VALUES (9, 'XX', 'x')",
            "SELECT 1; DROP TABLE dim_year",
            "SELECT 1 -- hidden comment",
            "PRAGMA table_info(dim_year)",
            "ATTACH DATABASE 'x.db' AS x",
            "WITH t AS (SELECT 1) DELETE FROM dim_state",
            "CREATE TABLE x (a)",
        ]
        for sql in unsafe:
            with self.subTest(sql=sql), self.assertRaises(UnsafeQueryError):
                check_sql(sql)


@unittest.skipUnless(DB_PATH.exists(), "build the database first")
class ExecutionChecks(unittest.TestCase):
    def test_query_runs(self):
        cols, rows, truncated = run_readonly(DB_PATH, "SELECT COUNT(*) AS n FROM dim_state")
        self.assertEqual(cols, ["n"])
        self.assertEqual(rows, [(6,)])
        self.assertFalse(truncated)

    def test_row_limit(self):
        _, rows, truncated = run_readonly(DB_PATH, "SELECT agency_id FROM dim_agency", max_rows=5)
        self.assertEqual(len(rows), 5)
        self.assertTrue(truncated)

    def test_cte_allowed(self):
        _, rows, _ = run_readonly(DB_PATH, "WITH t AS (SELECT year_key FROM dim_year) SELECT COUNT(*) FROM t")
        self.assertEqual(rows, [(11,)])

    def test_cte_cannot_hide_blocked_table(self):
        with self.assertRaises(UnsafeQueryError):
            run_readonly(DB_PATH, "WITH x AS (SELECT * FROM stg_agency_performance) SELECT * FROM x")

    def test_staging_table_not_allowed(self):
        with self.assertRaises(UnsafeQueryError):
            run_readonly(DB_PATH, "SELECT * FROM stg_agency_performance")

    def test_system_table_not_allowed(self):
        with self.assertRaises(UnsafeQueryError):
            run_readonly(DB_PATH, "SELECT name FROM sqlite_master")

    def test_timeout(self):
        slow = ("WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) "
                "SELECT COUNT(*) FROM n")
        with self.assertRaises(UnsafeQueryError):
            run_readonly(DB_PATH, slow, timeout_seconds=0.5)

    def test_bad_column_is_sql_error_not_guard_error(self):
        with self.assertRaises(sqlite3.OperationalError):
            run_readonly(DB_PATH, "SELECT no_such_column FROM dim_state")


if __name__ == "__main__":
    unittest.main()
