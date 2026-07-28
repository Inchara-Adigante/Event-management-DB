# Analytics results

Output of `python scripts/run_queries.py` on the seeded database (`python db/seed/generate.py --as-of 2026-07-28`). The SQL is in [queries/analytics.sql](../queries/analytics.sql).

## top_events
*Which events earned the most, and how full did they get?*  (10 rows, 53 ms)

| rank | title | organizer | city | seats_sold | sell_through_pct | net_revenue |
|---|---|---|---|---|---|---|
| 1 | React Summit 2026 | Jackson Productions | Nashville | 1,300 | 94.6 | 796,473.00 |
| 2 | Los Angeles Summer Music Festival 2025 | Russell Group | Los Angeles | 3,480 | 86.0 | 735,909.00 |
| 3 | Nashville Sunset Music Festival 2026 | May Productions | Nashville | 3,219 | 86.0 | 677,665.00 |
| 4 | Nashville Sunset Music Festival 2026 | Heath Group | Nashville | 2,887 | 68.5 | 653,741.00 |
| 5 | Startup Growth Days Boston | Mckenzie Collective | Boston | 1,032 | 76.8 | 632,511.00 |
| 6 | Atlanta Riverfront Music Festival 2025 | Mills Collective | Atlanta | 3,648 | 82.0 | 622,848.00 |
| 7 | MLOps Summit 2025 | Washington Collective | Washington | 959 | 71.8 | 593,381.25 |
| 8 | Fintech Days New York | Kaiser Foundation | New York | 941 | 93.2 | 567,474.30 |
| 9 | Security Days Nashville | Chen Society | Nashville | 950 | 76.6 | 566,164.10 |
| 10 | Founders World 2025 | Mcdaniel Productions | Seattle | 872 | 63.7 | 547,869.00 |

## monthly_revenue_growth
*How is revenue trending month over month? (window functions: LAG and a running total)*  (21 rows, 124 ms)

| month | orders | revenue | mom_growth_pct | running_total |
|---|---|---|---|---|
| 2024-11-01 | 1 | 775.00 |  | 775.00 |
| 2024-12-01 | 211 | 198,296.50 | 25,486.60 | 199,071.50 |
| 2025-01-01 | 919 | 562,225.45 | 183.5 | 761,296.95 |
| 2025-02-01 | 2,346 | 1,118,852.75 | 99.0 | 1,880,149.70 |
| 2025-03-01 | 4,688 | 2,238,387.25 | 100.1 | 4,118,536.95 |
| 2025-04-01 | 7,374 | 3,436,954.90 | 53.5 | 7,555,491.85 |
| 2025-05-01 | 12,297 | 5,865,038.20 | 70.6 | 13,420,530.05 |
| 2025-06-01 | 14,913 | 6,570,320.45 | 12.0 | 19,990,850.50 |
| 2025-07-01 | 15,308 | 6,620,806.45 | 0.8 | 26,611,656.95 |
| 2025-08-01 | 14,328 | 7,289,004.95 | 10.1 | 33,900,661.90 |
| 2025-09-01 | 12,792 | 7,071,169.80 | -3.0 | 40,971,831.70 |
| 2025-10-01 | 13,107 | 6,830,551.65 | -3.4 | 47,802,383.35 |

*... 9 more rows*

## category_rollup
*Revenue by category, rolled up the category tree (recursive CTE + ROLLUP).*  (24 rows, 48 ms)

| top_level | category | events | net_revenue |
|---|---|---|---|
| Arts & Culture | Exhibitions | 34 | 235,215.70 |
| Arts & Culture | Film Screenings | 45 | 79,860.00 |
| Arts & Culture | Theatre | 48 | 1,329,908.65 |
| Arts & Culture | (subtotal) | 127 | 1,644,984.35 |
| Business | Finance | 50 | 9,318,884.45 |
| Business | Marketing | 43 | 7,744,407.50 |
| Business | Startups | 59 | 10,951,128.65 |
| Business | (subtotal) | 152 | 28,014,420.60 |
| Community | Charity Runs | 69 | 1,243,417.35 |
| Community | Meetups | 71 | 0.00 |
| Community | (subtotal) | 140 | 1,243,417.35 |
| Education | Career Fairs | 58 | 0.00 |

*... 12 more rows*

