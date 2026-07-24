-- Business questions answered with SQL. Each block starts with "-- name:" and a one-line question;
-- scripts/run_queries.py runs them all and writes docs/analytics_results.md.

-- name: top_events
-- Which events earned the most, and how full did they get?
SELECT rank() OVER (ORDER BY net_revenue DESC) AS rank, title, organizer, city,
       seats_sold, sell_through_pct, net_revenue
  FROM report.event_sales
 WHERE status = 'completed'
 ORDER BY net_revenue DESC
 LIMIT 10;

-- name: monthly_revenue_growth
-- How is revenue trending month over month? (window functions: LAG and a running total)
WITH m AS (
    SELECT date_trunc('month', paid_at)::date AS month, sum(total) AS revenue, count(*) AS orders
      FROM app.orders WHERE status IN ('paid', 'refunded') GROUP BY 1
)
SELECT month, orders, revenue,
       round(100.0 * (revenue - lag(revenue) OVER w) / nullif(lag(revenue) OVER w, 0), 1) AS mom_growth_pct,
       sum(revenue) OVER (ORDER BY month) AS running_total
  FROM m WINDOW w AS (ORDER BY month)
 ORDER BY month;

-- name: category_rollup
-- Revenue by category, rolled up the category tree (recursive CTE + ROLLUP).
WITH RECURSIVE tree AS (
    SELECT category_id, name, name AS top_level FROM app.event_categories WHERE parent_id IS NULL
    UNION ALL
    SELECT c.category_id, c.name, t.top_level FROM app.event_categories c JOIN tree t ON c.parent_id = t.category_id
)
SELECT coalesce(t.top_level, 'ALL CATEGORIES') AS top_level,
       coalesce(t.name, CASE WHEN t.top_level IS NOT NULL THEN '(subtotal)' END) AS category,
       count(DISTINCT s.event_id) AS events, sum(s.net_revenue) AS net_revenue
  FROM report.event_sales s
  JOIN app.events e USING (event_id)
  JOIN tree t ON t.category_id = e.category_id
 GROUP BY ROLLUP (t.top_level, t.name)
 ORDER BY t.top_level NULLS LAST, t.name NULLS LAST;

-- name: sales_velocity
-- How far ahead do people buy? Share of tickets by days before the event.
SELECT CASE WHEN d >= 60 THEN '60+ days' WHEN d >= 30 THEN '30-59 days' WHEN d >= 14 THEN '14-29 days'
            WHEN d >= 7 THEN '7-13 days' WHEN d >= 1 THEN '1-6 days' ELSE 'same day' END AS bought_before_event,
       sum(qty) AS tickets,
       round(100.0 * sum(qty) / sum(sum(qty)) OVER (), 1) AS pct
  FROM (SELECT extract(day FROM e.starts_at - o.paid_at) AS d, oi.quantity AS qty
          FROM app.orders o JOIN app.order_items oi USING (order_id) JOIN app.events e USING (event_id)
         WHERE o.paid_at IS NOT NULL) x
 GROUP BY 1
 ORDER BY min(d) DESC;

-- name: tier_performance
-- Do Early Bird tiers sell out more than General Admission? Price and sell-through per tier name.
SELECT tt.name AS ticket_type, count(*) AS tiers, round(avg(tt.price), 2) AS avg_price,
       round(100.0 * sum(tt.quantity_sold) / sum(tt.quantity_total), 1) AS sell_through_pct,
       count(*) FILTER (WHERE tt.quantity_sold = tt.quantity_total) AS sold_out
  FROM app.ticket_types tt JOIN app.events e USING (event_id)
 WHERE e.status = 'completed'
 GROUP BY tt.name
HAVING count(*) >= 20
 ORDER BY sell_through_pct DESC;

