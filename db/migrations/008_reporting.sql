-- 008 Reporting layer: views that answer the questions organizers ask every day.

-- Revenue and sell-through per event. Net = paid orders - refunds.
CREATE VIEW report.event_sales AS
WITH tt AS (
    SELECT event_id, sum(quantity_total) AS seats_offered, sum(quantity_sold) AS seats_sold
      FROM app.ticket_types GROUP BY event_id
), money AS (
    SELECT o.event_id,
           count(*) FILTER (WHERE o.status IN ('paid', 'refunded', 'partially_refunded')) AS orders,
           sum(o.total) FILTER (WHERE o.status IN ('paid', 'refunded', 'partially_refunded')) AS gross_revenue,
           sum(o.discount) FILTER (WHERE o.status IN ('paid', 'refunded', 'partially_refunded')) AS discounts
      FROM app.orders o GROUP BY o.event_id
), refunded AS (
    SELECT o.event_id, sum(r.amount) AS refunds
      FROM app.refunds r JOIN app.orders o USING (order_id) GROUP BY o.event_id
)
SELECT e.event_id, e.title, org.name AS organizer, v.city, e.starts_at, e.status,
       coalesce(tt.seats_offered, 0)                          AS seats_offered,
       coalesce(tt.seats_sold, 0)                             AS seats_sold,
       round(100.0 * tt.seats_sold / nullif(tt.seats_offered, 0), 1) AS sell_through_pct,
       coalesce(m.orders, 0)                                  AS orders,
       coalesce(m.gross_revenue, 0)                           AS gross_revenue,
       coalesce(m.discounts, 0)                               AS discounts,
       coalesce(rf.refunds, 0)                                AS refunds,
       coalesce(m.gross_revenue, 0) - coalesce(rf.refunds, 0) AS net_revenue
  FROM app.events e
  JOIN app.organizations org USING (org_id)
  JOIN app.venues v USING (venue_id)
  LEFT JOIN tt USING (event_id)
  LEFT JOIN money m USING (event_id)
  LEFT JOIN refunded rf USING (event_id);
COMMENT ON VIEW report.event_sales IS 'Seats offered and sold, gross and net revenue per event';

-- Who actually showed up.
CREATE VIEW report.event_attendance AS
SELECT e.event_id, e.title, e.starts_at,
       count(t.ticket_id) FILTER (WHERE t.status <> 'cancelled')  AS tickets_issued,
       count(t.ticket_id) FILTER (WHERE t.status = 'checked_in')  AS checked_in,
       round(100.0 * count(t.ticket_id) FILTER (WHERE t.status = 'checked_in')
             / nullif(count(t.ticket_id) FILTER (WHERE t.status <> 'cancelled'), 0), 1) AS show_up_pct,
       min(c.checked_in_at) AS doors_first_scan,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY c.checked_in_at - e.starts_at) AS median_arrival_vs_start
  FROM app.events e
  LEFT JOIN app.tickets t   ON t.event_id = e.event_id
  LEFT JOIN app.check_ins c ON c.ticket_id = t.ticket_id
 WHERE e.status = 'completed'
 GROUP BY e.event_id, e.title, e.starts_at;
COMMENT ON VIEW report.event_attendance IS 'Tickets issued vs checked in for completed events, and when people arrived';

-- The printed agenda, in each venue's local time.
CREATE VIEW report.event_agenda AS
SELECT e.event_id, e.title AS event, s.session_id, s.title AS session, s.track, r.name AS room,
       (s.starts_at AT TIME ZONE v.timezone) AS local_start,
       (s.ends_at   AT TIME ZONE v.timezone) AS local_end,
       string_agg(sp.full_name || CASE WHEN ss.role <> 'speaker' THEN ' (' || ss.role || ')' ELSE '' END,
                  ', ' ORDER BY sp.full_name) AS speakers
  FROM app.sessions s
  JOIN app.events e USING (event_id)
  JOIN app.venues v ON v.venue_id = e.venue_id
  JOIN app.rooms r  ON r.room_id = s.room_id
  LEFT JOIN app.session_speakers ss USING (session_id)
  LEFT JOIN app.speakers sp USING (speaker_id)
 GROUP BY e.event_id, e.title, s.session_id, s.title, s.track, r.name, s.starts_at, s.ends_at, v.timezone;
COMMENT ON VIEW report.event_agenda IS 'Sessions with room and speakers, in the venue''s local time';

-- Ticket inventory right now, including seats held for waitlist offers.
CREATE VIEW report.ticket_availability AS
SELECT tt.ticket_type_id, e.event_id, e.title AS event, tt.name AS ticket_type, tt.price,
       tt.quantity_total, tt.quantity_sold,
       app.tickets_held(tt.ticket_type_id) AS held_for_waitlist,
       tt.quantity_total - tt.quantity_sold - app.tickets_held(tt.ticket_type_id) AS available,
       (SELECT count(*) FROM app.waitlist w WHERE w.ticket_type_id = tt.ticket_type_id AND w.status = 'waiting') AS waiting,
       now() BETWEEN tt.sales_start AND tt.sales_end AS on_sale
  FROM app.ticket_types tt
  JOIN app.events e USING (event_id)
 WHERE e.status = 'published';
COMMENT ON VIEW report.ticket_availability IS 'Live inventory of every published ticket type';

-- Daily revenue is read by dashboards many times a minute: materialize it.
CREATE MATERIALIZED VIEW report.daily_revenue AS
SELECT (o.paid_at AT TIME ZONE 'UTC')::date AS day,
       c.name AS category,
       count(*) AS orders,
       sum(oi.tickets) AS tickets,
       sum(o.total) AS revenue
  FROM app.orders o
  JOIN app.events e USING (event_id)
  JOIN app.event_categories c USING (category_id)
  JOIN (SELECT order_id, sum(quantity) AS tickets FROM app.order_items GROUP BY order_id) oi USING (order_id)
 WHERE o.paid_at IS NOT NULL
 GROUP BY 1, 2
WITH NO DATA;
CREATE UNIQUE INDEX daily_revenue_pk ON report.daily_revenue (day, category);
COMMENT ON MATERIALIZED VIEW report.daily_revenue IS 'Orders, tickets and revenue per day and category; refresh with report.refresh()';

CREATE FUNCTION report.refresh() RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    -- CONCURRENTLY keeps the view readable during the refresh (needs the unique index above),
    -- but only works once the view has been populated.
    IF (SELECT relispopulated FROM pg_class WHERE oid = 'report.daily_revenue'::regclass) THEN
        REFRESH MATERIALIZED VIEW CONCURRENTLY report.daily_revenue;
    ELSE
        REFRESH MATERIALIZED VIEW report.daily_revenue;
    END IF;
END $$;
COMMENT ON FUNCTION report.refresh IS 'Refreshes materialized reports (concurrently once populated, so readers are never blocked)';
