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