-- name: no_show_by_price
-- Free events have more no-shows than paid ones.
SELECT CASE WHEN tt.price = 0 THEN 'free' WHEN tt.price < 50 THEN 'under $50'
            WHEN tt.price < 200 THEN '$50-199' ELSE '$200+' END AS price_band,
       count(*) AS tickets,
       round(100.0 * count(*) FILTER (WHERE t.status = 'checked_in') / count(*), 1) AS show_up_pct
  FROM app.tickets t
  JOIN app.order_items oi USING (order_item_id)
  JOIN app.ticket_types tt USING (ticket_type_id)
  JOIN app.events e ON e.event_id = t.event_id
 WHERE e.status = 'completed' AND t.status <> 'cancelled'
 GROUP BY 1
 ORDER BY min(tt.price);

-- name: repeat_attendees
-- How loyal are attendees? Buyers by number of distinct events attended.
WITH per_user AS (
    SELECT o.user_id, count(DISTINCT o.event_id) AS events
      FROM app.orders o WHERE o.status = 'paid' GROUP BY o.user_id
)
SELECT CASE WHEN events >= 10 THEN '10+' ELSE events::text END AS events_attended,
       count(*) AS buyers,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct_of_buyers
  FROM per_user GROUP BY 1 ORDER BY min(events);

-- name: arrival_curve
-- When do people arrive? Check-ins in 15-minute buckets relative to the start time (big events).
WITH b AS (
    SELECT (floor(extract(epoch FROM c.checked_in_at - e.starts_at) / 900) * 15)::int AS minutes_from_start,
           count(*) AS check_ins
      FROM app.check_ins c JOIN app.events e USING (event_id)
     WHERE e.capacity >= 1000
     GROUP BY 1
)
SELECT minutes_from_start, check_ins,
       round(100.0 * check_ins / sum(check_ins) OVER (), 1) AS pct,
       round(100.0 * sum(check_ins) OVER (ORDER BY minutes_from_start) / sum(check_ins) OVER (), 1) AS cumulative_pct
  FROM b ORDER BY minutes_from_start;

-- name: busiest_gates
-- Which gates need more staff? Peak 5-minute scan count per gate (top 10).
WITH buckets AS (
    SELECT e.title, c.gate, date_bin('5 minutes', c.checked_in_at, timestamptz '2000-01-01') AS bucket, count(*) AS scans
      FROM app.check_ins c JOIN app.events e USING (event_id)
     GROUP BY 1, 2, 3
)
SELECT title, gate, bucket, scans,
       round(scans / 5.0, 1) AS scans_per_minute
  FROM (SELECT *, row_number() OVER (PARTITION BY title, gate ORDER BY scans DESC) AS rn FROM buckets) b
 WHERE rn = 1
 ORDER BY scans DESC LIMIT 10;

-- name: promo_effectiveness
-- Do promo codes bring larger orders? Orders with and without a code.
SELECT (promo_id IS NOT NULL) AS used_promo, count(*) AS orders,
       round(avg(subtotal), 2) AS avg_subtotal, round(avg(discount), 2) AS avg_discount,
       round(avg(total), 2) AS avg_paid, sum(discount) AS total_discount
  FROM app.orders WHERE status IN ('paid', 'refunded') AND subtotal > 0
 GROUP BY 1 ORDER BY 1;

-- name: refund_reasons
-- Why do people ask for their money back, and how much does it cost?
SELECT reason, count(*) AS refunds, sum(amount) AS refunded,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct
  FROM app.refunds GROUP BY reason ORDER BY refunds DESC;

-- name: speaker_leaderboard
-- Which speakers present most often, and how are their events rated?
WITH ratings AS (SELECT event_id, avg(rating) AS avg_rating, count(*) AS n FROM app.feedback GROUP BY event_id)
SELECT sp.full_name, sp.company, count(DISTINCT ss.session_id) AS sessions, count(DISTINCT s.event_id) AS events,
       round(avg(r.avg_rating), 2) AS avg_event_rating
  FROM app.speakers sp
  JOIN app.session_speakers ss USING (speaker_id)
  JOIN app.sessions s USING (session_id)
  LEFT JOIN ratings r USING (event_id)
 GROUP BY sp.speaker_id
 ORDER BY sessions DESC, avg_event_rating DESC NULLS LAST LIMIT 10;

