# Data dictionary

Generated from the database catalog by `python scripts/data_dictionary.py`. Row counts and sizes are from the seeded database.

| Table | Description | Rows | Size |
|---|---|---:|---:|
| [`app.check_ins`](#appcheck_ins) | Successful door scans; the UNIQUE ticket_id makes a second entry on the same ticket impossible | 300,529 | 48 MB |
| [`app.event_categories`](#appevent_categories) | Category tree, e.g. Technology > Data > Databases (queried recursively) | 23 | 80 kB |
| [`app.events`](#appevents) | An event hosted by one organization at one venue | 1,000 | 2280 kB |
| [`app.feedback`](#appfeedback) | Post-event ratings; only people who actually checked in may rate (trigger) | 51,605 | 7128 kB |
| [`app.order_items`](#apporder_items) | Lines of an order; unit_price is frozen at purchase time | 233,422 | 29 MB |
| [`app.orders`](#apporders) | One checkout: a buyer, one event, one or more ticket types | 233,422 | 47 MB |
| [`app.org_members`](#apporg_members) | Which users work for which organizer, and in what role | 313 | 120 kB |
| [`app.organizations`](#apporganizations) | Companies, clubs and universities that host events | 60 | 96 kB |
| [`app.payments`](#apppayments) | Payment attempts reported by the payment provider | 233,422 | 52 MB |
| [`app.promo_codes`](#apppromo_codes) | Discount codes, limited per event, by date window and by number of uses | 500 | 152 kB |
| [`app.refunds`](#apprefunds) | Money returned; total refunds of a payment can never exceed the amount captured (trigger) | 8,268 | 1464 kB |
| [`app.rooms`](#approoms) | Bookable spaces inside a venue (halls, stages, workshop rooms) | 134 | 80 kB |
| [`app.scan_attempts`](#appscan_attempts) | Every scan at the door, including rejected ones (fraud and queue analysis) | 307,577 | 30 MB |
| [`app.session_speakers`](#appsession_speakers) | Many-to-many: who presents which session | 20,832 | 2016 kB |
| [`app.sessions`](#appsessions) | Agenda items of an event, each in one room | 17,785 | 4376 kB |
| [`app.speakers`](#appspeakers) | People who present sessions; a speaker does not need a user account | 950 | 360 kB |
| [`app.ticket_types`](#appticket_types) | Ticket tiers of an event (Early bird, General, VIP) with their own inventory | 2,462 | 480 kB |
| [`app.tickets`](#apptickets) | One admission per person; the QR code on the ticket is the uuid in code | 425,486 | 117 MB |
| [`app.users`](#appusers) | Everyone with an account: attendees, organizer staff and speakers who log in | 150,000 | 40 MB |
| [`app.venues`](#appvenues) | Physical locations; capacity is the fire-code limit for the whole building | 30 | 80 kB |
| [`app.waitlist`](#appwaitlist) | Queue for sold-out ticket types; first come, first offered when tickets free up | 458 | 160 kB |
| [`audit.change_log`](#auditchange_log) | Append-only history of changes to events, ticket types, orders, refunds and promo codes | 0 | 24 kB |

## Views and functions

| View | Kind | Description |
|---|---|---|
| `report.daily_revenue` | materialized view | Orders, tickets and revenue per day and category; refresh with report.refresh() |
| `report.event_agenda` | view | Sessions with room and speakers, in the venue's local time |
| `report.event_attendance` | view | Tickets issued vs checked in for completed events, and when people arrived |
| `report.event_sales` | view | Seats offered and sold, gross and net revenue per event |
| `report.ticket_availability` | view | Live inventory of every published ticket type |

| Function | Returns | Description |
|---|---|---|
| `app.check_in_ticket(p_code uuid, p_event_id bigint, p_gate text, p_scanned_by bigint)` | text | Door scan: returns admitted / already_checked_in / cancelled / not_found / wrong_event / too_early |
| `app.complete_finished_events(IN p_batch integer)` | procedure | Nightly job: marks published events that have ended as completed, committing in batches |
| `app.current_org()` | bigint | Organization of the current session (SET app.org_id), used by row-level security policies |
| `app.expire_waitlist_offers()` | integer | Expires unanswered offers and passes the seats to the next people waiting; returns offers expired |
| `app.is_valid_timezone(tz text)` | boolean | True for IANA time zone names known to the server (used by venues.timezone) |
| `app.join_waitlist(p_user_id bigint, p_ticket_type_id bigint, p_quantity integer)` | bigint | Joins the queue for a sold-out ticket type; refused while seats are still available |
| `app.offer_waitlist(p_ticket_type_id bigint, p_offer_hours integer)` | integer | Offers freed seats to waiting people in arrival order; returns the number of offers made |
| `app.purchase_tickets(p_user_id bigint, p_items jsonb, p_promo_code text, p_method app.payment_method)` | bigint | Checkout: validates sales window, limits, inventory and promo code, then issues tickets atomically |
| `app.refund_order(p_order_id bigint, p_reason text, p_processed_by bigint)` | numeric | Full refund before the event: money back, tickets cancelled, seats returned and offered to the waitlist |
| `app.tickets_held(p_ticket_type_id bigint, p_except_user bigint)` | integer | Seats held for open waitlist offers (optionally ignoring one user's own offer) |
| `report.refresh()` | void | Refreshes materialized reports (concurrently once populated, so readers are never blocked) |

<a id="appcheck_ins"></a>
## app.check_ins

Successful door scans; the UNIQUE ticket_id makes a second entry on the same ticket impossible

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `check_in_id` | bigint |  | identity |  |
| `ticket_id` | bigint |  |  |  |
| `event_id` | bigint |  |  |  |
| `gate` | text |  |  |  |
| `scanned_by` | bigint | yes |  |  |
| `checked_in_at` | timestamp with time zone |  | now() |  |

**Constraints**

- `check_ins_event_id_fkey` (foreign key): `FOREIGN KEY (event_id) REFERENCES app.events(event_id)`
- `check_ins_scanned_by_fkey` (foreign key): `FOREIGN KEY (scanned_by) REFERENCES app.users(user_id)`
- `check_ins_ticket_id_fkey` (foreign key): `FOREIGN KEY (ticket_id) REFERENCES app.tickets(ticket_id)`
- `check_ins_pkey` (primary key): `PRIMARY KEY (check_in_id)`
- `check_ins_ticket_id_key` (unique): `UNIQUE (ticket_id)`

**Indexes**

- `CREATE INDEX check_ins_event_time ON app.check_ins USING btree (event_id, checked_in_at)`

**Triggers**

- `check_ins_event_check`

<a id="appevent_categories"></a>
## app.event_categories

Category tree, e.g. Technology > Data > Databases (queried recursively)

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `category_id` | integer |  | identity |  |
| `name` | text |  |  |  |
| `parent_id` | integer | yes |  |  |

**Constraints**

- `event_categories_check` (check): `CHECK ((parent_id IS DISTINCT FROM category_id))`
- `event_categories_parent_id_fkey` (foreign key): `FOREIGN KEY (parent_id) REFERENCES app.event_categories(category_id)`
- `event_categories_pkey` (primary key): `PRIMARY KEY (category_id)`
- `event_categories_name_key` (unique): `UNIQUE (name)`

<a id="appevents"></a>
## app.events

An event hosted by one organization at one venue

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `event_id` | bigint |  | identity |  |
| `org_id` | bigint |  |  |  |
| `venue_id` | bigint |  |  |  |
| `category_id` | integer |  |  |  |
| `title` | text |  |  |  |
| `slug` | text |  |  |  |
| `description` | text |  | ''::text |  |
| `status` | app.event_status |  | 'draft'::app.event_status |  |
| `starts_at` | timestamp with time zone |  |  |  |
| `ends_at` | timestamp with time zone |  |  |  |
| `capacity` | integer |  |  | Maximum attendees; may not exceed the venue capacity (trigger) |
| `published_at` | timestamp with time zone | yes |  |  |
| `created_at` | timestamp with time zone |  | now() |  |
| `updated_at` | timestamp with time zone |  | now() |  |
| `search` | tsvector | yes | generated: (setweight(to_tsvector('english'::regconfig, title), 'A'::"char") \|\| setweight(to_tsvector('english'::regconfig, description), 'B'::"char")) | Full-text search document: title weighted above description |

**Constraints**

- `events_capacity_check` (check): `CHECK ((capacity > 0))`
- `events_check` (check): `CHECK ((ends_at > starts_at))`
- `events_check1` (check): `CHECK (((ends_at - starts_at) <= '14 days'::interval))`
- `events_check2` (check): `CHECK (((status = 'draft'::app.event_status) OR (published_at IS NOT NULL)))`
- `events_slug_check` (check): `CHECK ((slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'::text))`
- `events_category_id_fkey` (foreign key): `FOREIGN KEY (category_id) REFERENCES app.event_categories(category_id)`
- `events_org_id_fkey` (foreign key): `FOREIGN KEY (org_id) REFERENCES app.organizations(org_id)`
- `events_venue_id_fkey` (foreign key): `FOREIGN KEY (venue_id) REFERENCES app.venues(venue_id)`
- `events_pkey` (primary key): `PRIMARY KEY (event_id)`
- `events_slug_key` (unique): `UNIQUE (slug)`

**Indexes**

- `CREATE INDEX events_category ON app.events USING btree (category_id)`
- `CREATE INDEX events_org ON app.events USING btree (org_id)`
- `CREATE INDEX events_search ON app.events USING gin (search)`
- `CREATE INDEX events_title_trgm ON app.events USING gin (title gin_trgm_ops)`
- `CREATE INDEX events_upcoming ON app.events USING btree (starts_at) WHERE (status = 'published'::app.event_status)`
- `CREATE INDEX events_venue ON app.events USING btree (venue_id)`

**Triggers**

- `audit_events`
- `events_check`
- `events_updated_at`

<a id="appfeedback"></a>
## app.feedback

Post-event ratings; only people who actually checked in may rate (trigger)

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `feedback_id` | bigint |  | identity |  |
| `event_id` | bigint |  |  |  |
| `user_id` | bigint |  |  |  |
| `rating` | smallint |  |  |  |
| `comment` | text | yes |  |  |
| `created_at` | timestamp with time zone |  | now() |  |

**Constraints**

- `feedback_rating_check` (check): `CHECK (((rating >= 1) AND (rating <= 5)))`
- `feedback_event_id_fkey` (foreign key): `FOREIGN KEY (event_id) REFERENCES app.events(event_id)`
- `feedback_user_id_fkey` (foreign key): `FOREIGN KEY (user_id) REFERENCES app.users(user_id)`
- `feedback_pkey` (primary key): `PRIMARY KEY (feedback_id)`
- `feedback_event_id_user_id_key` (unique): `UNIQUE (event_id, user_id)`

**Triggers**

- `feedback_check`

<a id="apporder_items"></a>
## app.order_items

Lines of an order; unit_price is frozen at purchase time

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `order_item_id` | bigint |  | identity |  |
| `order_id` | bigint |  |  |  |
| `ticket_type_id` | bigint |  |  |  |
| `quantity` | integer |  |  |  |
| `unit_price` | numeric(10,2) |  |  |  |
| `line_total` | numeric(10,2) | yes | generated: ((quantity)::numeric * unit_price) |  |

**Constraints**

- `order_items_quantity_check` (check): `CHECK ((quantity > 0))`
- `order_items_unit_price_check` (check): `CHECK ((unit_price >= (0)::numeric))`
- `order_items_order_id_fkey` (foreign key): `FOREIGN KEY (order_id) REFERENCES app.orders(order_id) ON DELETE CASCADE`
- `order_items_ticket_type_id_fkey` (foreign key): `FOREIGN KEY (ticket_type_id) REFERENCES app.ticket_types(ticket_type_id)`
- `order_items_pkey` (primary key): `PRIMARY KEY (order_item_id)`
- `order_items_order_id_ticket_type_id_key` (unique): `UNIQUE (order_id, ticket_type_id)`

**Indexes**

- `CREATE INDEX order_items_tt ON app.order_items USING btree (ticket_type_id)`

<a id="apporders"></a>
## app.orders

One checkout: a buyer, one event, one or more ticket types

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `order_id` | bigint |  | identity |  |
| `user_id` | bigint |  |  |  |
| `event_id` | bigint |  |  |  |
| `promo_id` | bigint | yes |  |  |
| `status` | app.order_status |  | 'pending'::app.order_status |  |
| `subtotal` | numeric(10,2) |  |  |  |
| `discount` | numeric(10,2) |  | 0 |  |
| `total` | numeric(10,2) |  |  | Always subtotal - discount (CHECK constraint) |
| `created_at` | timestamp with time zone |  | now() |  |
| `paid_at` | timestamp with time zone | yes |  |  |
| `updated_at` | timestamp with time zone |  | now() |  |

**Constraints**

- `orders_check` (check): `CHECK ((discount <= subtotal))`
- `orders_check1` (check): `CHECK ((total = (subtotal - discount)))`
- `orders_check2` (check): `CHECK (((status = ANY (ARRAY['pending'::app.order_status, 'cancelled'::app.order_status])) = (paid_at IS NULL)))`
- `orders_discount_check` (check): `CHECK ((discount >= (0)::numeric))`
- `orders_subtotal_check` (check): `CHECK ((subtotal >= (0)::numeric))`
- `orders_event_id_fkey` (foreign key): `FOREIGN KEY (event_id) REFERENCES app.events(event_id)`
- `orders_promo_id_fkey` (foreign key): `FOREIGN KEY (promo_id) REFERENCES app.promo_codes(promo_id)`
- `orders_user_id_fkey` (foreign key): `FOREIGN KEY (user_id) REFERENCES app.users(user_id)`
- `orders_pkey` (primary key): `PRIMARY KEY (order_id)`

**Indexes**

- `CREATE INDEX orders_event_status ON app.orders USING btree (event_id, status)`
- `CREATE INDEX orders_paid_at ON app.orders USING btree (paid_at) WHERE (paid_at IS NOT NULL)`
- `CREATE INDEX orders_user_recent ON app.orders USING btree (user_id, created_at DESC)`

**Triggers**

- `audit_orders`
- `orders_updated_at`

<a id="apporg_members"></a>
## app.org_members

Which users work for which organizer, and in what role

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `org_id` | bigint |  |  |  |
| `user_id` | bigint |  |  |  |
| `role` | app.member_role |  | 'staff'::app.member_role |  |
| `joined_at` | timestamp with time zone |  | now() |  |

**Constraints**

- `org_members_org_id_fkey` (foreign key): `FOREIGN KEY (org_id) REFERENCES app.organizations(org_id) ON DELETE CASCADE`
- `org_members_user_id_fkey` (foreign key): `FOREIGN KEY (user_id) REFERENCES app.users(user_id) ON DELETE CASCADE`
- `org_members_pkey` (primary key): `PRIMARY KEY (org_id, user_id)`

**Indexes**

- `CREATE UNIQUE INDEX org_members_one_owner ON app.org_members USING btree (org_id) WHERE (role = 'owner'::app.member_role)`
- `CREATE INDEX org_members_user ON app.org_members USING btree (user_id)`

<a id="apporganizations"></a>
## app.organizations

Companies, clubs and universities that host events

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `org_id` | bigint |  | identity |  |
| `name` | text |  |  |  |
| `slug` | text |  |  |  |
| `contact_email` | citext |  |  |  |
| `created_at` | timestamp with time zone |  | now() |  |

**Constraints**

- `organizations_slug_check` (check): `CHECK ((slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'::text))`
- `organizations_pkey` (primary key): `PRIMARY KEY (org_id)`
- `organizations_name_key` (unique): `UNIQUE (name)`
- `organizations_slug_key` (unique): `UNIQUE (slug)`

<a id="apppayments"></a>
## app.payments

Payment attempts reported by the payment provider

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `payment_id` | bigint |  | identity |  |
| `order_id` | bigint |  |  |  |
| `amount` | numeric(10,2) |  |  |  |
| `method` | app.payment_method |  |  |  |
| `status` | app.payment_status |  |  |  |
| `provider_ref` | text |  |  | Provider transaction id; unique so a webhook replay cannot record a payment twice |
| `created_at` | timestamp with time zone |  | now() |  |

**Constraints**

- `payments_amount_check` (check): `CHECK ((amount >= (0)::numeric))`
- `payments_order_id_fkey` (foreign key): `FOREIGN KEY (order_id) REFERENCES app.orders(order_id)`
- `payments_pkey` (primary key): `PRIMARY KEY (payment_id)`
- `payments_provider_ref_key` (unique): `UNIQUE (provider_ref)`

**Indexes**

- `CREATE INDEX payments_order ON app.payments USING btree (order_id)`

<a id="apppromo_codes"></a>
## app.promo_codes

Discount codes, limited per event, by date window and by number of uses

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `promo_id` | bigint |  | identity |  |
| `event_id` | bigint |  |  |  |
| `code` | citext |  |  |  |
| `discount_type` | text |  |  |  |
| `discount_value` | numeric(10,2) |  |  |  |
| `max_uses` | integer | yes |  |  |
| `times_used` | integer |  | 0 |  |
| `valid_from` | timestamp with time zone |  |  |  |
| `valid_until` | timestamp with time zone |  |  |  |

**Constraints**

- `promo_codes_check` (check): `CHECK ((valid_until > valid_from))`
- `promo_codes_check1` (check): `CHECK (((discount_type <> 'percent'::text) OR (discount_value <= (100)::numeric)))`
- `promo_codes_check2` (check): `CHECK (((max_uses IS NULL) OR (times_used <= max_uses)))`
- `promo_codes_code_check` (check): `CHECK ((code ~ '^[A-Za-z0-9_-]{3,32}$'::citext))`
- `promo_codes_discount_type_check` (check): `CHECK ((discount_type = ANY (ARRAY['percent'::text, 'amount'::text])))`
- `promo_codes_discount_value_check` (check): `CHECK ((discount_value > (0)::numeric))`
- `promo_codes_max_uses_check` (check): `CHECK ((max_uses > 0))`
- `promo_codes_times_used_check` (check): `CHECK ((times_used >= 0))`
- `promo_codes_event_id_fkey` (foreign key): `FOREIGN KEY (event_id) REFERENCES app.events(event_id) ON DELETE CASCADE`
- `promo_codes_pkey` (primary key): `PRIMARY KEY (promo_id)`
- `promo_codes_event_id_code_key` (unique): `UNIQUE (event_id, code)`

**Triggers**

- `audit_promo_codes`

<a id="apprefunds"></a>
## app.refunds

Money returned; total refunds of a payment can never exceed the amount captured (trigger)

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `refund_id` | bigint |  | identity |  |
| `order_id` | bigint |  |  |  |
| `payment_id` | bigint |  |  |  |
| `amount` | numeric(10,2) |  |  |  |
| `reason` | text |  |  |  |
| `processed_by` | bigint | yes |  |  |
| `created_at` | timestamp with time zone |  | now() |  |

**Constraints**

- `refunds_amount_check` (check): `CHECK ((amount > (0)::numeric))`
- `refunds_order_id_fkey` (foreign key): `FOREIGN KEY (order_id) REFERENCES app.orders(order_id)`
- `refunds_payment_id_fkey` (foreign key): `FOREIGN KEY (payment_id) REFERENCES app.payments(payment_id)`
- `refunds_processed_by_fkey` (foreign key): `FOREIGN KEY (processed_by) REFERENCES app.users(user_id)`
- `refunds_pkey` (primary key): `PRIMARY KEY (refund_id)`

**Indexes**

- `CREATE INDEX refunds_order ON app.refunds USING btree (order_id)`
- `CREATE INDEX refunds_payment ON app.refunds USING btree (payment_id)`

**Triggers**

- `audit_refunds`
- `refunds_check`

<a id="approoms"></a>
## app.rooms

Bookable spaces inside a venue (halls, stages, workshop rooms)

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `room_id` | bigint |  | identity |  |
| `venue_id` | bigint |  |  |  |
| `name` | text |  |  |  |
| `capacity` | integer |  |  |  |

**Constraints**

- `rooms_capacity_check` (check): `CHECK ((capacity > 0))`
- `rooms_venue_id_fkey` (foreign key): `FOREIGN KEY (venue_id) REFERENCES app.venues(venue_id) ON DELETE CASCADE`
- `rooms_pkey` (primary key): `PRIMARY KEY (room_id)`
- `rooms_venue_id_name_key` (unique): `UNIQUE (venue_id, name)`

<a id="appscan_attempts"></a>
## app.scan_attempts

Every scan at the door, including rejected ones (fraud and queue analysis)

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `attempt_id` | bigint |  | identity |  |
| `code` | uuid |  |  |  |
| `gate` | text |  |  |  |
| `result` | text |  |  |  |
| `attempted_at` | timestamp with time zone |  | now() |  |

**Constraints**

- `scan_attempts_result_check` (check): `CHECK ((result = ANY (ARRAY['admitted'::text, 'already_checked_in'::text, 'cancelled'::text, 'not_found'::text, 'wrong_event'::text, 'too_early'::text])))`
- `scan_attempts_pkey` (primary key): `PRIMARY KEY (attempt_id)`

**Indexes**

- `CREATE INDEX scan_attempts_time ON app.scan_attempts USING brin (attempted_at) WITH (autosummarize='on')`

<a id="appsession_speakers"></a>
## app.session_speakers

Many-to-many: who presents which session

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `session_id` | bigint |  |  |  |
| `speaker_id` | bigint |  |  |  |
| `role` | text |  | 'speaker'::text |  |

**Constraints**

- `session_speakers_role_check` (check): `CHECK ((role = ANY (ARRAY['speaker'::text, 'moderator'::text, 'panelist'::text])))`
- `session_speakers_session_id_fkey` (foreign key): `FOREIGN KEY (session_id) REFERENCES app.sessions(session_id) ON DELETE CASCADE`
- `session_speakers_speaker_id_fkey` (foreign key): `FOREIGN KEY (speaker_id) REFERENCES app.speakers(speaker_id)`
- `session_speakers_pkey` (primary key): `PRIMARY KEY (session_id, speaker_id)`

**Indexes**

- `CREATE INDEX session_speakers_spkr ON app.session_speakers USING btree (speaker_id)`

<a id="appsessions"></a>
## app.sessions

Agenda items of an event, each in one room

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `session_id` | bigint |  | identity |  |
| `event_id` | bigint |  |  |  |
| `room_id` | bigint |  |  |  |
| `title` | text |  |  |  |
| `track` | text | yes |  |  |
| `starts_at` | timestamp with time zone |  |  |  |
| `ends_at` | timestamp with time zone |  |  |  |
| `during` | tstzrange | yes | generated: tstzrange(starts_at, ends_at, '[)'::text) | Half-open time range [start, end) used by the no-overlap constraint |

**Constraints**

- `sessions_check` (check): `CHECK ((ends_at > starts_at))`
- `sessions_event_id_fkey` (foreign key): `FOREIGN KEY (event_id) REFERENCES app.events(event_id) ON DELETE CASCADE`
- `sessions_room_id_fkey` (foreign key): `FOREIGN KEY (room_id) REFERENCES app.rooms(room_id)`
- `sessions_pkey` (primary key): `PRIMARY KEY (session_id)`
- `sessions_no_room_overlap` (exclusion): `EXCLUDE USING gist (room_id WITH =, during WITH &&)`

**Indexes**

- `CREATE INDEX sessions_event ON app.sessions USING btree (event_id)`

**Triggers**

- `sessions_check`

<a id="appspeakers"></a>
## app.speakers

People who present sessions; a speaker does not need a user account

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `speaker_id` | bigint |  | identity |  |
| `full_name` | text |  |  |  |
| `email` | citext | yes |  |  |
| `company` | text | yes |  |  |
| `bio` | text |  | ''::text |  |

**Constraints**

- `speakers_pkey` (primary key): `PRIMARY KEY (speaker_id)`
- `speakers_email_key` (unique): `UNIQUE (email)`

<a id="appticket_types"></a>
## app.ticket_types

Ticket tiers of an event (Early bird, General, VIP) with their own inventory

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `ticket_type_id` | bigint |  | identity |  |
| `event_id` | bigint |  |  |  |
| `name` | text |  |  |  |
| `price` | numeric(10,2) |  |  |  |
| `currency` | character(3) |  | 'USD'::bpchar |  |
| `quantity_total` | integer |  |  |  |
| `quantity_sold` | integer |  | 0 | Inventory counter maintained only by purchase_tickets and refund_order |
| `sales_start` | timestamp with time zone |  |  |  |
| `sales_end` | timestamp with time zone |  |  |  |
| `max_per_order` | smallint |  | 10 |  |

**Constraints**

- `ticket_types_check` (check): `CHECK ((sales_end > sales_start))`
- `ticket_types_currency_check` (check): `CHECK ((currency ~ '^[A-Z]{3}$'::text))`
- `ticket_types_inventory` (check): `CHECK (((quantity_sold >= 0) AND (quantity_sold <= quantity_total)))`
- `ticket_types_max_per_order_check` (check): `CHECK (((max_per_order >= 1) AND (max_per_order <= 50)))`
- `ticket_types_price_check` (check): `CHECK ((price >= (0)::numeric))`
- `ticket_types_quantity_total_check` (check): `CHECK ((quantity_total > 0))`
- `ticket_types_event_id_fkey` (foreign key): `FOREIGN KEY (event_id) REFERENCES app.events(event_id) ON DELETE CASCADE`
- `ticket_types_pkey` (primary key): `PRIMARY KEY (ticket_type_id)`
- `ticket_types_event_id_name_key` (unique): `UNIQUE (event_id, name)`

**Triggers**

- `audit_ticket_types`
- `ticket_types_check`

<a id="apptickets"></a>
## app.tickets

One admission per person; the QR code on the ticket is the uuid in code

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `ticket_id` | bigint |  | identity |  |
| `order_item_id` | bigint |  |  |  |
| `event_id` | bigint |  |  | Denormalized from the order for fast door scanning and per-event constraints |
| `code` | uuid |  | gen_random_uuid() |  |
| `attendee_name` | text |  |  |  |
| `attendee_email` | citext |  |  |  |
| `status` | app.ticket_status |  | 'valid'::app.ticket_status |  |
| `issued_at` | timestamp with time zone |  | now() |  |

**Constraints**

- `tickets_event_id_fkey` (foreign key): `FOREIGN KEY (event_id) REFERENCES app.events(event_id)`
- `tickets_order_item_id_fkey` (foreign key): `FOREIGN KEY (order_item_id) REFERENCES app.order_items(order_item_id) ON DELETE CASCADE`
- `tickets_pkey` (primary key): `PRIMARY KEY (ticket_id)`
- `tickets_code_key` (unique): `UNIQUE (code)`

**Indexes**

- `CREATE INDEX tickets_attendee_email ON app.tickets USING btree (attendee_email)`
- `CREATE INDEX tickets_event_status ON app.tickets USING btree (event_id, status)`
- `CREATE INDEX tickets_order_item ON app.tickets USING btree (order_item_id)`

**Triggers**

- `tickets_event_check`

<a id="appusers"></a>
## app.users

Everyone with an account: attendees, organizer staff and speakers who log in

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `user_id` | bigint |  | identity |  |
| `email` | citext |  |  | Login and contact address; case-insensitive and unique |
| `full_name` | text |  |  |  |
| `phone` | text | yes |  |  |
| `city` | text | yes |  |  |
| `created_at` | timestamp with time zone |  | now() |  |
| `is_active` | boolean |  | true |  |

**Constraints**

- `users_email_check` (check): `CHECK ((email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'::citext))`
- `users_full_name_check` (check): `CHECK ((length(TRIM(BOTH FROM full_name)) > 0))`
- `users_pkey` (primary key): `PRIMARY KEY (user_id)`
- `users_email_key` (unique): `UNIQUE (email)`

**Indexes**

- `CREATE INDEX users_name_trgm ON app.users USING gin (full_name gin_trgm_ops)`

<a id="appvenues"></a>
## app.venues

Physical locations; capacity is the fire-code limit for the whole building

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `venue_id` | bigint |  | identity |  |
| `name` | text |  |  |  |
| `address_line` | text |  |  |  |
| `city` | text |  |  |  |
| `state` | text | yes |  |  |
| `postal_code` | text | yes |  |  |
| `country` | character(2) |  | 'US'::bpchar |  |
| `timezone` | text |  | 'America/New_York'::text | IANA zone used to show local times; all timestamps are stored in UTC |
| `capacity` | integer |  |  |  |

**Constraints**

- `venues_capacity_check` (check): `CHECK ((capacity > 0))`
- `venues_country_check` (check): `CHECK ((country ~ '^[A-Z]{2}$'::text))`
- `venues_timezone_check` (check): `CHECK (app.is_valid_timezone(timezone))`
- `venues_pkey` (primary key): `PRIMARY KEY (venue_id)`
- `venues_name_city_key` (unique): `UNIQUE (name, city)`

<a id="appwaitlist"></a>
## app.waitlist

Queue for sold-out ticket types; first come, first offered when tickets free up

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `waitlist_id` | bigint |  | identity |  |
| `ticket_type_id` | bigint |  |  |  |
| `user_id` | bigint |  |  |  |
| `quantity` | smallint |  | 1 |  |
| `status` | app.waitlist_status |  | 'waiting'::app.waitlist_status |  |
| `joined_at` | timestamp with time zone |  | now() |  |
| `offered_at` | timestamp with time zone | yes |  |  |
| `offer_expires_at` | timestamp with time zone | yes |  |  |

**Constraints**

- `waitlist_check` (check): `CHECK (((status <> 'offered'::app.waitlist_status) OR ((offered_at IS NOT NULL) AND (offer_expires_at > offered_at))))`
- `waitlist_quantity_check` (check): `CHECK (((quantity >= 1) AND (quantity <= 10)))`
- `waitlist_ticket_type_id_fkey` (foreign key): `FOREIGN KEY (ticket_type_id) REFERENCES app.ticket_types(ticket_type_id) ON DELETE CASCADE`
- `waitlist_user_id_fkey` (foreign key): `FOREIGN KEY (user_id) REFERENCES app.users(user_id)`
- `waitlist_pkey` (primary key): `PRIMARY KEY (waitlist_id)`

**Indexes**

- `CREATE UNIQUE INDEX waitlist_one_active_entry ON app.waitlist USING btree (ticket_type_id, user_id) WHERE (status = ANY (ARRAY['waiting'::app.waitlist_status, 'offered'::app.waitlist_status]))`
- `CREATE INDEX waitlist_queue ON app.waitlist USING btree (ticket_type_id, joined_at) WHERE (status = 'waiting'::app.waitlist_status)`

<a id="auditchange_log"></a>
## audit.change_log

Append-only history of changes to events, ticket types, orders, refunds and promo codes

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `change_id` | bigint |  | identity |  |
| `table_name` | text |  |  |  |
| `operation` | text |  |  |  |
| `row_id` | bigint |  |  |  |
| `old_values` | jsonb | yes |  |  |
| `new_values` | jsonb | yes |  |  |
| `changed_by` | text |  | CURRENT_USER |  |
| `app_user` | text | yes | current_setting('app.user_id'::text, true) | Application user id, set per transaction with SET LOCAL app.user_id |
| `changed_at` | timestamp with time zone |  | now() |  |

**Constraints**

- `change_log_operation_check` (check): `CHECK ((operation = ANY (ARRAY['INSERT'::text, 'UPDATE'::text, 'DELETE'::text])))`
- `change_log_pkey` (primary key): `PRIMARY KEY (change_id)`

**Indexes**

- `CREATE INDEX change_log_lookup ON audit.change_log USING btree (table_name, row_id, changed_at)`
