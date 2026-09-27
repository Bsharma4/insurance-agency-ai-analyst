"""Evaluate the text-to-SQL pipeline against hand-written reference SQL.

Usage:
    python src/run_eval.py            # all cases
    python src/run_eval.py E05 E10    # selected cases

For each case: ask the LLM for SQL, run it through the guard, run the reference
SQL, compare the two result sets, and write evals/eval_results.csv.

Comparison rule: same number of rows, and every reference column's values appear
in some generated column (numbers rounded to 2 decimals). Column names, order and
extra columns are ignored. That checks the *numbers*, not the exact SQL text.
"""

import csv
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

from ask import DB_PATH, generate_sql
from sql_guard import UnsafeQueryError, run_readonly

ROOT = Path(__file__).resolve().parent.parent
CASES_FILE = ROOT / "evals" / "eval_cases.json"
RESULTS_FILE = ROOT / "evals" / "eval_results.csv"


def columns_of(rows: list[tuple]) -> list[list]:
    """Each column as a sorted list of values, numbers rounded to 2 decimals."""
    def cell(v):
        return round(float(v), 2) if isinstance(v, (int, float)) else str(v)
    return [sorted((cell(r[i]) for r in rows), key=str) for i in range(len(rows[0]))] if rows else []


def results_match(generated: list[tuple], reference: list[tuple]) -> bool:
    """Same number of rows, and every reference column appears somewhere in the generated result.

    Extra generated columns (e.g. earned premium shown next to a loss ratio) are allowed;
    column names, column order and row order are ignored.
    """
    if len(generated) != len(reference):
        return False
    gen_cols = columns_of(generated)
    return all(ref_col in gen_cols for ref_col in columns_of(reference))


def evaluate(case: dict) -> dict:
    result = {"id": case["id"], "category": case["category"], "question": case["question"],
              "expected": case["expected"], "reference_sql": case.get("reference_sql") or "",
              "generated_sql": "", "outcome": "", "passed": False, "failure_category": "", "note": ""}
    try:
        plan = generate_sql(case["question"])
    except Exception as e:
        result.update(outcome="llm_error", failure_category="llm_error", note=str(e)[:200])
        return result

    result["generated_sql"] = plan.get("sql", "")
    result["note"] = "; ".join(plan.get("assumptions", [])) or plan.get("reason", "")

    if not plan.get("answerable") or not plan.get("sql"):
        result["outcome"] = "not_answerable"
        result["passed"] = case["expected"] in ("not_answerable", "not_answerable_or_rejected")
        result["failure_category"] = "" if result["passed"] else "false_refusal"
        return result

    try:
        _, gen_rows, _ = run_readonly(DB_PATH, plan["sql"], max_rows=1000)
    except UnsafeQueryError as e:
        result.update(outcome="rejected", note=str(e))
        result["passed"] = case["expected"] == "not_answerable_or_rejected"
        result["failure_category"] = "" if result["passed"] else "guard_rejected"
        return result
    except sqlite3.Error as e:
        result.update(outcome="sql_error", failure_category="invalid_sql", note=str(e))
        return result

    result["outcome"] = "answered"
    if case["expected"] == "answer":
        _, ref_rows, _ = run_readonly(DB_PATH, case["reference_sql"], max_rows=1000)
        result["passed"] = results_match(gen_rows, ref_rows)
        result["failure_category"] = "" if result["passed"] else "wrong_result"
    elif case["expected"] == "answer_with_assumptions":
        result["passed"] = bool(plan.get("assumptions"))
        result["failure_category"] = "" if result["passed"] else "no_assumptions_stated"
    else:  # expected a refusal but got an answer
        result["failure_category"] = "should_have_refused"
    return result


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    if len(sys.argv) > 1:
        cases = [c for c in cases if c["id"] in sys.argv[1:]]

    delay = float(os.environ.get("EVAL_DELAY_SECONDS", "4"))  # stay under free-tier rate limits
    results = []
    for i, case in enumerate(cases):
        if i:
            time.sleep(delay)
        r = evaluate(case)
        results.append(r)
        print(f"{r['id']}  {'PASS' if r['passed'] else 'FAIL'}  {r['category']:24} {r['outcome']:15} {r['failure_category']}")

    with RESULTS_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    passed = sum(r["passed"] for r in results)
    print(f"\n{passed}/{len(results)} passed. Details: {RESULTS_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