## sales_velocity
*How far ahead do people buy? Share of tickets by days before the event.*  (6 rows, 225 ms)

| bought_before_event | tickets | pct |
|---|---|---|
| 60+ days | 202,890 | 47.7 |
| 30-59 days | 113,699 | 26.7 |
| 14-29 days | 54,449 | 12.8 |
| 7-13 days | 26,572 | 6.2 |
| 1-6 days | 23,926 | 5.6 |
| same day | 3,950 | 0.9 |

## tier_performance
*Do Early Bird tiers sell out more than General Admission? Price and sell-through per tier name.*  (10 rows, 2 ms)

| ticket_type | tiers | avg_price | sell_through_pct | sold_out |
|---|---|---|---|---|
| Early Bird | 358 | 250.31 | 77.3 | 12 |
| Student | 347 | 92.05 | 64.8 | 14 |
| Orchestra | 38 | 106.00 | 62.2 | 0 |
| 5K Entry | 49 | 33.33 | 61.9 | 0 |
| 10K Entry | 49 | 44.65 | 61.3 | 0 |
| Balcony | 38 | 55.95 | 60.8 | 0 |
| Free Registration | 47 | 0.00 | 60.3 | 0 |
| General Admission | 533 | 345.73 | 58.4 | 1 |
| Free RSVP | 50 | 0.00 | 57.0 | 0 |
| VIP | 393 | 1,048.20 | 46.5 | 0 |

## no_show_by_price
*Free events have more no-shows than paid ones.*  (4 rows, 119 ms)

| price_band | tickets | show_up_pct |
|---|---|---|
| free | 28,441 | 63.4 |
| under $50 | 52,412 | 89.5 |
| $50-199 | 110,515 | 90.1 |
| $200+ | 151,948 | 89.5 |

## repeat_attendees
*How loyal are attendees? Buyers by number of distinct events attended.*  (10 rows, 200 ms)

| events_attended | buyers | pct_of_buyers |
|---|---|---|
| 1 | 50,171 | 44.2 |
| 2 | 36,161 | 31.8 |
| 3 | 17,547 | 15.4 |
| 4 | 6,747 | 5.9 |
| 5 | 2,069 | 1.8 |
| 6 | 597 | 0.5 |
| 7 | 174 | 0.2 |
| 8 | 74 | 0.1 |
| 9 | 21 | 0.0 |
| 10+ | 47 | 0.0 |

## arrival_curve
*When do people arrive? Check-ins in 15-minute buckets relative to the start time (big events).*  (14 rows, 135 ms)

| minutes_from_start | check_ins | pct | cumulative_pct |
|---|---|---|---|
| -90 | 4,119 | 2.2 | 2.2 |
| -75 | 8,108 | 4.3 | 6.4 |
| -60 | 17,050 | 9.0 | 15.4 |
| -45 | 28,124 | 14.8 | 30.2 |
| -30 | 36,242 | 19.1 | 49.3 |
| -15 | 36,474 | 19.2 | 68.5 |
| 0 | 28,928 | 15.2 | 83.7 |
| 15 | 17,925 | 9.4 | 93.1 |
| 30 | 8,449 | 4.4 | 97.6 |
| 45 | 3,314 | 1.7 | 99.3 |
| 60 | 982 | 0.5 | 99.8 |
| 75 | 243 | 0.1 | 100.0 |

*... 2 more rows*

## busiest_gates
*Which gates need more staff? Peak 5-minute scan count per gate (top 10).*  (10 rows, 361 ms)

| title | gate | bucket | scans | scans_per_minute |
|---|---|---|---|---|
| Los Angeles Summer Music Festival 2025 | Gate A | 2025-08-20 18:40:00+00:00 | 88 | 17.6 |
| Los Angeles Summer Music Festival 2025 | Gate C | 2025-08-20 18:45:00+00:00 | 82 | 16.4 |
| Nashville Sunset Music Festival 2026 | Gate C | 2026-07-21 16:55:00+00:00 | 82 | 16.4 |
| Atlanta Riverfront Music Festival 2025 | Gate A | 2025-09-08 15:40:00+00:00 | 79 | 15.8 |
| Atlanta Riverfront Music Festival 2025 | Gate B | 2025-09-08 15:40:00+00:00 | 79 | 15.8 |
| Los Angeles Summer Music Festival 2025 | Gate B | 2025-08-20 18:40:00+00:00 | 74 | 14.8 |
| Atlanta Riverfront Music Festival 2025 | Gate C | 2025-09-08 15:50:00+00:00 | 74 | 14.8 |
| Minneapolis Harbor Music Festival 2026 | Gate B | 2026-03-30 16:30:00+00:00 | 72 | 14.4 |
| Minneapolis Harbor Music Festival 2026 | Gate C | 2026-03-30 16:50:00+00:00 | 72 | 14.4 |
| Minneapolis Harbor Music Festival 2026 | Gate A | 2026-03-30 16:50:00+00:00 | 70 | 14.0 |

