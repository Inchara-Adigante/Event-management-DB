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
