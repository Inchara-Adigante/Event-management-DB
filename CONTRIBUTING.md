# Contributing

Thanks for your interest! Issues and pull requests are welcome.

## Set up

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
docker compose up -d            # or use a local PostgreSQL 16
make setup && make test         # 47 tests, about 15 seconds
```

## Ground rules

- **Schema changes go in a new migration** (`db/migrations/011_*.sql`). Never edit a migration that has already been
  applied: `scripts/migrate.py` checks a SHA-256 of each file and refuses edited ones.
- **Every rule gets a test.** If you add a constraint, trigger or function, add a test in `tests/` that shows it
  rejecting bad data. Concurrency rules need a race test (see `_race` in `tests/test_purchase.py`).
- **Every index gets a query.** Add the query to `scripts/benchmark.py` and the measured result to
  `docs/performance.md`.
- Regenerate the docs with `make docs` when the schema changes.

## Good first contributions

- **Partial refunds:** refund one ticket of a multi-ticket order (the schema already has a
  `partially_refunded` status).
- **Seat maps:** add reserved seating (`seats` table, one ticket per seat) with a unique constraint and a race test.
- **Pending payments:** create a `pending` order, then capture it from a simulated payment webhook (idempotent on
  `provider_ref`).
- **More analytics:** a new business question in `queries/analytics.sql`.

## Background reading

[How ticket sites stop two people booking the same seat](https://github.com/Inchara-Adigante/Lets-Learn/blob/main/system-design/how-seat-booking-works.md)
explains the locking and constraint patterns used here.