## promo_effectiveness
*Do promo codes bring larger orders? Orders with and without a code.*  (2 rows, 45 ms)

| used_promo | orders | avg_subtotal | avg_discount | avg_paid | total_discount |
|---|---|---|---|---|---|
| 0 | 202,900 | 519.33 | 0.00 | 519.33 | 0.00 |
| 1 | 9,687 | 520.04 | 95.24 | 424.80 | 922,630.65 |

## refund_reasons
*Why do people ask for their money back, and how much does it cost?*  (5 rows, 2 ms)

| reason | refunds | refunded | pct |
|---|---|---|---|
| Event cancelled by organizer | 1,970 | 796,159.70 | 23.8 |
| Schedule conflict | 1,618 | 845,841.10 | 19.6 |
| Duplicate purchase | 1,567 | 796,164.05 | 19.0 |
| Can no longer attend | 1,565 | 819,059.40 | 18.9 |
| Bought the wrong ticket type | 1,548 | 788,434.10 | 18.7 |

## speaker_leaderboard
*Which speakers present most often, and how are their events rated?*  (10 rows, 45 ms)

| full_name | company | sessions | events | avg_event_rating |
|---|---|---|---|---|
| Patricia Stanley | Schroeder, Winters and Wilson | 39 | 38 | 3.93 |
| Douglas Gonzalez | Hodge, Smith and Alvarado | 38 | 36 | 3.91 |
| Brittany Peters | Johnson-Mcfarland | 37 | 36 | 3.84 |
| Ethan Mccoy | Harper, Porter and Harrison | 36 | 34 | 4.01 |
| Michael Mitchell | Shah, Church and Bauer | 36 | 35 | 3.96 |
| James Fletcher | Hall LLC | 36 | 36 | 3.84 |
| Erica Wood | Henry, Hicks and Norton | 36 | 36 | 3.69 |
| Nathan Stanley | Rodriguez Inc | 35 | 35 | 3.95 |
| Nicole Marshall | Harris, Hicks and Miller | 35 | 34 | 3.81 |
| Samantha Brown | Villegas, Gordon and Allen | 34 | 33 | 3.88 |

## city_quarter_revenue
*Revenue by city and quarter as a pivot table (conditional aggregation with FILTER).*  (15 rows, 285 ms)

| city | q_minus_3 | q_minus_2 | q_minus_1 | this_quarter |
|---|---|---|---|---|
| Philadelphia | 1,329,508.25 | 1,467,818.40 | 1,291,059.15 | 1,111,213.00 |
| San Francisco | 2,020,774.75 | 1,047,061.75 | 1,869,623.45 | 917,215.10 |
| Nashville | 2,256,941.50 | 2,753,294.40 | 2,141,707.10 | 772,707.00 |
| Austin | 1,436,927.15 | 779,295.85 | 1,198,229.25 | 740,815.45 |
| Denver | 1,459,140.40 | 983,604.20 | 1,169,036.50 | 688,273.45 |
| Los Angeles | 1,399,622.70 | 1,439,063.05 | 1,315,086.45 | 585,744.25 |
| Atlanta | 1,139,569.55 | 1,833,447.90 | 1,641,447.65 | 514,638.35 |
| Chicago | 1,498,544.40 | 1,200,784.35 | 1,127,419.95 | 489,986.50 |
| Seattle | 786,465.50 | 939,699.00 | 1,353,556.60 | 476,047.25 |
| Boston | 1,308,018.75 | 1,294,232.45 | 816,776.10 | 386,976.50 |
| Minneapolis | 421,071.40 | 1,212,004.60 | 1,171,191.50 | 363,985.75 |
| Washington | 1,958,651.55 | 1,703,731.60 | 1,289,141.10 | 345,612.75 |

