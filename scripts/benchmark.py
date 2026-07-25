"""
Performance evidence for docs/performance.md.

1. Index experiments on the seeded database: each query runs with and without its index.
   The index is dropped inside a transaction that is rolled back afterwards, so the
   database is never left without it.
2. Lock contention: checkout throughput when all buyers want the same ticket type
   (one hot row) versus buyers spread over many ticket types. Runs in a scratch database.

Usage:
    python scripts/benchmark.py            # writes docs/performance_results.json
"""
import json
import os
import statistics
import sys
import threading
import time
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import migrate  # noqa: E402

URL = os.getenv("DATABASE_URL", "postgresql:///event_mgmt")
BENCH_URL = os.getenv("DATABASE_URL_BENCH", "postgresql:///event_mgmt_bench")
RUNS = 7


def plan_and_time(con, sql, params):
    """Median execution time over RUNS, plus the plan's main node and buffers of the last run."""
    times, plan = [], None
    for _ in range(RUNS):
        plan = con.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}", params).fetchone()[0][0]
        times.append(plan["Execution Time"])

    def nodes(p):
        yield p["Node Type"] + (f" on {p['Relation Name']}" if "Relation Name" in p else "") + \
            (f" using {p['Index Name']}" if "Index Name" in p else "")
        for child in p.get("Plans", []):
            yield from nodes(child)
    scans = [n for n in nodes(plan["Plan"]) if "Scan" in n]
    top = plan["Plan"]
    return dict(ms=round(statistics.median(times), 3), plan=scans,
                buffers=top.get("Shared Hit Blocks", 0) + top.get("Shared Read Blocks", 0))


def index_experiments():
    with psycopg.connect(URL) as con:
        sample = dict(
            user=con.execute("SELECT user_id FROM app.orders GROUP BY 1 ORDER BY count(*) DESC LIMIT 1").fetchone()[0],
            email=con.execute("SELECT attendee_email FROM app.tickets WHERE ticket_id = 123456").fetchone()[0],
            event=con.execute("SELECT event_id FROM app.orders GROUP BY 1 ORDER BY count(*) DESC LIMIT 1").fetchone()[0],
            item=con.execute("SELECT order_item_id FROM app.order_items WHERE quantity = 4 LIMIT 1").fetchone()[0],
            typo=con.execute("SELECT overlay(full_name placing 'xq' from 3 for 1) FROM app.users WHERE user_id = 4242").fetchone()[0],
            day=con.execute("SELECT attempted_at::date FROM app.scan_attempts ORDER BY attempted_at OFFSET 300000 LIMIT 1").fetchone()[0],
        )
        cases = [
            ("Buyer's order history (newest 20)", "orders_user_recent",
             "SELECT order_id, total, created_at FROM app.orders WHERE user_id = %(user)s ORDER BY created_at DESC LIMIT 20"),
            ("Support desk: find tickets by email", "tickets_attendee_email",
             "SELECT ticket_id, code, status FROM app.tickets WHERE attendee_email = %(email)s"),
            ("Organizer dashboard: paid orders of an event", "orders_event_status",
             "SELECT count(*), sum(total) FROM app.orders WHERE event_id = %(event)s AND status = 'paid'"),
            ("Tickets of an order line (foreign key join)", "tickets_order_item",
             "SELECT ticket_id, attendee_name FROM app.tickets WHERE order_item_id = %(item)s"),
            ("Arrival curve of one event", "check_ins_event_time",
             "SELECT date_trunc('minute', checked_in_at), count(*) FROM app.check_ins WHERE event_id = %(event)s GROUP BY 1"),
            ("Scan log for one day (BRIN)", "scan_attempts_time",
             "SELECT result, count(*) FROM app.scan_attempts WHERE attempted_at >= %(day)s::date "
             "AND attempted_at < %(day)s::date + 1 GROUP BY result"),
            ("Customer lookup with a misspelled name (trigram)", "users_name_trgm",
             "SELECT user_id, full_name, email FROM app.users WHERE full_name %% %(typo)s "
             "ORDER BY similarity(full_name, %(typo)s) DESC LIMIT 5"),
        ]
        results = []
        for label, index, sql in cases:
            with_idx = plan_and_time(con, sql, sample)
            with con.transaction(force_rollback=True):
                con.execute(f"DROP INDEX app.{index}")
                without = plan_and_time(con, sql, sample)
            size = con.execute("SELECT pg_size_pretty(pg_relation_size(%s::regclass))", (f"app.{index}",)).fetchone()[0]
            results.append(dict(query=label, index=index, index_size=size, sql=sql % {k: repr(str(v)) for k, v in sample.items()}
                                if "%(" in sql else sql, without=without, with_index=with_idx,
                                speedup=round(without["ms"] / max(with_idx["ms"], 0.001), 1)))
            print(f"{label:<48} {without['ms']:>9.2f} ms -> {with_idx['ms']:>7.3f} ms  ({results[-1]['speedup']}x)")
        brin = con.execute("SELECT pg_size_pretty(pg_relation_size('app.scan_attempts_time'))").fetchone()[0]
        with con.transaction(force_rollback=True):
            con.execute("CREATE INDEX tmp_btree ON app.scan_attempts (attempted_at)")
            btree = con.execute("SELECT pg_size_pretty(pg_relation_size('app.tmp_btree'))").fetchone()[0]
        rows = con.execute("SELECT count(*) FROM app.tickets").fetchone()[0]
    return dict(cases=results, brin_vs_btree=dict(brin=brin, btree=btree), tickets=rows)


