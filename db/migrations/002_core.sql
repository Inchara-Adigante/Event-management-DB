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

CREATE TABLE app.venues (
    venue_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name         text    NOT NULL,
    address_line text    NOT NULL,
    city         text    NOT NULL,
    state        text,
    postal_code  text,
    country      char(2) NOT NULL DEFAULT 'US' CHECK (country ~ '^[A-Z]{2}$'),
    timezone     text    NOT NULL DEFAULT 'America/New_York' CHECK (app.is_valid_timezone(timezone)),
    capacity     integer NOT NULL CHECK (capacity > 0),
    UNIQUE (name, city)
);
COMMENT ON TABLE  app.venues IS 'Physical locations; capacity is the fire-code limit for the whole building';
COMMENT ON COLUMN app.venues.timezone IS 'IANA zone used to show local times; all timestamps are stored in UTC';

CREATE TABLE app.rooms (
    room_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    venue_id  bigint  NOT NULL REFERENCES app.venues ON DELETE CASCADE,
    name      text    NOT NULL,
    capacity  integer NOT NULL CHECK (capacity > 0),
    UNIQUE (venue_id, name)
);
COMMENT ON TABLE app.rooms IS 'Bookable spaces inside a venue (halls, stages, workshop rooms)';

CREATE TABLE app.event_categories (
    category_id  integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name         text    NOT NULL UNIQUE,
    parent_id    integer REFERENCES app.event_categories,
    CHECK (parent_id IS DISTINCT FROM category_id)
);
COMMENT ON TABLE app.event_categories IS 'Category tree, e.g. Technology > Data > Databases (queried recursively)';

CREATE TABLE app.events (
    event_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    org_id        bigint           NOT NULL REFERENCES app.organizations,
    venue_id      bigint           NOT NULL REFERENCES app.venues,
    category_id   integer          NOT NULL REFERENCES app.event_categories,
    title         text             NOT NULL,
    slug          text             NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    description   text             NOT NULL DEFAULT '',
    status        app.event_status NOT NULL DEFAULT 'draft',
    starts_at     timestamptz      NOT NULL,
    ends_at       timestamptz      NOT NULL,
    capacity      integer          NOT NULL CHECK (capacity > 0),
    published_at  timestamptz,
    created_at    timestamptz      NOT NULL DEFAULT now(),
    updated_at    timestamptz      NOT NULL DEFAULT now(),
    search        tsvector GENERATED ALWAYS AS (
                      setweight(to_tsvector('english', title), 'A') ||
                      setweight(to_tsvector('english', description), 'B')) STORED,
    CHECK (ends_at > starts_at),
    CHECK (ends_at - starts_at <= interval '14 days'),
    CHECK (status = 'draft' OR published_at IS NOT NULL)
);
COMMENT ON TABLE  app.events IS 'An event hosted by one organization at one venue';
COMMENT ON COLUMN app.events.capacity IS 'Maximum attendees; may not exceed the venue capacity (trigger)';
COMMENT ON COLUMN app.events.search IS 'Full-text search document: title weighted above description';
CREATE TRIGGER events_updated_at BEFORE UPDATE ON app.events
    FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();

CREATE TABLE app.speakers (
    speaker_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    full_name   text   NOT NULL,
    email       citext UNIQUE,
    company     text,
    bio         text   NOT NULL DEFAULT ''
);
COMMENT ON TABLE app.speakers IS 'People who present sessions; a speaker does not need a user account';

CREATE TABLE app.sessions (
    session_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id    bigint      NOT NULL REFERENCES app.events ON DELETE CASCADE,
    room_id     bigint      NOT NULL REFERENCES app.rooms,
    title       text        NOT NULL,
    track       text,
    starts_at   timestamptz NOT NULL,
    ends_at     timestamptz NOT NULL,
    during      tstzrange GENERATED ALWAYS AS (tstzrange(starts_at, ends_at, '[)')) STORED,
    CHECK (ends_at > starts_at),
    -- A room can never be double-booked, across all events.
    CONSTRAINT sessions_no_room_overlap EXCLUDE USING gist (room_id WITH =, during WITH &&)
);
COMMENT ON TABLE  app.sessions IS 'Agenda items of an event, each in one room';
COMMENT ON COLUMN app.sessions.during IS 'Half-open time range [start, end) used by the no-overlap constraint';

CREATE TABLE app.session_speakers (
    session_id  bigint NOT NULL REFERENCES app.sessions ON DELETE CASCADE,
    speaker_id  bigint NOT NULL REFERENCES app.speakers,
    role        text   NOT NULL DEFAULT 'speaker' CHECK (role IN ('speaker', 'moderator', 'panelist')),
    PRIMARY KEY (session_id, speaker_id)
);
COMMENT ON TABLE app.session_speakers IS 'Many-to-many: who presents which session';
