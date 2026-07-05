-- 004 Event-day operations: door check-ins, scan log, waitlist and feedback.

CREATE TABLE app.check_ins (
    check_in_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_id      bigint      NOT NULL UNIQUE REFERENCES app.tickets,   -- one entry per ticket, ever
    event_id       bigint      NOT NULL REFERENCES app.events,
    gate           text        NOT NULL,
    scanned_by     bigint      REFERENCES app.users,
    checked_in_at  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE app.check_ins IS 'Successful door scans; the UNIQUE ticket_id makes a second entry on the same ticket impossible';

CREATE TABLE app.scan_attempts (
    attempt_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code          uuid        NOT NULL,
    gate          text        NOT NULL,
    result        text        NOT NULL CHECK (result IN
                      ('admitted', 'already_checked_in', 'cancelled', 'not_found', 'wrong_event', 'too_early')),
    attempted_at  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE app.scan_attempts IS 'Every scan at the door, including rejected ones (fraud and queue analysis)';

CREATE TABLE app.waitlist (
    waitlist_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_type_id    bigint              NOT NULL REFERENCES app.ticket_types ON DELETE CASCADE,
    user_id           bigint              NOT NULL REFERENCES app.users,
    quantity          smallint            NOT NULL DEFAULT 1 CHECK (quantity BETWEEN 1 AND 10),
    status            app.waitlist_status NOT NULL DEFAULT 'waiting',
    joined_at         timestamptz         NOT NULL DEFAULT now(),
    offered_at        timestamptz,
    offer_expires_at  timestamptz,
    CHECK (status <> 'offered' OR (offered_at IS NOT NULL AND offer_expires_at > offered_at))
);
COMMENT ON TABLE app.waitlist IS 'Queue for sold-out ticket types; first come, first offered when tickets free up';
-- A person can only be in the active queue once per ticket type.
CREATE UNIQUE INDEX waitlist_one_active_entry ON app.waitlist (ticket_type_id, user_id)
    WHERE status IN ('waiting', 'offered');

CREATE TABLE app.feedback (
    feedback_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id     bigint      NOT NULL REFERENCES app.events,
    user_id      bigint      NOT NULL REFERENCES app.users,
    rating       smallint    NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment      text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (event_id, user_id)
);
COMMENT ON TABLE app.feedback IS 'Post-event ratings; only people who actually checked in may rate (trigger)';
