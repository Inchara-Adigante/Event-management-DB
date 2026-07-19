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
