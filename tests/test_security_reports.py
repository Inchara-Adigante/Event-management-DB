"""Row-level security, role permissions, reporting views, migrations and the seed generator."""
import subprocess
import sys
from datetime import timedelta

import psycopg
import pytest
from psycopg import errors

from conftest import ROOT, one
import migrate


def as_organizer(con, org_id):
    con.execute("SET ROLE ems_organizer")
    if org_id is not None:
        con.execute("SELECT set_config('app.org_id', %s, false)", (str(org_id),))


@pytest.fixture
def two_orgs(con, f):
    a, b = f.event(), f.event()
    f.buy(f.user(), f.ticket_type(a), qty=2)
    f.buy(f.user(), f.ticket_type(b), qty=3)
    return a, b


def test_organizers_only_see_their_own_events_orders_and_tickets(con, two_orgs):
    a, b = two_orgs
    as_organizer(con, a["org"])
    try:
        assert [r[0] for r in con.execute("SELECT event_id FROM app.events")] == [a["id"]]
        assert one(con, "SELECT count(*) FROM app.orders") == 1
        assert one(con, "SELECT count(*) FROM app.tickets") == 2
        assert one(con, "SELECT count(*) FROM app.order_items") == 1
        # Updating another organizer's event silently matches nothing.
        con.execute("UPDATE app.events SET title = 'hijacked' WHERE event_id = %s", (b["id"],))
    finally:
        con.execute("RESET ROLE")
    assert one(con, "SELECT title FROM app.events WHERE event_id = %s", (b["id"],)) != "hijacked"


def test_without_an_organization_set_nothing_is_visible(con, two_orgs):
    as_organizer(con, None)
    try:
        assert one(con, "SELECT count(*) FROM app.events") == 0
        assert one(con, "SELECT count(*) FROM app.tickets") == 0
    finally:
        con.execute("RESET ROLE")


def test_organizer_staff_cannot_touch_money_tables(con, two_orgs):
    as_organizer(con, two_orgs[0]["org"])
    try:
        with pytest.raises(errors.InsufficientPrivilege):
            con.execute("SELECT * FROM app.payments")
        with pytest.raises(errors.InsufficientPrivilege):
            con.execute("UPDATE app.events SET capacity = 1")
    finally:
        con.execute("RESET ROLE")


def test_organizer_staff_can_scan_their_own_tickets_only(con, f):
    a, b = f.event(starts_in=timedelta(hours=1)), f.event(starts_in=timedelta(hours=1))
    f.buy(f.user(), f.ticket_type(a))
    f.buy(f.user(), f.ticket_type(b))
    code_a, code_b = (one(con, "SELECT code FROM app.tickets WHERE event_id = %s", (e["id"],)) for e in (a, b))
    as_organizer(con, a["org"])
    try:
        assert one(con, "SELECT app.check_in_ticket(%s, %s, 'Gate A')", (code_a, a["id"])) == "admitted"
        assert one(con, "SELECT app.check_in_ticket(%s, %s, 'Gate A')", (code_b, b["id"])) == "not_found"
    finally:
        con.execute("RESET ROLE")


def test_analysts_read_reports_but_not_raw_tables(con, two_orgs):
    con.execute("SET ROLE ems_analyst")
    try:
        assert one(con, "SELECT count(*) FROM report.event_sales") == 2
        with pytest.raises(errors.InsufficientPrivilege):
            con.execute("SELECT * FROM app.users")
    finally:
        con.execute("RESET ROLE")


def test_event_sales_report_adds_up(con, f):
    ev = f.event()
    tt = f.ticket_type(ev, qty=10, price=25)
    f.promo(ev, "HALF", "percent", 50)
    f.buy(f.user(), tt, qty=4)                         # 100
    f.buy(f.user(), tt, qty=2, promo="HALF")          # 50 - 25
    refunded = f.buy(f.user(), tt, qty=1)              # 25, refunded
    con.execute("SELECT app.refund_order(%s, 'x')", (refunded,))
    row = con.execute("""SELECT seats_offered, seats_sold, sell_through_pct, orders, gross_revenue, discounts, refunds, net_revenue
                         FROM report.event_sales WHERE event_id = %s""", (ev["id"],)).fetchone()
    assert row == (10, 6, 60.0, 3, 150, 25, 25, 125)


def test_daily_revenue_materialized_view_refreshes(con, f):
    f.buy(f.user(), f.ticket_type(f.event(), price=10), qty=3)
    con.execute("SELECT report.refresh()")
    con.execute("SELECT report.refresh()")              # second time runs CONCURRENTLY
    assert con.execute("SELECT orders, tickets, revenue FROM report.daily_revenue").fetchone() == (1, 3, 30)


def test_editing_an_applied_migration_is_detected(db_url, tmp_path, monkeypatch):
    assert migrate.migrate(db_url) == []               # already up to date
    fake = tmp_path / "migrations"
    fake.mkdir()
    for p in migrate.MIGRATIONS.glob("*.sql"):
        (fake / p.name).write_text(p.read_text())
    (fake / "001_foundation.sql").write_text("-- edited\n" + (fake / "001_foundation.sql").read_text())
    monkeypatch.setattr(migrate, "MIGRATIONS", fake)
    with pytest.raises(SystemExit, match="changed after it was applied"):
        migrate.migrate(db_url)


def test_seed_generator_loads_with_every_rule_enforced(con, db_url):
    out = subprocess.run([sys.executable, str(ROOT / "db" / "seed" / "generate.py"), "--scale", "0.03"],
                         env={"DATABASE_URL": db_url, "PATH": ""}, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    # Inventory counters equal the tickets that are actually live.
    assert one(con, """SELECT count(*) FROM app.ticket_types tt
                       WHERE quantity_sold <> (SELECT count(*) FROM app.tickets t JOIN app.order_items oi USING (order_item_id)
                                               WHERE oi.ticket_type_id = tt.ticket_type_id AND t.status <> 'cancelled')""") == 0
    # Every paid order has a captured payment of the same amount.
    assert one(con, """SELECT count(*) FROM app.orders o JOIN app.payments p USING (order_id)
                       WHERE o.status = 'paid' AND (p.status <> 'captured' OR p.amount <> o.total)""") == 0
    # Promo usage counters match the orders that used them.
    assert one(con, """SELECT count(*) FROM app.promo_codes pc
                       WHERE times_used <> (SELECT count(*) FROM app.orders o WHERE o.promo_id = pc.promo_id)""") == 0
    assert one(con, "SELECT count(*) FROM app.events WHERE status = 'completed'") > 0
    assert one(con, "SELECT count(*) FROM report.daily_revenue") > 0
