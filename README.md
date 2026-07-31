# Event Management Database

[![CI](https://github.com/Inchara-Adigante/Event-management-DB/actions/workflows/ci.yml/badge.svg)](https://github.com/Inchara-Adigante/Event-management-DB/actions/workflows/ci.yml)

A PostgreSQL database for an event ticketing platform (think Eventbrite): organizers, venues and rooms, events
and agendas, speakers, ticket tiers, promo codes, orders, payments, refunds, waitlists, door check-ins and ratings.

The focus is a database that **protects its own data**. The rules (no double-booked rooms, no overselling, refunds
never above payments, a ticket used only once) are enforced by constraints, triggers and transactional functions,
and they hold even when hundreds of people buy the last tickets at the same moment.

Built in Summer 2026 as a database design project.

| | |
|---|---|
| **Schema** | 22 tables in 3 schemas, 10 versioned migrations, 7 enum types, 27 indexes each tied to a query or rule |
| **Logic** | 11 functions and procedures, 14 triggers, 5 reporting views (1 materialized) |
| **Security** | 3 least-privilege roles, row-level security per organization, full audit trail |
| **Data** | Realistic generator: 150k users, 1,000 events in 15 US cities, ~2 million rows |
| **Quality** | 47 automated tests (including concurrency races), CI on every push |
| **Analysis** | 18 business questions in SQL, indexes measured with `EXPLAIN ANALYZE` |

## Data model

```mermaid
erDiagram
    ORGANIZATIONS ||--o{ EVENTS : hosts
    VENUES ||--o{ ROOMS : contains
    VENUES ||--o{ EVENTS : "takes place at"
    EVENTS ||--o{ SESSIONS : agenda
    ROOMS ||--o{ SESSIONS : "booked for"
    SPEAKERS }o--o{ SESSIONS : presents
    EVENTS ||--o{ TICKET_TYPES : sells
    USERS ||--o{ ORDERS : places
    ORDERS ||--|{ ORDER_ITEMS : contains
    TICKET_TYPES ||--o{ ORDER_ITEMS : "sold as"
    ORDER_ITEMS ||--|{ TICKETS : issues
    ORDERS ||--o{ PAYMENTS : "paid by"
    PAYMENTS ||--o{ REFUNDS : "returned by"
    TICKETS ||--o| CHECK_INS : "used at door"
    TICKET_TYPES ||--o{ WAITLIST : "queue for"
    EVENTS ||--o{ FEEDBACK : "rated in"
```

Full diagram with columns: [docs/erd.md](docs/erd.md) · every column and constraint: [docs/data_dictionary.md](docs/data_dictionary.md)

## What the database guarantees

| Rule | How it's enforced |
|---|---|
| A room is never double-booked, even across different events | Exclusion constraint on `(room_id, tstzrange)` |
| Tickets are never oversold, even with 40 buyers racing for 25 seats | Row lock in checkout + `CHECK (quantity_sold <= quantity_total)` |
| The last use of a promo code goes to exactly one buyer | Row lock on the promo code |
| A ticket gets in once, even if two gates scan it at the same instant | `UNIQUE (ticket_id)` on check-ins + row lock in the scanner |
| Refunds never exceed what was paid | Trigger that locks the payment before summing refunds |
| Ticket tiers fit the event, and the event fits the venue | Triggers |
| Sessions stay inside their event's time and venue | Trigger |
| Only people who checked in can rate an event | Trigger |
| Event status only moves forward (draft → published → completed) | Trigger |
| Organizers only ever see their own events, orders and tickets | Row-level security |
| Every change to money and inventory is recorded | Generic audit trigger (changed columns only) |

Details and trade-offs: [docs/design.md](docs/design.md)

## Using it

The application talks to the database through functions, so every rule runs every time:

```sql
-- Buy 2 General Admission tickets with a promo code
SELECT app.purchase_tickets(
    p_user_id    => 1042,
    p_items      => '[{"ticket_type_id": 87, "quantity": 2}]',
    p_promo_code => 'friends20');          -- returns the order id

-- Sold out? Errors carry a code the app can map to a message:
--   ERROR:  "VIP" sold out: 2 requested, 0 available      SQLSTATE: EV001

SELECT app.join_waitlist(1042, 87);              -- queue for a sold-out tier
SELECT app.refund_order(5531, 'Schedule conflict');   -- seats go back and are offered to the waitlist

-- At the door
SELECT app.check_in_ticket('7f9c4b1e-...'::uuid, p_event_id => 311, p_gate => 'Gate A');
--  admitted | already_checked_in | cancelled | not_found | wrong_event | too_early

-- An organizer's staff only see their own organization
SET ROLE ems_organizer;
SET app.org_id = '12';
SELECT count(*) FROM app.tickets;                -- only org 12's tickets
```

## Results

### Analytics ([all 18 questions](queries/analytics.sql) · [results](docs/analytics_results.md))

Run on the generated data set (as of 2026-07-28):

- **Free events lose a third of their audience:** 63% of free tickets are used, against about 90% of paid tickets.
- **Early Bird sells best:** 77% sell-through, against 58% for General Admission and 47% for VIP.
- **Better-rated events sell more:** rating and sell-through correlate at 0.4 to 0.7 in most categories.
- **Arrivals peak in the last half hour before the start:** half of all attendees are in by 15 minutes before
  the start, and the busiest gate scans about 18 people a minute. Useful for staffing.
- **Loyalty:** 44% of buyers came once, 32% twice; a small core attends 5 or more events.
- **Unmet demand:** some sold-out tiers have waitlists larger than the tier itself (VIP: 33 seats, 55 wanted).

SQL features used: window functions (`LAG`, running totals, `rank`, `row_number`), recursive CTE over the category
tree, `ROLLUP`, `FILTER` pivots, `percentile_cont`, `corr`, `date_bin`, full-text search with `ts_rank`, trigram
similarity.

### Performance ([details](docs/performance.md))

| Query | Without index | With index |
|---|---:|---:|
| Support desk: find tickets by email (425k tickets) | 97 ms | **0.02 ms** |
| Tickets of an order (foreign-key join) | 12.5 ms | **0.007 ms** |
| Buyer's order history, newest first | 11.2 ms | **0.036 ms** |
| Customer lookup with a misspelled name (trigram) | 269 ms | **4.3 ms** |
| Scan log for one day (BRIN, 24 kB vs 6.8 MB B-tree) | 14.1 ms | **1.2 ms** |

Lock contention: 16 concurrent buyers manage 644 checkouts/s on one hot ticket type and 2,123/s when spread over
16 types, with 0 oversold tickets in every run.

## Run it

Requirements: Python 3.11+ and PostgreSQL 16 (local, or `docker compose up -d`).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/event_mgmt   # for docker compose

make setup     # create the database and apply the 10 migrations
make seed      # ~2 million rows of realistic data, about 90 seconds
make test      # 47 tests, about 15 seconds
make queries   # 18 analytics questions -> docs/analytics_results.md
make bench     # index and contention experiments -> docs/performance_results.json
make docs      # regenerate docs/data_dictionary.md from the live schema
```

`scripts/migrate.py` records each applied migration with a SHA-256 checksum: re-running it is a no-op, and editing a
migration that already ran is refused.

## Project structure

```
Event-management-DB/
├── db/
│   ├── migrations/
│   │   ├── 001_foundation.sql          extensions, schemas, enum types
│   │   ├── 002_core.sql                users, organizations, venues, rooms, events, sessions, speakers
│   │   ├── 003_ticketing.sql           ticket types, promo codes, orders, payments, refunds, tickets
│   │   ├── 004_operations.sql          check-ins, scan log, waitlist, feedback
│   │   ├── 005_integrity_triggers.sql  cross-table business rules
│   │   ├── 006_business_functions.sql  checkout, refunds, waitlist, door scanning
│   │   ├── 007_audit.sql               change history
│   │   ├── 008_reporting.sql           reporting views, materialized daily revenue
│   │   ├── 009_security.sql            roles and row-level security
│   │   └── 010_indexes.sql             indexes, each tied to a query
│   └── seed/generate.py                realistic, deterministic data generator
├── queries/analytics.sql               18 business questions
├── scripts/
│   ├── migrate.py                      migration runner with checksums
│   ├── run_queries.py                  runs the analytics, writes the results doc
│   ├── benchmark.py                    index and lock-contention experiments
│   └── data_dictionary.py              docs generated from the catalog
├── tests/                              47 tests: constraints, checkout, concurrency, refunds,
│                                       waitlist, door, audit, RLS, reports, migrations, seed
├── docs/                               ERD, data dictionary, design, performance, analytics results
├── docker-compose.yml · Makefile · .github/workflows/ci.yml
```

## Tech

PostgreSQL 16 (PL/pgSQL, `citext`, `btree_gist`, `pg_trgm`, `pgcrypto`), Python 3 with psycopg 3, pytest, Faker,
GitHub Actions.
