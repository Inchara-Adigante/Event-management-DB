"""Event day: door scanning, feedback, audit history and the housekeeping procedure."""
import threading
import uuid
from datetime import timedelta

import psycopg
import pytest
from psycopg import errors

from conftest import one


def ticket_codes(con, order):
    return [r[0] for r in con.execute("""SELECT t.code FROM app.tickets t JOIN app.order_items oi USING (order_item_id)
                                         WHERE oi.order_id = %s ORDER BY t.ticket_id""", (order,))]


def test_door_scanner_results(con, f):
    ev, other = f.event(starts_in=timedelta(hours=1)), f.event(starts_in=timedelta(hours=1))
    tt = f.ticket_type(ev)
    code, refunded_code = ticket_codes(con, f.buy(f.user(), tt))[0], None
    refunded_order = f.buy(f.user(), tt)
    refunded_code = ticket_codes(con, refunded_order)[0]
    con.execute("SELECT app.refund_order(%s, 'x')", (refunded_order,))

    scan = lambda c, e: one(con, "SELECT app.check_in_ticket(%s, %s, 'Gate A')", (c, e))  # noqa: E731
    assert scan(code, other["id"]) == "wrong_event"
    assert scan(code, ev["id"]) == "admitted"
    assert scan(code, ev["id"]) == "already_checked_in"
    assert scan(refunded_code, ev["id"]) == "cancelled"
    assert scan(uuid.uuid4(), ev["id"]) == "not_found"
    assert one(con, "SELECT count(*) FROM app.scan_attempts") == 5
    assert one(con, "SELECT count(*) FROM app.check_ins") == 1


def test_doors_open_two_hours_before_start(con, f):
    ev = f.event(starts_in=timedelta(hours=5))
    code = ticket_codes(con, f.buy(f.user(), f.ticket_type(ev)))[0]
    assert one(con, "SELECT app.check_in_ticket(%s, %s, 'Gate A')", (code, ev["id"])) == "too_early"


def test_two_gates_scanning_the_same_ticket_admit_it_once(con, f, db_url):
    ev = f.event(starts_in=timedelta(hours=1))
    code = ticket_codes(con, f.buy(f.user(), f.ticket_type(ev)))[0]
    barrier, results = threading.Barrier(8), []

    def scan(gate):
        with psycopg.connect(db_url, autocommit=True) as c:
            barrier.wait()
            results.append(c.execute("SELECT app.check_in_ticket(%s, %s, %s)", (code, ev["id"], gate)).fetchone()[0])

    threads = [threading.Thread(target=scan, args=(f"Gate {i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["admitted"] + ["already_checked_in"] * 7


def test_only_attendees_can_rate_an_event(con, f):
    ev = f.event(starts_in=timedelta(hours=1))
    tt = f.ticket_type(ev)
    attendee, no_show = f.user(), f.user()
    code = ticket_codes(con, f.buy(attendee, tt))[0]
    f.buy(no_show, tt)
    con.execute("SELECT app.check_in_ticket(%s, %s, 'Gate A')", (code, ev["id"]))
    con.execute("INSERT INTO app.feedback (event_id, user_id, rating) VALUES (%s, %s, 5)", (ev["id"], attendee))
    with pytest.raises(errors.CheckViolation, match="did not attend"):
        con.execute("INSERT INTO app.feedback (event_id, user_id, rating) VALUES (%s, %s, 1)", (ev["id"], no_show))
    with pytest.raises(errors.UniqueViolation):
        con.execute("INSERT INTO app.feedback (event_id, user_id, rating) VALUES (%s, %s, 4)", (ev["id"], attendee))


def test_audit_log_keeps_only_changed_columns(con, f):
    ev = f.event()
    old_title = one(con, "SELECT title FROM app.events WHERE event_id = %s", (ev["id"],))
    with con.transaction():
        con.execute("SET LOCAL app.user_id = '7'")
        con.execute("UPDATE app.events SET title = 'Renamed', description = description WHERE event_id = %s", (ev["id"],))
    row = con.execute("""SELECT old_values, new_values, app_user FROM audit.change_log
                         WHERE table_name = 'events' AND operation = 'UPDATE'""").fetchone()
    assert row == ({"title": old_title}, {"title": "Renamed"}, "7")


def test_inventory_changes_are_audited(con, f):
    tt = f.ticket_type(f.event())
    f.buy(f.user(), tt, qty=2)
    change = con.execute("""SELECT old_values, new_values FROM audit.change_log
                            WHERE table_name = 'ticket_types' AND operation = 'UPDATE'""").fetchone()
    assert change == ({"quantity_sold": 0}, {"quantity_sold": 2})


def test_housekeeping_completes_finished_events(con, f):
    ev = f.event()
    con.execute("UPDATE app.events SET starts_at = now() - interval '2 days', ends_at = now() - interval '1 day' WHERE event_id = %s",
                (ev["id"],))
    con.execute("CALL app.complete_finished_events()")
    assert one(con, "SELECT status FROM app.events WHERE event_id = %s", (ev["id"],)) == "completed"
