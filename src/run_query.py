"""Run a named query from sql/analysis/business_queries.sql and print it as a table.

Usage:
    python src/run_query.py                  # list available query names
    python src/run_query.py loss_ratio_by_year
"""

import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "database" / "insurance.db"
QUERIES_FILE = ROOT / "sql" / "analysis" / "business_queries.sql"


def load_named_queries(path: Path) -> dict[str, str]:
    """Split the file on '-- name: <query_name>' lines."""
    parts = re.split(r"^-- name:\s*(\w+)\s*$", path.read_text(encoding="utf-8"), flags=re.M)
    # parts = [preamble, name1, body1, name2, body2, ...]
    return {name: body.strip() for name, body in zip(parts[1::2], parts[2::2])}


def print_table(columns: list[str], rows: list[tuple]) -> None:
    cells = [[("" if v is None else str(v)) for v in row] for row in rows]
    widths = [max(len(c), *(len(r[i]) for r in cells)) if cells else len(c) for i, c in enumerate(columns)]
    print("  ".join(c.ljust(w) for c, w in zip(columns, widths)))
    print("  ".join("-" * w for w in widths))
    for r in cells:
        print("  ".join(v.rjust(w) for v, w in zip(r, widths)))
    print(f"({len(rows)} rows)")


def main() -> int:
    queries = load_named_queries(QUERIES_FILE)
    if len(sys.argv) < 2 or sys.argv[1] not in queries:
        print("Available queries:\n  " + "\n  ".join(queries))
        return 1

    conn = sqlite3.connect(DB_PATH.as_uri() + "?mode=ro", uri=True)  # read-only
    cur = conn.execute(queries[sys.argv[1]])
    print_table([d[0] for d in cur.description], cur.fetchall())
    return 0


if __name__ == "__main__":
    sys.exit(main())
