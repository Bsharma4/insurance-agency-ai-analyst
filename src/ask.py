"""Ask an insurance question in plain English; get validated SQL, results and a grounded answer.

Usage:
    python src/ask.py "What was the loss ratio by product line in 2014?"
    python src/ask.py            # interactive mode, empty line to quit

Flow (no agent yet - a fixed pipeline):
    question
      -> LLM call 1: approved schema + question -> JSON {answerable, sql, assumptions}
      -> sql_guard: validate, then run read-only with row/time limits
      -> show SQL and result table
      -> LLM call 2: question + SQL + returned rows -> explanation of those rows only
Every run is appended to logs/ask_log.jsonl.
"""

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from llm_client import chat, parse_json_reply
from sql_guard import UnsafeQueryError, run_readonly

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "database" / "insurance.db"
SCHEMA_CONTEXT = (ROOT / "docs" / "llm_schema_context.md").read_text(encoding="utf-8")
LOG_FILE = ROOT / "logs" / "ask_log.jsonl"

MAX_ROWS = 200            # rows returned by the database
ROWS_SENT_TO_LLM = 50     # rows the explainer sees

SQL_SYSTEM_PROMPT = f"""You translate business questions into SQLite SQL for an insurance analytics database.

{SCHEMA_CONTEXT}

Respond with ONLY a JSON object, no other text:
{{
  "answerable": true or false,
  "sql": "one SQLite SELECT or WITH query, or empty string if not answerable",
  "assumptions": ["each interpretation you made, e.g. which years or definition you used"],
  "reason": "if not answerable: why the data cannot answer it; otherwise empty string"
}}

SQL requirements:
- Exactly one SELECT (or WITH ... SELECT) statement. No semicolons, no comments.
- Use only the tables and columns listed above, with the metric definitions above.
- Give result columns clear aliases, e.g. AS loss_ratio.
- Add ORDER BY for rankings and trends, and LIMIT for "top N" questions.
- If the question is ambiguous, choose the most reasonable interpretation and state it in assumptions.
- If the question needs data that does not exist in these tables, set answerable to false.
"""

EXPLAIN_SYSTEM_PROMPT = """You explain SQL query results to an insurance business user.

Rules:
- Use ONLY the numbers in the provided result rows. Do not invent, estimate or recalculate totals.
- If the rows are empty or do not answer the question, say so plainly.
- Mention the assumptions you were given, and note partial years (2005, 2015) if they appear.
- If results were truncated, say that only part of the result is shown.
- Keep it to a short paragraph or a few bullets. Plain language, no SQL.
"""


def generate_sql(question: str) -> dict:
    reply = chat([
        {"role": "system", "content": SQL_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ])
    plan = parse_json_reply(reply)
    plan.setdefault("assumptions", [])
    return plan


def explain(question: str, sql: str, assumptions: list, columns: list, rows: list, truncated: bool) -> str:
    payload = {
        "question": question,
        "sql": sql,
        "assumptions": assumptions,
        "columns": columns,
        "rows": [list(r) for r in rows[:ROWS_SENT_TO_LLM]],
        "rows_shown_to_you": min(len(rows), ROWS_SENT_TO_LLM),
        "total_rows_returned": len(rows),
        "truncated_by_row_limit": truncated,
    }
    return chat([
        {"role": "system", "content": EXPLAIN_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, default=str)},
    ])


def print_table(columns: list, rows: list, limit: int = 20) -> None:
    cells = [["" if v is None else str(v) for v in r] for r in rows[:limit]]
    widths = [max([len(c)] + [len(r[i]) for r in cells]) for i, c in enumerate(columns)]
    print("  ".join(c.ljust(w) for c, w in zip(columns, widths)))
    print("  ".join("-" * w for w in widths))
    for r in cells:
        print("  ".join(v.rjust(w) for v, w in zip(r, widths)))
    if len(rows) > limit:
        print(f"... {len(rows) - limit} more rows")


def log(entry: dict) -> None:
    LOG_FILE.parent.mkdir(exist_ok=True)
    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def answer(question: str) -> dict:
    """Run the full pipeline for one question and return a result record (no printing).

    Used by both the command line (ask) and the web app (web_app.py).
    status is one of: ok, not_answerable, rejected, sql_error.
    """
    record = {"question": question, "status": None, "sql": "", "assumptions": [],
              "reason": "", "error": "", "columns": [], "rows": [], "truncated": False, "answer": ""}

    plan = generate_sql(question)
    record.update(plan)

    if not plan.get("answerable") or not plan.get("sql"):
        record["status"] = "not_answerable"
        record["reason"] = plan.get("reason") or "No reason given."
        return record

    try:
        columns, rows, truncated = run_readonly(DB_PATH, plan["sql"], max_rows=MAX_ROWS)
    except UnsafeQueryError as e:
        record.update(status="rejected", error=str(e))
        return record
    except sqlite3.Error as e:
        record.update(status="sql_error", error=str(e))
        return record

    record.update(columns=columns, rows=[list(r) for r in rows], truncated=truncated)
    record["answer"] = explain(question, plan["sql"], plan["assumptions"], columns, rows, truncated)
    record["status"] = "ok"
    return record


def print_record(record: dict) -> None:
    """Command-line display of a result record."""
    if record["status"] == "not_answerable":
        print(f"\nCannot answer from this data: {record['reason']}")
        return
    print("\nGenerated SQL:\n" + record["sql"])
    if record["assumptions"]:
        print("\nAssumptions:\n- " + "\n- ".join(record["assumptions"]))
    if record["status"] == "rejected":
        print(f"\nREJECTED by SQL guard: {record['error']}")
    elif record["status"] == "sql_error":
        print(f"\nSQL error: {record['error']}")
    else:
        rows = record["rows"]
        print(f"\nResults ({len(rows)} rows{', truncated' if record['truncated'] else ''}):")
        print_table(record["columns"], rows)
        print("\nAnswer:\n" + record["answer"])


def ask(question: str) -> dict:
    record = answer(question)
    print_record(record)
    return record


def log_record(record: dict) -> None:
    """Log a record without the full result rows (keeps the log small)."""
    entry = {k: v for k, v in record.items() if k != "rows"}
    entry["row_count"] = len(record.get("rows", []))
    entry["rows_preview"] = record.get("rows", [])[:10]
    log(entry)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows terminals + LLM text
    if not DB_PATH.exists():
        print("Database not found. Run: python src/build_database.py")
        return 1

    questions = [" ".join(sys.argv[1:])] if len(sys.argv) > 1 else None
    while True:
        question = questions.pop() if questions else input("\nQuestion (blank to quit): ").strip()
        if not question:
            return 0
        try:
            log_record(ask(question))
        except Exception as e:  # API/network/JSON problems: report and keep going
            print(f"\nError: {e}")
            log({"question": question, "status": "error", "error": str(e)})
        if len(sys.argv) > 1:
            return 0


if __name__ == "__main__":
    sys.exit(main())
