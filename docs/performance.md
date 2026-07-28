# Performance

All numbers come from `python scripts/benchmark.py` on the seeded database
(150,000 users, 233,422 orders, 425,486 tickets, 300,529 check-ins) running PostgreSQL 16 on a laptop-class machine.
Raw results: [performance_results.json](performance_results.json).

## 1. Every index is there for a query

Method: each query runs 7 times with its index and 7 times without it (median shown). The index is dropped inside a
transaction that is rolled back, so the database is never actually left without it.

| Query | Index | Without | With | Speedup | Pages read | Index size |
|---|---|---:|---:|---:|---:|---:|
| Buyer's order history, newest 20 | `orders (user_id, created_at DESC)` | 11.2 ms | 0.036 ms | **311×** | 3,196 → 28 | 9.1 MB |
| Support desk: tickets by email | `tickets (attendee_email)` | 97.2 ms | 0.022 ms | **4,418×** | 6,656 → 4 | 28 MB |
| Organizer dashboard: paid orders of an event | `orders (event_id, status)` | 9.3 ms | 0.43 ms | **22×** | 3,120 → 31 | 2.1 MB |
| Tickets of an order line (FK join) | `tickets (order_item_id)` | 12.5 ms | 0.007 ms | **1,791×** | 6,656 → 4 | 7.4 MB |
| Arrival curve of one event | `check_ins (event_id, checked_in_at)` | 11.6 ms | 0.93 ms | **12×** (index-only scan) | 2,880 → 21 | 12 MB |
| Scan log for one day | BRIN `scan_attempts (attempted_at)` | 14.1 ms | 1.24 ms | **11×** | 2,982 → 130 | **24 kB** |
| Customer lookup with a misspelled name | GIN trigram `users (full_name)` | 269 ms | 4.3 ms | **62×** | 2,200 → 501 | 10 MB |

What the numbers show:

- **Foreign keys need their own indexes.** PostgreSQL indexes primary keys and unique constraints automatically, but
  not the referencing side of a foreign key. Without `tickets (order_item_id)`, showing the tickets of one order reads
  the whole 117 MB tickets table.
- **Column order matters.** `orders (user_id, created_at DESC)` returns a buyer's newest orders already sorted, so
  `LIMIT 20` stops after 20 index entries instead of sorting everything.
- **Covering indexes avoid the table.** The arrival-curve query only needs `event_id` and `checked_in_at`, both in the
  index, so PostgreSQL never touches the table (index-only scan).
- **BRIN fits append-only logs.** For the time-ordered scan log, a BRIN index of 24 kB gives an 11× speedup.
  A B-tree on the same column is 6.8 MB, **280× larger**.

### A lesson from the BRIN index

The first BRIN measurement was *slower* than no index (0.6×). `EXPLAIN (ANALYZE, BUFFERS)` showed
`Heap Blocks: lossy=2816` out of 2,944: the index had been created on an empty table, and block ranges written by a
bulk `COPY` are only summarized by `VACUUM`. Unsummarized ranges must always be read. Two fixes:

1. `CREATE INDEX ... USING brin (...) WITH (autosummarize = on)` so ranges are summarized as they fill up;
2. the seed loader ends with `VACUUM ANALYZE`.

BRIN also only helps when the physical row order follows the indexed column (here `correlation = 1.0` in `pg_stats`),
which is why the seed writes the scan log in time order, as a real door system would.

### Indexes I didn't benchmark, and why

`events_upcoming` (partial), `events_search` (GIN full-text) and `events_title_trgm` exist for the public event
pages. With 1,000 events the whole table is 128 pages, and the planner correctly prefers a sequential scan. These
indexes start paying off as the catalog grows; they're cheap to keep because events change rarely.

## 2. Lock contention: the hot ticket type

Checkout locks the `ticket_types` row it sells from (`SELECT ... FOR UPDATE`). That is what makes overselling
impossible, but it also means buyers of the *same* ticket type are served one at a time.

16 concurrent buyers, 2,400 purchases per run, in a scratch database:

| Scenario | Checkouts per second |
|---|---:|
| Everyone buys the same ticket type (one hot row) | **644 / s** |
| Each buyer buys a different ticket type of the same event | **2,123 / s** (3.3×) |

In both runs: **0 oversold ticket types**, and every `quantity_sold` counter equals the number of tickets actually
issued. Correctness never depends on the load; only throughput does.

What this means in practice:

- 644 checkouts a second on one ticket type is about **2.3 million an hour**: enough for nearly any event.
- For a stadium on-sale (tens of thousands of buyers in the first minute), the next step is to stop all buyers
  queueing on one row: split the inventory into several sub-pools (like sharded counters), or put buyers in a
  virtual waiting room and admit them at a rate the database can sustain.

## 3. Bulk loading

The seed generator loads about 2 million rows in about 45 seconds **with every constraint and trigger enabled**, so a
successful load is itself proof that the generated data obeys all business rules.

One thing I had to fix: the integrity triggers query other tables, and inside one big load transaction those tables
had no statistics yet. The planner assumed they were empty and chose sequential scans, so the feedback trigger ran a
full scan of the tickets table for every rating and the load took over 10 minutes. Running `ANALYZE` on each table
right after its `COPY` brought the whole load back to about 45 seconds.
