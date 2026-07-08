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
