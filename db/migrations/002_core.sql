-- 002 Core: people, organizers, venues, events and their agenda.

CREATE TABLE app.users (
    user_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email       citext      NOT NULL UNIQUE CHECK (email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    full_name   text        NOT NULL CHECK (length(trim(full_name)) > 0),
    phone       text,
    city        text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    is_active   boolean     NOT NULL DEFAULT true
);
COMMENT ON TABLE  app.users IS 'Everyone with an account: attendees, organizer staff and speakers who log in';
COMMENT ON COLUMN app.users.email IS 'Login and contact address; case-insensitive and unique';

CREATE TABLE app.organizations (
    org_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name           text        NOT NULL UNIQUE,
    slug           text        NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    contact_email  citext      NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE app.organizations IS 'Companies, clubs and universities that host events';

CREATE TABLE app.org_members (
    org_id     bigint          NOT NULL REFERENCES app.organizations ON DELETE CASCADE,
    user_id    bigint          NOT NULL REFERENCES app.users ON DELETE CASCADE,
    role       app.member_role NOT NULL DEFAULT 'staff',
    joined_at  timestamptz     NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, user_id)
);
COMMENT ON TABLE app.org_members IS 'Which users work for which organizer, and in what role';
-- Every organization keeps exactly one owner.
CREATE UNIQUE INDEX org_members_one_owner ON app.org_members (org_id) WHERE role = 'owner';