*... 3 more rows*

## rating_vs_sellthrough
*Do better-rated events sell more? Correlation per category.*  (17 rows, 23 ms)

| category | events | avg_rating | correlation |
|---|---|---|---|
| Workshops | 39 | 3.98 | 0.58 |
| Concerts | 35 | 3.96 | 0.38 |
| Cloud & DevOps | 55 | 3.94 | 0.66 |
| Charity Runs | 49 | 3.94 | 0.63 |
| Meetups | 47 | 3.93 | 0.41 |
| Marketing | 31 | 3.93 | 0.56 |
| Web Development | 55 | 3.91 | 0.62 |
| Theatre | 38 | 3.91 | 0.69 |
| Finance | 34 | 3.90 | 0.72 |
| Film Screenings | 33 | 3.88 | 0.55 |
| Career Fairs | 47 | 3.87 | 0.58 |
| Festivals | 38 | 3.86 | 0.45 |

*... 5 more rows*

## unmet_demand
*Where is demand larger than supply? Sold-out ticket types with people waiting.*  (10 rows, 2 ms)

| title | ticket_type | seats | people_waiting | seats_wanted | extra_demand_pct |
|---|---|---|---|---|---|
| San Francisco Frontend Conference | VIP | 33 | 39 | 55 | 166.7 |
| San Francisco Frontend Conference | Student | 41 | 39 | 46 | 112.2 |
| Machine Learning Days Denver | Early Bird | 61 | 34 | 45 | 73.8 |
| Chicago Content Marketing Conference | VIP | 106 | 31 | 39 | 36.8 |
| Austin Machine Learning Conference | Student | 74 | 29 | 38 | 51.4 |
| Cloud Security Days San Francisco | Early Bird | 59 | 31 | 37 | 62.7 |
| Phoenix Analytics Conference | Student | 47 | 30 | 36 | 76.6 |
| Phoenix Analytics Conference | VIP | 37 | 28 | 35 | 94.6 |
| New York Founders Conference | Early Bird | 48 | 29 | 35 | 72.9 |
| Zero Trust World 2026 | Student | 37 | 28 | 32 | 86.5 |

## search_events
*Full-text search: the best matches for "data engineering", ranked.*  (5 rows, 2 ms)

| title | rank | date |
|---|---|---|
| Philadelphia Data Engineering Conference | 0.99818754 | 2025-08-21 |
| Data Engineering Days Nashville | 0.998125 | 2026-11-23 |
| Data Engineering Days Nashville | 0.998125 | 2026-04-18 |
| Los Angeles Data Engineering Conference | 0.998125 | 2026-04-04 |
| Data Engineering World 2026 | 0.998125 | 2026-03-28 |

## room_utilization
*How busy are the rooms? Booked hours per room (top 10).*  (10 rows, 10 ms)

| venue | room | sessions | booked_hours |
|---|---|---|---|
| Nashville Convention Center | Ballroom A | 505 | 461.3 |
| Nashville Convention Center | Ballroom B | 490 | 446.3 |
| Atlanta Conference Center | Ballroom A | 446 | 392.3 |
| Washington Conference Center | Ballroom A | 429 | 376.5 |
| Atlanta Conference Center | Ballroom B | 425 | 371.3 |
| Washington Conference Center | Ballroom B | 420 | 367.5 |
| Nashville Convention Center | Main Hall | 275 | 328.2 |
| San Francisco Convention Center | Ballroom A | 367 | 319.5 |
| San Francisco Convention Center | Ballroom B | 355 | 307.5 |
| Miami Expo Center | Ballroom A | 368 | 306.8 |

## suspicious_scans
*Possible ticket sharing: rejected re-scans by gate.*  (4 rows, 49 ms)

| gate | reused_tickets | fake_codes | refunded_tickets | rejected_pct |
|---|---|---|---|---|
| Main Entrance | 474 | 719 | 42 | 4.03 |
| Gate A | 1,409 | 1,144 | 549 | 3.30 |
| Gate C | 1,367 | 0 | 0 | 1.49 |
| Gate B | 1,344 | 0 | 0 | 1.47 |
