# Design decisions

## Goals

1. **The database protects itself.** Business rules live in constraints, triggers and functions, so they hold for
   every client: the web app, an admin running SQL by hand, or a buggy script.
2. **Correct under concurrency.** Two people buying the last seat, two gates scanning the same ticket, and two
   refunds of the same payment must all have exactly one winner.
3. **Explainable.** Every rule has a test, and every index has a measured query.

## Where each rule is enforced

| Rule | Mechanism | Why this mechanism |
|---|---|---|
| A room can't host two sessions at once (across all events) | `EXCLUDE USING gist (room_id WITH =, during WITH &&)` | Declarative and race-free; a trigger that checks for overlaps can miss a concurrent insert |
| Back-to-back sessions are allowed | `tstzrange(starts_at, ends_at, '[)')`: half-open ranges | 10:00–11:00 and 11:00–12:00 don't overlap |
| Never oversell | `CHECK (quantity_sold BETWEEN 0 AND quantity_total)` plus a row lock in checkout | The lock serializes buyers; the CHECK is a last line of defense even against manual `UPDATE`s |
| Ticket tiers fit the event, and the event fits the venue | Triggers (they need to read other rows) | A CHECK constraint can only see its own row |
| Event status only moves forward | Trigger on `UPDATE` | draft → published → completed, or → cancelled; never back |
| A ticket is used once | `UNIQUE (ticket_id)` on `check_ins` + `FOR UPDATE` in the scanner | Two gates at the same millisecond: one `admitted`, one `already_checked_in` (tested with 8 threads) |
| Refunds never exceed the payment | Trigger that locks the payment row, then sums | Locking first serializes concurrent refunds of the same payment |
| Only attendees can rate | Trigger checks for a checked-in ticket | Keeps ratings honest |
| Totals add up | `CHECK (total = subtotal - discount)`, `line_total` as a generated column | Arithmetic can't drift |
| One owner per organization | Partial unique index `WHERE role = 'owner'` | A rule about a subset of rows |
| One active waitlist entry per person and ticket type | Partial unique index `WHERE status IN ('waiting', 'offered')` | Past entries stay as history |
| Case-insensitive emails and promo codes | `citext` | `Ada@Example.com` and `ada@example.com` are the same account |
| Webhook replays can't record a payment twice | `UNIQUE (provider_ref)` | Idempotency |

## Checkout and concurrency

`app.purchase_tickets` is the only way tickets are created:

1. Lock the requested `ticket_types` rows with `FOR UPDATE`, **in ascending id order**. Two buyers of the same tiers
   queue instead of overselling, and because everyone locks in the same order, they can't deadlock.
2. Check the sales window, the per-order limit and availability (`total - sold - seats held for waitlist offers`).
3. Lock and apply the promo code (`FOR UPDATE`, so the last allowed use goes to exactly one buyer).
4. Insert the order, items, tickets and payment, and increment `quantity_sold`, all in one transaction.

Any failure rolls everything back: a test buys two tiers where the second is sold out and checks that no order,
ticket or inventory change remains.

Errors use custom SQLSTATE codes so an application can show the right message without parsing text:

| Code | Meaning |
|---|---|
| `EV001` | Sold out |
| `EV002` | Not on sale right now |
| `EV003` | Invalid or used-up promo code |
| `EV004` | Per-order limit exceeded |
| `EV005` | Event not open for booking |
| `EV006` | Refund not allowed |
| `EV007` | Bad request |

Isolation level: the default `READ COMMITTED` is enough because every decision is made on rows locked with
`FOR UPDATE`. That's cheaper than running every checkout under `SERIALIZABLE` and retrying on conflicts.

## Waitlist

When a refund frees seats, `offer_waitlist` walks the queue in arrival order (`FOR UPDATE SKIP LOCKED`) and makes
24-hour offers. Offered seats are **held**: they don't count as available for anyone else until the offer is
converted or expires. A person wanting 2 seats doesn't block someone behind them who wants 1 when only 1 is free.
`expire_waitlist_offers()` runs periodically, expires stale offers and offers the seats again.

## Security model

| Role | Can do |
|---|---|
| `ems_app` (backend) | Everything through the business functions; reads and writes app tables |
| `ems_organizer` (organizer staff) | Read **only their own organization's** events, orders and tickets; scan tickets; edit event title, description and status |
| `ems_analyst` (BI tools) | Read the `report` schema only |

Row-level security does the per-organization filtering. The backend runs `SET app.org_id = '42'` for the session,
and every query an organizer runs is filtered: even `SELECT * FROM app.tickets`, and even a door scan of another
organizer's ticket returns `not_found`. Without `app.org_id` set, an organizer sees nothing.

## Audit trail

A generic trigger (`audit.log_change`) records inserts, updates and deletes on events, ticket types, orders, refunds
and promo codes. Updates store **only the changed columns**, as before/after JSON, plus the database role and the
application user (`SET LOCAL app.user_id`). Example: a purchase produces
`{"quantity_sold": 0} → {"quantity_sold": 2}` for the ticket type.

## Time zones

All timestamps are `timestamptz` (stored in UTC). Each venue has an IANA time zone, validated against
`pg_timezone_names`, and `report.event_agenda` shows sessions in local time with `AT TIME ZONE`. The seed generator
builds event times in local time first, so a 9:00 keynote in Seattle and in Boston are both at 9:00 local time,
and daylight-saving changes are handled.

## Trade-offs

- **Logic in the database** keeps rules consistent for all clients, at the cost of PL/pgSQL, which is less familiar
  than application code. The tests treat the functions like an API.
- **One hot row per ticket type** gives a simple, provably correct inventory but caps throughput per ticket type at
  around 650 checkouts a second (see [performance](performance.md)). Sharding the counter would raise that at the
  cost of more complex availability checks.
- **Full refunds only.** Partial refunds (one ticket out of three) are modelled in the schema (`partially_refunded`
  status, refunds as separate rows) but not implemented in `refund_order`.
- **Payments are simulated.** A real integration would create a `pending` order, wait for the provider's webhook,
  then capture. The unique `provider_ref` already makes that webhook idempotent.