def contention(threads=16, per_thread=150):
    """Checkout throughput: one hot ticket type vs. one ticket type per buyer thread."""
    migrate.reset_database(BENCH_URL)
    migrate.migrate(BENCH_URL)
    with psycopg.connect(BENCH_URL, autocommit=True) as con:
        con.execute("""INSERT INTO app.users (email, full_name)
                       SELECT 'buyer' || g || '@example.com', 'Buyer ' || g FROM generate_series(1, %s) g""", (threads,))
        con.execute("""
            INSERT INTO app.organizations (name, slug, contact_email) VALUES ('Bench', 'bench', 'b@example.com');
            INSERT INTO app.venues (name, address_line, city, capacity) VALUES ('Arena', '1 St', 'Boston', 100000);
            INSERT INTO app.event_categories (name) VALUES ('Concerts');
            INSERT INTO app.events (org_id, venue_id, category_id, title, slug, status, starts_at, ends_at, capacity, published_at)
                VALUES (1, 1, 1, 'Bench Concert', 'bench-concert', 'published', now() + interval '30 days',
                        now() + interval '30 days 4 hours', 100000, now());
        """)
        tiers = [con.execute("""INSERT INTO app.ticket_types (event_id, name, price, quantity_total, sales_start, sales_end)
                                VALUES (1, %s, 50, 5000, now() - interval '1 day', now() + interval '29 days')
                                RETURNING ticket_type_id""", (f"Tier {i}",)).fetchone()[0] for i in range(threads + 1)]

    def run(spread: bool) -> float:
        barrier = threading.Barrier(threads + 1)

        def worker(i):
            tt = tiers[i + 1] if spread else tiers[0]
            items = json.dumps([{"ticket_type_id": tt, "quantity": 1}])
            with psycopg.connect(BENCH_URL, autocommit=True) as c:
                barrier.wait()
                for _ in range(per_thread):
                    c.execute("SELECT app.purchase_tickets(%s, %s::jsonb)", (i + 1, items))

        ts = [threading.Thread(target=worker, args=(i,)) for i in range(threads)]
        for t in ts:
            t.start()
        barrier.wait()
        t0 = time.perf_counter()
        for t in ts:
            t.join()
        return threads * per_thread / (time.perf_counter() - t0)

    hot = run(spread=False)
    spread = run(spread=True)
    with psycopg.connect(BENCH_URL) as con:
        oversold = con.execute("SELECT count(*) FROM app.ticket_types WHERE quantity_sold > quantity_total").fetchone()[0]
        consistent = con.execute("""SELECT bool_and(quantity_sold = (SELECT count(*) FROM app.tickets t JOIN app.order_items oi
                                     USING (order_item_id) WHERE oi.ticket_type_id = tt.ticket_type_id))
                                    FROM app.ticket_types tt""").fetchone()[0]
    out = dict(threads=threads, purchases_per_run=threads * per_thread, hot_row_per_sec=round(hot),
               spread_per_sec=round(spread), oversold_ticket_types=oversold, counters_match_tickets=consistent)
    print(f"checkout throughput: one hot ticket type {hot:,.0f}/s, spread over {threads} types {spread:,.0f}/s")
    return out


def main():
    results = dict(indexes=index_experiments(), contention=contention())
    (ROOT / "docs" / "performance_results.json").write_text(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
