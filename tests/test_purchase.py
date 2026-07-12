"""Checkout rules, atomicity and behaviour under concurrent buyers."""
import threading
from datetime import timedelta

import psycopg
import pytest

from conftest import NOW, one


def sqlstate(exc_info):
    return exc_info.value.sqlstate


def test_purchase_issues_tickets_payment_and_updates_inventory(con, f):
    ev = f.event()
    tt = f.ticket_type(ev, qty=10, price=40)
    buyer = f.user("Grace Hopper")
    order = f.buy(buyer, tt, qty=3)
    assert con.execute("SELECT status, subtotal, total FROM app.orders WHERE order_id = %s", (order,)).fetchone() == ("paid", 120, 120)
    assert one(con, "SELECT count(*) FROM app.tickets WHERE event_id = %s AND attendee_name = 'Grace Hopper'", (ev["id"],)) == 3
    assert one(con, "SELECT quantity_sold FROM app.ticket_types WHERE ticket_type_id = %s", (tt,)) == 3
    assert con.execute("SELECT amount, status FROM app.payments WHERE order_id = %s", (order,)).fetchone() == (120, "captured")
    assert one(con, "SELECT count(DISTINCT code) FROM app.tickets") == 3


def test_sold_out(con, f):
    tt = f.ticket_type(f.event(), qty=2)
    f.buy(f.user(), tt, qty=2)
    with pytest.raises(psycopg.Error, match="sold out") as e:
        f.buy(f.user(), tt)
    assert sqlstate(e) == "EV001"


def test_sales_window_is_enforced(con, f):
    ev = f.event()
    tt = f.ticket_type(ev, sales_start=NOW() + timedelta(days=1))
    with pytest.raises(psycopg.Error, match="not on sale") as e:
        f.buy(f.user(), tt)
    assert sqlstate(e) == "EV002"


def test_per_order_limit(con, f):
    tt = f.ticket_type(f.event(), max_per_order=4)
    with pytest.raises(psycopg.Error, match="at most 4") as e:
        f.buy(f.user(), tt, qty=5)
    assert sqlstate(e) == "EV004"


def test_draft_and_past_events_cannot_be_booked(con, f):
    draft = f.event(status="draft")
    with pytest.raises(psycopg.Error, match="not open for booking") as e:
        f.buy(f.user(), f.ticket_type(draft))
    assert sqlstate(e) == "EV005"


def test_one_order_one_event(con, f):
    a, b = f.ticket_type(f.event()), f.ticket_type(f.event())
    with pytest.raises(psycopg.Error, match="one event") as e:
        con.execute("SELECT app.purchase_tickets(%s, %s::jsonb)",
                    (f.user(), f'[{{"ticket_type_id": {a}, "quantity": 1}}, {{"ticket_type_id": {b}, "quantity": 1}}]'))
    assert sqlstate(e) == "EV007"


def test_a_failed_order_leaves_no_trace(con, f):
    ev = f.event()
    plenty, scarce = f.ticket_type(ev, qty=50), f.ticket_type(ev, qty=1)
    with pytest.raises(psycopg.Error, match="sold out"):
        con.execute("SELECT app.purchase_tickets(%s, %s::jsonb)",
                    (f.user(), f'[{{"ticket_type_id": {plenty}, "quantity": 3}}, {{"ticket_type_id": {scarce}, "quantity": 2}}]'))
    assert one(con, "SELECT count(*) FROM app.orders") == 0
    assert one(con, "SELECT count(*) FROM app.tickets") == 0
    assert one(con, "SELECT sum(quantity_sold) FROM app.ticket_types") == 0


def test_promo_codes_percent_amount_and_usage_limit(con, f):
    ev = f.event()
    tt = f.ticket_type(ev, price=80)
    f.promo(ev, "TEAM25", "percent", 25, max_uses=1)
    f.promo(ev, "TENOFF", "amount", 10)
    o1 = f.buy(f.user(), tt, qty=2, promo="team25")              # codes are case-insensitive
    assert con.execute("SELECT subtotal, discount, total FROM app.orders WHERE order_id = %s", (o1,)).fetchone() == (160, 40, 120)
    with pytest.raises(psycopg.Error, match="not valid") as e:
        f.buy(f.user(), tt, promo="TEAM25")
    assert sqlstate(e) == "EV003"
    o2 = f.buy(f.user(), tt, promo="TENOFF")
    assert one(con, "SELECT total FROM app.orders WHERE order_id = %s", (o2,)) == 70


def _race(url, n, work):
    """Run work(conn) in n threads that start at the same moment; return (successes, sqlstates of failures)."""
    barrier, ok, failed, lock = threading.Barrier(n), [], [], threading.Lock()

    def run():
        with psycopg.connect(url, autocommit=True) as c:
            barrier.wait()
            try:
                result = work(c)
                with lock:
                    ok.append(result)
            except psycopg.Error as exc:
                with lock:
                    failed.append(exc.sqlstate)

    threads = [threading.Thread(target=run) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return ok, failed


def test_concurrent_buyers_never_oversell(con, f, db_url):
    tt = f.ticket_type(f.event(), qty=25)
    users = [f.user() for _ in range(40)]
    it = iter(users)
    lock = threading.Lock()

    def buy(c):
        with lock:
            u = next(it)
        return c.execute("SELECT app.purchase_tickets(%s, %s::jsonb)",
                         (u, f'[{{"ticket_type_id": {tt}, "quantity": 1}}]')).fetchone()[0]

    ok, failed = _race(db_url, 40, buy)
    assert len(ok) == 25 and failed == ["EV001"] * 15
    assert one(con, "SELECT quantity_sold FROM app.ticket_types WHERE ticket_type_id = %s", (tt,)) == 25
    assert one(con, "SELECT count(*) FROM app.tickets") == 25


def test_last_use_of_a_promo_code_goes_to_exactly_one_buyer(con, f, db_url):
    ev = f.event()
    tt = f.ticket_type(ev, qty=50, price=100)
    f.promo(ev, "ONLYONE", "percent", 50, max_uses=1)
    users = iter([f.user() for _ in range(10)])
    lock = threading.Lock()

    def buy(c):
        with lock:
            u = next(users)
        return c.execute("SELECT app.purchase_tickets(%s, %s::jsonb, 'ONLYONE')",
                         (u, f'[{{"ticket_type_id": {tt}, "quantity": 1}}]')).fetchone()[0]

    ok, failed = _race(db_url, 10, buy)
    assert len(ok) == 1 and failed == ["EV003"] * 9
    assert one(con, "SELECT times_used FROM app.promo_codes") == 1
