"""Schema-level rules: constraints and integrity triggers reject bad data no matter who writes it."""
from datetime import timedelta

import psycopg
import pytest
from psycopg import errors

from conftest import NOW, one


def test_email_is_unique_regardless_of_case(con, f):
    con.execute("INSERT INTO app.users (email, full_name) VALUES ('Ada@Example.com', 'Ada')")
    with pytest.raises(errors.UniqueViolation):
        con.execute("INSERT INTO app.users (email, full_name) VALUES ('ada@example.COM', 'Ada again')")


def test_invalid_email_and_timezone_are_rejected(con):
    with pytest.raises(errors.CheckViolation):
        con.execute("INSERT INTO app.users (email, full_name) VALUES ('not-an-email', 'X')")
    with pytest.raises(errors.CheckViolation):
        con.execute("""INSERT INTO app.venues (name, address_line, city, capacity, timezone)
                       VALUES ('V', '1 St', 'Boston', 10, 'Mars/Olympus_Mons')""")


def test_an_organization_has_exactly_one_owner(con, f):
    org = f.org()
    with pytest.raises(errors.UniqueViolation):
        con.execute("INSERT INTO app.org_members (org_id, user_id, role) VALUES (%s, %s, 'owner')", (org, f.user()))
    con.execute("INSERT INTO app.org_members (org_id, user_id, role) VALUES (%s, %s, 'admin')", (org, f.user()))


def test_a_room_cannot_be_double_booked(con, f):
    ev = f.event()
    room, start = ev["rooms"][0], ev["start"]
    add = "INSERT INTO app.sessions (event_id, room_id, title, starts_at, ends_at) VALUES (%s, %s, %s, %s, %s)"
    con.execute(add, (ev["id"], room, "Talk A", start, start + timedelta(hours=1)))
    with pytest.raises(errors.ExclusionViolation):
        con.execute(add, (ev["id"], room, "Talk B", start + timedelta(minutes=30), start + timedelta(hours=2)))
    # Back-to-back is fine: ranges are half-open [start, end).
    con.execute(add, (ev["id"], room, "Talk C", start + timedelta(hours=1), start + timedelta(hours=2)))
    # The same time in another room is fine too.
    con.execute(add, (ev["id"], ev["rooms"][1], "Talk D", start, start + timedelta(hours=1)))


def test_double_booking_is_blocked_across_different_events(con, f):
    venue = f.venue()
    ev1, ev2 = f.event(venue=venue), f.event(venue=venue)
    add = "INSERT INTO app.sessions (event_id, room_id, title, starts_at, ends_at) VALUES (%s, %s, %s, %s, %s)"
    con.execute(add, (ev1["id"], venue[1][0], "Mine", ev1["start"], ev1["start"] + timedelta(hours=1)))
    with pytest.raises(errors.ExclusionViolation):
        con.execute(add, (ev2["id"], venue[1][0], "Yours", ev2["start"], ev2["start"] + timedelta(hours=1)))


def test_sessions_stay_inside_the_event_and_its_venue(con, f):
    ev, other_venue = f.event(hours=3), f.venue()
    add = "INSERT INTO app.sessions (event_id, room_id, title, starts_at, ends_at) VALUES (%s, %s, %s, %s, %s)"
    with pytest.raises(errors.CheckViolation, match="outside the event time window"):
        con.execute(add, (ev["id"], ev["rooms"][0], "Late", ev["end"] - timedelta(minutes=30), ev["end"] + timedelta(hours=1)))
    with pytest.raises(errors.CheckViolation, match="not in the venue"):
        con.execute(add, (ev["id"], other_venue[1][0], "Elsewhere", ev["start"], ev["start"] + timedelta(hours=1)))


def test_event_capacity_cannot_exceed_the_venue(con, f):
    with pytest.raises(errors.CheckViolation, match="exceeds venue capacity"):
        f.event(capacity=5000, venue=f.venue(capacity=1000))


def test_event_status_only_moves_forward(con, f):
    ev = f.event(status="draft")
    con.execute("UPDATE app.events SET status = 'published' WHERE event_id = %s", (ev["id"],))
    assert one(con, "SELECT published_at IS NOT NULL FROM app.events WHERE event_id = %s", (ev["id"],))
    con.execute("UPDATE app.events SET status = 'completed' WHERE event_id = %s", (ev["id"],))
    with pytest.raises(errors.CheckViolation, match="cannot change from completed to draft"):
        con.execute("UPDATE app.events SET status = 'draft' WHERE event_id = %s", (ev["id"],))


def test_ticket_tiers_must_fit_the_event_capacity(con, f):
    ev = f.event(capacity=100)
    f.ticket_type(ev, qty=60)
    f.ticket_type(ev, qty=40)
    with pytest.raises(errors.CheckViolation, match="would total 101 seats"):
        f.ticket_type(ev, qty=1)


def test_inventory_can_never_be_oversold_even_by_direct_updates(con, f):
    tt = f.ticket_type(f.event(), qty=5)
    with pytest.raises(errors.CheckViolation, match="ticket_types_inventory"):
        con.execute("UPDATE app.ticket_types SET quantity_sold = 6 WHERE ticket_type_id = %s", (tt,))


def test_order_totals_must_add_up(con, f):
    ev = f.event()
    with pytest.raises(errors.CheckViolation):
        con.execute("""INSERT INTO app.orders (user_id, event_id, status, subtotal, discount, total, paid_at)
                       VALUES (%s, %s, 'paid', 100, 10, 95, now())""", (f.user(), ev["id"]))


def test_paid_orders_must_have_a_payment_time(con, f):
    ev = f.event()
    with pytest.raises(errors.CheckViolation):
        con.execute("""INSERT INTO app.orders (user_id, event_id, status, subtotal, discount, total)
                       VALUES (%s, %s, 'paid', 100, 0, 100)""", (f.user(), ev["id"]))


def test_ticket_must_belong_to_the_event_of_its_order(con, f):
    ev, other = f.event(), f.event()
    order = f.buy(f.user(), f.ticket_type(ev))
    item = one(con, "SELECT order_item_id FROM app.order_items WHERE order_id = %s", (order,))
    with pytest.raises(psycopg.errors.ForeignKeyViolation, match="does not match"):
        con.execute("""INSERT INTO app.tickets (order_item_id, event_id, attendee_name, attendee_email)
                       VALUES (%s, %s, 'Sneaky', 'x@example.com')""", (item, other["id"]))


def test_full_text_search_column_is_maintained(con, f):
    f.event()
    assert one(con, "SELECT count(*) FROM app.events WHERE search @@ websearch_to_tsquery('english', 'database')") == 1
