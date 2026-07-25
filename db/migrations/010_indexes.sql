-- 010 Indexes. Each one is here for a query that needs it; see docs/performance.md for measurements.
-- PostgreSQL does not index foreign keys automatically, so joins and ON DELETE checks need these.

-- Foreign keys used in joins
CREATE INDEX org_members_user       ON app.org_members (user_id);
CREATE INDEX events_org             ON app.events (org_id);
CREATE INDEX events_venue           ON app.events (venue_id);
CREATE INDEX events_category        ON app.events (category_id);
CREATE INDEX sessions_event         ON app.sessions (event_id);
CREATE INDEX session_speakers_spkr  ON app.session_speakers (speaker_id);
CREATE INDEX order_items_tt         ON app.order_items (ticket_type_id);
CREATE INDEX tickets_order_item     ON app.tickets (order_item_id);
CREATE INDEX payments_order         ON app.payments (order_id);
CREATE INDEX refunds_order          ON app.refunds (order_id);
CREATE INDEX refunds_payment        ON app.refunds (payment_id);

-- "Upcoming events": partial index holds only published events, ordered by start time.
CREATE INDEX events_upcoming        ON app.events (starts_at) WHERE status = 'published';

-- Search box: full-text on title + description, and typo-tolerant title matching.
CREATE INDEX events_search          ON app.events USING gin (search);
CREATE INDEX events_title_trgm      ON app.events USING gin (title gin_trgm_ops);
-- Support desk: find a customer even when the name is misspelled ("Jon Smiht").
CREATE INDEX users_name_trgm        ON app.users USING gin (full_name gin_trgm_ops);

-- Organizer dashboards: an event's orders by status; a buyer's order history, newest first.
CREATE INDEX orders_event_status    ON app.orders (event_id, status);
CREATE INDEX orders_user_recent     ON app.orders (user_id, created_at DESC);
CREATE INDEX orders_paid_at         ON app.orders (paid_at) WHERE paid_at IS NOT NULL;

-- Door and support desk: tickets of an event by status; "find my tickets" by email.
CREATE INDEX tickets_event_status   ON app.tickets (event_id, status);
CREATE INDEX tickets_attendee_email ON app.tickets (attendee_email);

-- Arrival curves per event.
CREATE INDEX check_ins_event_time   ON app.check_ins (event_id, checked_in_at);

-- Scan log is append-only and time-ordered: BRIN is tiny and good enough for time ranges.
-- autosummarize: new block ranges are summarized as they fill up (otherwise only VACUUM does it,
-- and unsummarized ranges are always read).
CREATE INDEX scan_attempts_time     ON app.scan_attempts USING brin (attempted_at) WITH (autosummarize = on);

-- Waitlist queue: next person in line for a ticket type.
CREATE INDEX waitlist_queue         ON app.waitlist (ticket_type_id, joined_at) WHERE status = 'waiting';
