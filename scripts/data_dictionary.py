"""
Generate docs/data_dictionary.md from the live database catalog: tables, columns, types,
defaults, constraints, indexes and the COMMENT ON text written in the migrations.
The documentation can't drift from the schema because it is read from it.

Usage:
    python scripts/data_dictionary.py
"""
import os
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]

TABLES = """
SELECT c.oid, n.nspname, c.relname, obj_description(c.oid, 'pg_class'), c.reltuples::bigint,
       pg_size_pretty(pg_total_relation_size(c.oid))
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname IN ('app', 'audit') AND c.relkind = 'r'
 ORDER BY n.nspname, c.relname
"""
COLUMNS = """
SELECT a.attname, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull,
       CASE WHEN a.attgenerated = 's' THEN 'generated: ' || pg_get_expr(d.adbin, d.adrelid)
            WHEN a.attidentity <> '' THEN 'identity'
            ELSE pg_get_expr(d.adbin, d.adrelid) END,
       col_description(a.attrelid, a.attnum)
  FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
 WHERE a.attrelid = %s AND a.attnum > 0 AND NOT a.attisdropped
 ORDER BY a.attnum
"""
CONSTRAINTS = """
SELECT conname, CASE contype WHEN 'p' THEN 'primary key' WHEN 'f' THEN 'foreign key' WHEN 'u' THEN 'unique'
                             WHEN 'c' THEN 'check' WHEN 'x' THEN 'exclusion' END, pg_get_constraintdef(oid)
  FROM pg_constraint WHERE conrelid = %s ORDER BY contype, conname
"""
INDEXES = """
SELECT i.relname, pg_get_indexdef(i.oid)
  FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid
 WHERE x.indrelid = %s AND NOT x.indisprimary
   AND NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid = i.oid)
 ORDER BY i.relname
"""
TRIGGERS = """
SELECT tgname, pg_get_triggerdef(oid) FROM pg_trigger WHERE tgrelid = %s AND NOT tgisinternal ORDER BY tgname
"""
FUNCTIONS = """
SELECT n.nspname || '.' || p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')',
       CASE p.prokind WHEN 'p' THEN 'procedure' ELSE pg_get_function_result(p.oid) END,
       obj_description(p.oid, 'pg_proc')
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname IN ('app', 'report')
   AND p.prorettype <> 'trigger'::regtype
 ORDER BY 1
"""
VIEWS = """
SELECT n.nspname || '.' || c.relname, CASE c.relkind WHEN 'm' THEN 'materialized view' ELSE 'view' END,
       obj_description(c.oid, 'pg_class')
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'report' AND c.relkind IN ('v', 'm') ORDER BY 1
"""


def cell(v) -> str:
    return "" if v is None else str(v).replace("|", "\\|").replace("\n", " ")


def main() -> None:
    url = os.getenv("DATABASE_URL", "postgresql:///event_mgmt")
    out = ["# Data dictionary", "",
           "Generated from the database catalog by `python scripts/data_dictionary.py`. "
           "Row counts and sizes are from the seeded database.", ""]
    with psycopg.connect(url) as con:
        tables = con.execute(TABLES).fetchall()
        out += ["| Table | Description | Rows | Size |", "|---|---|---:|---:|"]
        out += [f"| [`{s}.{t}`](#{s}{t}) | {cell(d)} | {max(n, 0):,} | {size} |" for _, s, t, d, n, size in tables]
        out += ["", "## Views and functions", "", "| View | Kind | Description |", "|---|---|---|"]
        out += [f"| `{n}` | {k} | {cell(d)} |" for n, k, d in con.execute(VIEWS)]
        out += ["", "| Function | Returns | Description |", "|---|---|---|"]
        out += [f"| `{n}` | {cell(r)} | {cell(d)} |" for n, r, d in con.execute(FUNCTIONS)]
        for oid, schema, name, desc, _, _ in tables:
            out += ["", f'<a id="{schema}{name}"></a>', f"## {schema}.{name}", "", cell(desc), "",
                    "| Column | Type | Null | Default | Description |", "|---|---|---|---|---|"]
            out += [f"| `{c}` | {t} | {'yes' if nullable else ''} | {cell(dflt)} | {cell(cm)} |"
                    for c, t, nullable, dflt, cm in con.execute(COLUMNS, (oid,))]
            cons = con.execute(CONSTRAINTS, (oid,)).fetchall()
            if cons:
                out += ["", "**Constraints**", ""] + [f"- `{n}` ({k}): `{cell(d)}`" for n, k, d in cons]
            idx = con.execute(INDEXES, (oid,)).fetchall()
            if idx:
                out += ["", "**Indexes**", ""] + [f"- `{d}`" for _, d in idx]
            trg = con.execute(TRIGGERS, (oid,)).fetchall()
            if trg:
                out += ["", "**Triggers**", ""] + [f"- `{n}`" for n, _ in trg]
    (ROOT / "docs" / "data_dictionary.md").write_text("\n".join(out) + "\n")
    print(f"wrote docs/data_dictionary.md ({len(tables)} tables)")


if __name__ == "__main__":
    main()
