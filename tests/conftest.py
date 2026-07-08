"""
Test fixtures. Tests run against a separate database (DATABASE_URL_TEST, default event_mgmt_test)
that is rebuilt from the migrations once per session and emptied after every test.

Factories create the smallest valid set of rows for a scenario, so each test reads like
the business rule it checks.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import migrate  # noqa: E402

TEST_URL = os.getenv("DATABASE_URL_TEST", "postgresql:///event_mgmt_test")
NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


@pytest.fixture(scope="session")
def db_url():
    migrate.reset_database(TEST_URL)
    migrate.migrate(TEST_URL)
    return TEST_URL


@pytest.fixture
def con(db_url):
    with psycopg.connect(db_url, autocommit=True) as c:
        yield c
    with psycopg.connect(db_url, autocommit=True) as c:
        tables = c.execute("""SELECT string_agg(format('%I.%I', schemaname, tablename), ', ')
                                FROM pg_tables WHERE schemaname IN ('app', 'audit')""").fetchone()[0]
        c.execute(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")


def one(con, sql, params=None):
    return con.execute(sql, params).fetchone()[0]


class Factory:
    def __init__(self, con):
        self.con = con
        self.n = 0

    def _next(self):
        self.n += 1
        return self.n

    def user(self, name=None):
        k = self._next()
        return one(self.con, "INSERT INTO app.users (email, full_name) VALUES (%s, %s) RETURNING user_id",
                   (f"user{k}@example.com", name or f"User {k}"))

    def org(self):
        k = self._next()
        oid = one(self.con, "INSERT INTO app.organizations (name, slug, contact_email) VALUES (%s, %s, %s) RETURNING org_id",
                  (f"Org {k}", f"org-{k}", f"org{k}@example.com"))
        self.con.execute("INSERT INTO app.org_members (org_id, user_id, role) VALUES (%s, %s, 'owner')", (oid, self.user()))
        return oid

    def venue(self, capacity=1000, rooms=("Main Hall", "Room 1")):
        k = self._next()
        vid = one(self.con, """INSERT INTO app.venues (name, address_line, city, capacity)
                               VALUES (%s, '1 Main St', 'Boston', %s) RETURNING venue_id""", (f"Venue {k}", capacity))
        room_ids = [one(self.con, "INSERT INTO app.rooms (venue_id, name, capacity) VALUES (%s, %s, 200) RETURNING room_id",
                        (vid, r)) for r in rooms]
        return vid, room_ids

    def category(self):
        k = self._next()
        return one(self.con, "INSERT INTO app.event_categories (name) VALUES (%s) RETURNING category_id", (f"Cat {k}",))

    def event(self, starts_in=timedelta(days=30), hours=8, capacity=100, status="published", org=None, venue=None):
        k = self._next()
        org = org or self.org()
        vid, rooms = venue or self.venue()
        start = NOW() + starts_in
        eid = one(self.con, """INSERT INTO app.events (org_id, venue_id, category_id, title, slug, description, status,
                                                       starts_at, ends_at, capacity, published_at)
                               VALUES (%s, %s, %s, %s, %s, 'Talks about databases', %s, %s, %s, %s, %s)
                               RETURNING event_id""",
                  (org, vid, self.category(), f"Event {k}", f"event-{k}", status, start, start + timedelta(hours=hours),
                   capacity, None if status == "draft" else NOW()))
        return dict(id=eid, org=org, venue=vid, rooms=rooms, start=start, end=start + timedelta(hours=hours))

    def ticket_type(self, event, qty=10, price=50, name=None, sales_start=None, sales_end=None, max_per_order=10):
        k = self._next()
        return one(self.con, """INSERT INTO app.ticket_types (event_id, name, price, quantity_total, sales_start, sales_end,
                                                               max_per_order)
                                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING ticket_type_id""",
                   (event["id"], name or f"Tier {k}", price, qty, sales_start or NOW() - timedelta(days=1),
                    sales_end or event["start"], max_per_order))

    def promo(self, event, code="SAVE10", kind="percent", value=10, max_uses=None):
        return one(self.con, """INSERT INTO app.promo_codes (event_id, code, discount_type, discount_value, max_uses,
                                                              valid_from, valid_until)
                                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING promo_id""",
                   (event["id"], code, kind, value, max_uses, NOW() - timedelta(days=1), event["start"]))

    def buy(self, user, tt, qty=1, promo=None):
        return one(self.con, "SELECT app.purchase_tickets(%s, %s::jsonb, %s)",
                   (user, f'[{{"ticket_type_id": {tt}, "quantity": {qty}}}]', promo))


@pytest.fixture
def f(con):
    return Factory(con)
