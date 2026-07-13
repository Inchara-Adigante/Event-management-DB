"""Refunds return seats; freed seats go to the waitlist in arrival order and are held for 24 hours."""
from datetime import timedelta

import psycopg
import pytest
from psycopg import errors

from conftest import one


def test_refund_returns_money_and_seats(con, f):
    tt = f.ticket_type(f.event(), qty=5, price=30)
    order = f.buy(f.user(), tt, qty=2)
    assert one(con, "SELECT app.refund_order(%s, 'Schedule conflict')", (order,)) == 60
    assert one(con, "SELECT status FROM app.orders WHERE order_id = %s", (order,)) == "refunded"
    assert one(con, "SELECT status FROM app.payments WHERE order_id = %s", (order,)) == "refunded"
    assert one(con, "SELECT amount FROM app.refunds WHERE order_id = %s", (order,)) == 60
    assert one(con, "SELECT count(*) FROM app.tickets WHERE status = 'cancelled'") == 2
    assert one(con, "SELECT quantity_sold FROM app.ticket_types WHERE ticket_type_id = %s", (tt,)) == 0


def test_an_order_can_only_be_refunded_once(con, f):
    order = f.buy(f.user(), f.ticket_type(f.event()))
    con.execute("SELECT app.refund_order(%s, 'first')", (order,))
    with pytest.raises(psycopg.Error, match="only paid orders") as e:
        con.execute("SELECT app.refund_order(%s, 'again')", (order,))
    assert e.value.sqlstate == "EV006"


def test_no_refunds_once_the_event_has_started(con, f):
    ev = f.event()
    order = f.buy(f.user(), f.ticket_type(ev))
    con.execute("UPDATE app.events SET starts_at = now() - interval '1 hour', ends_at = now() + interval '2 hours' WHERE event_id = %s", (ev["id"],))
    with pytest.raises(psycopg.Error, match="refunds close"):
        con.execute("SELECT app.refund_order(%s, 'too late')", (order,))


def test_refunds_can_never_exceed_the_payment(con, f):
    order = f.buy(f.user(), f.ticket_type(f.event(), price=50))
    pay = one(con, "SELECT payment_id FROM app.payments WHERE order_id = %s", (order,))
    con.execute("INSERT INTO app.refunds (order_id, payment_id, amount, reason) VALUES (%s, %s, 30, 'partial')", (order, pay))
    with pytest.raises(errors.CheckViolation, match="more than the 50.00 captured"):
        con.execute("INSERT INTO app.refunds (order_id, payment_id, amount, reason) VALUES (%s, %s, 30, 'again')", (order, pay))
