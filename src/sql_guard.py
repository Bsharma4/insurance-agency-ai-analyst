"""Safety layer between LLM-generated SQL and the database.

Two layers of defense:
  1. check_sql()    - text checks before anything runs (one read-only statement only)
  2. run_readonly() - executes with the database itself enforcing read-only access:
       * read-only connection (mode=ro) + PRAGMA query_only
       * an authorizer that only allows SELECT / READ on approved tables
       * a row limit and a time limit

Layer 1 gives clear error messages. Layer 2 is the real guarantee: even if a
trick gets past the text checks, SQLite itself refuses to write.
"""

import re
import sqlite3
import time
from pathlib import Path

ALLOWED_TABLES = {
    "fact_agency_product_performance",
    "fact_agency_quote_activity",
    "dim_agency",
    "dim_product",
    "dim_state",
    "dim_year",
}

FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|PRAGMA|VACUUM|REINDEX|TRIGGER|REPLACE\s+INTO)\b",
    re.IGNORECASE,
)

MAX_SQL_LENGTH = 5000


class UnsafeQueryError(Exception):
    """Raised when SQL is rejected before or during execution."""


def check_sql(sql: str) -> str:
    """Return cleaned SQL if it is a single read-only SELECT/WITH query, else raise."""
    if not sql or not sql.strip():
        raise UnsafeQueryError("Empty query.")
    if len(sql) > MAX_SQL_LENGTH:
        raise UnsafeQueryError(f"Query longer than {MAX_SQL_LENGTH} characters.")

    cleaned = sql.strip().rstrip(";").strip()

    if ";" in cleaned:
        raise UnsafeQueryError("Multiple statements are not allowed (found ';').")
    if "--" in cleaned or "/*" in cleaned:
        raise UnsafeQueryError("SQL comments are not allowed.")

    first_word = cleaned.split(None, 1)[0].upper()
    if first_word not in ("SELECT", "WITH"):
        raise UnsafeQueryError(f"Only SELECT or WITH queries are allowed (got '{first_word}').")

    match = FORBIDDEN_KEYWORDS.search(cleaned)
    if match:
        raise UnsafeQueryError(f"Forbidden keyword: {match.group(0).upper()}.")

    return cleaned


def _make_authorizer(real_tables: set[str]):
    """Build the callback SQLite calls for every operation while compiling a statement."""

    def authorizer(action, arg1, arg2, db_name, trigger):
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:  # arg1 = table (or CTE) name being read
            if arg1 in ALLOWED_TABLES:
                return sqlite3.SQLITE_OK
            # Names that are not real tables are CTEs defined inside the query itself.
            return sqlite3.SQLITE_DENY if arg1 in real_tables else sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION:  # SUM, ROUND, COALESCE, ...
            return sqlite3.SQLITE_OK
        if action == getattr(sqlite3, "SQLITE_RECURSIVE", 33):  # WITH RECURSIVE
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY  # everything else: writes, pragmas, attach ...

    return authorizer


def run_readonly(db_path: Path, sql: str, max_rows: int = 200, timeout_seconds: float = 5.0):
    """Validate and run a query. Returns (columns, rows, truncated)."""
    cleaned = check_sql(sql)

    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.execute("PRAGMA query_only = ON")
        real_tables = {name for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")} | {"sqlite_master", "sqlite_schema"}
        conn.set_authorizer(_make_authorizer(real_tables))

        deadline = time.monotonic() + timeout_seconds
        # Called every 10,000 SQLite VM steps; returning True aborts the query.
        conn.set_progress_handler(lambda: time.monotonic() > deadline, 10_000)

        try:
            cur = conn.execute(cleaned)
            columns = [d[0] for d in cur.description]
            rows = cur.fetchmany(max_rows + 1)
        except sqlite3.DatabaseError as e:
            msg = str(e)
            if "interrupted" in msg:
                raise UnsafeQueryError(f"Query exceeded {timeout_seconds}s time limit.") from e
            if "prohibited" in msg or "not authorized" in msg:
                raise UnsafeQueryError(f"Access denied by database guard: {msg}") from e
            raise  # ordinary SQL error (bad column name, syntax) - caller reports it

        truncated = len(rows) > max_rows
        return columns, rows[:max_rows], truncated
    finally:
        conn.close()
