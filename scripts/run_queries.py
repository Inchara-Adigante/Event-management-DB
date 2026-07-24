"""
Run every query in queries/analytics.sql and write the results to docs/analytics_results.md.

Usage:
    python scripts/run_queries.py [--rows 10]
"""
import argparse
import os
import re
import time
from decimal import Decimal
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]


def parse(sql_text: str):
    """Split the file into (name, question, sql) blocks."""
    blocks = re.split(r"^-- name: ", sql_text, flags=re.M)[1:]
    for block in blocks:
        name, rest = block.split("\n", 1)
        question = rest.split("\n", 1)[0].lstrip("- ").strip()
        yield name.strip(), question, rest.split("\n", 1)[1].strip()


def fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (Decimal, float)):
        return f"{v:,.2f}" if abs(v) >= 1000 else f"{v}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v).replace("|", "\\|")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=12)
    args = ap.parse_args()
    url = os.getenv("DATABASE_URL", "postgresql:///event_mgmt")
    out = ["# Analytics results", "",
           "Output of `python scripts/run_queries.py` on the seeded database "
           "(`python db/seed/generate.py --as-of 2026-07-28`). The SQL is in [queries/analytics.sql](../queries/analytics.sql).", ""]
    with psycopg.connect(url) as con:
        for name, question, sql in parse((ROOT / "queries" / "analytics.sql").read_text()):
            t0 = time.perf_counter()
            cur = con.execute(sql)
            rows = cur.fetchall()
            ms = (time.perf_counter() - t0) * 1000
            cols = [d.name for d in cur.description]
            out += [f"## {name}", f"*{question}*  ({len(rows)} rows, {ms:.0f} ms)", "",
                    "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
            out += ["| " + " | ".join(fmt(v) for v in r) + " |" for r in rows[: args.rows]]
            if len(rows) > args.rows:
                out.append(f"\n*... {len(rows) - args.rows} more rows*")
            out.append("")
            print(f"{name:<24} {len(rows):>4} rows {ms:8.1f} ms")
    (ROOT / "docs" / "analytics_results.md").write_text("\n".join(out))


if __name__ == "__main__":
    main()