-- name: city_quarter_revenue
-- Revenue by city and quarter as a pivot table (conditional aggregation with FILTER).
SELECT v.city,
       sum(o.total) FILTER (WHERE date_trunc('quarter', o.paid_at) = date_trunc('quarter', q.ref - interval '9 months')) AS q_minus_3,
       sum(o.total) FILTER (WHERE date_trunc('quarter', o.paid_at) = date_trunc('quarter', q.ref - interval '6 months')) AS q_minus_2,
       sum(o.total) FILTER (WHERE date_trunc('quarter', o.paid_at) = date_trunc('quarter', q.ref - interval '3 months')) AS q_minus_1,
       sum(o.total) FILTER (WHERE date_trunc('quarter', o.paid_at) = date_trunc('quarter', q.ref)) AS this_quarter
  FROM app.orders o
  JOIN app.events e USING (event_id)
  JOIN app.venues v USING (venue_id)
 CROSS JOIN (SELECT max(paid_at) AS ref FROM app.orders) q
 WHERE o.status IN ('paid', 'refunded')
 GROUP BY v.city ORDER BY this_quarter DESC NULLS LAST;

-- name: rating_vs_sellthrough
-- Do better-rated events sell more? Correlation per category.
WITH ev AS (
    SELECT e.event_id, c.name AS category, s.sell_through_pct, avg(f.rating) AS rating
      FROM app.events e
      JOIN app.event_categories c USING (category_id)
      JOIN report.event_sales s USING (event_id)
      JOIN app.feedback f USING (event_id)
     WHERE e.status = 'completed'
     GROUP BY e.event_id, c.name, s.sell_through_pct
)
SELECT category, count(*) AS events, round(avg(rating), 2) AS avg_rating,
       round(corr(rating, sell_through_pct)::numeric, 2) AS correlation
  FROM ev GROUP BY category HAVING count(*) >= 15 ORDER BY avg_rating DESC;

-- name: unmet_demand
-- Where is demand larger than supply? Sold-out ticket types with people waiting.
SELECT e.title, tt.name AS ticket_type, tt.quantity_total AS seats, count(w.*) AS people_waiting,
       sum(w.quantity) AS seats_wanted, round(100.0 * sum(w.quantity) / tt.quantity_total, 1) AS extra_demand_pct
  FROM app.waitlist w
  JOIN app.ticket_types tt USING (ticket_type_id)
  JOIN app.events e USING (event_id)
 WHERE w.status = 'waiting'
 GROUP BY e.title, tt.ticket_type_id ORDER BY seats_wanted DESC LIMIT 10;

-- name: search_events
-- Full-text search: the best matches for "data engineering", ranked.
SELECT title, ts_rank(search, q) AS rank, starts_at::date AS date
  FROM app.events, websearch_to_tsquery('english', 'data engineering') q
 WHERE search @@ q
 ORDER BY rank DESC, starts_at DESC LIMIT 5;

-- name: room_utilization
-- How busy are the rooms? Booked hours per room (top 10).
SELECT v.name AS venue, r.name AS room,
       count(*) AS sessions,
       round(sum(extract(epoch FROM s.ends_at - s.starts_at)) / 3600, 1) AS booked_hours
  FROM app.sessions s JOIN app.rooms r USING (room_id) JOIN app.venues v USING (venue_id)
 GROUP BY v.name, r.name ORDER BY booked_hours DESC LIMIT 10;

-- name: suspicious_scans
-- Possible ticket sharing: rejected re-scans by gate.
SELECT gate, count(*) FILTER (WHERE result = 'already_checked_in') AS reused_tickets,
       count(*) FILTER (WHERE result = 'not_found') AS fake_codes,
       count(*) FILTER (WHERE result = 'cancelled') AS refunded_tickets,
       round(100.0 * count(*) FILTER (WHERE result <> 'admitted') / count(*), 2) AS rejected_pct
  FROM app.scan_attempts GROUP BY gate ORDER BY rejected_pct DESC;
