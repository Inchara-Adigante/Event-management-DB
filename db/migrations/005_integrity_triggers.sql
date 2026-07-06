-- 005 Integrity rules that span more than one row or table, enforced with triggers.
-- Each raises a clear message with a SQLSTATE so applications can show it to users.

-- Events: capacity fits the venue, and status only moves forward.
CREATE FUNCTION app.check_event() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    venue_cap integer;
BEGIN
    SELECT capacity INTO venue_cap FROM app.venues WHERE venue_id = NEW.venue_id;
    IF NEW.capacity > venue_cap THEN
        RAISE EXCEPTION 'event capacity % exceeds venue capacity %', NEW.capacity, venue_cap
            USING ERRCODE = 'check_violation';
    END IF;

    IF TG_OP = 'UPDATE' AND NEW.status IS DISTINCT FROM OLD.status THEN
        IF NOT (OLD.status, NEW.status) IN (('draft', 'published'), ('draft', 'cancelled'),
                                             ('published', 'cancelled'), ('published', 'completed')) THEN
            RAISE EXCEPTION 'event status cannot change from % to %', OLD.status, NEW.status
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.status = 'published' AND NEW.published_at IS NULL THEN
            NEW.published_at := now();
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER events_check BEFORE INSERT OR UPDATE ON app.events
    FOR EACH ROW EXECUTE FUNCTION app.check_event();

-- Sessions: inside the event's time window, in a room of the event's venue.
CREATE FUNCTION app.check_session() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    e app.events%ROWTYPE;
BEGIN
    SELECT * INTO e FROM app.events WHERE event_id = NEW.event_id;
    IF NEW.starts_at < e.starts_at OR NEW.ends_at > e.ends_at THEN
        RAISE EXCEPTION 'session "%" is outside the event time window', NEW.title
            USING ERRCODE = 'check_violation';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM app.rooms WHERE room_id = NEW.room_id AND venue_id = e.venue_id) THEN
        RAISE EXCEPTION 'room % is not in the venue of event %', NEW.room_id, NEW.event_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER sessions_check BEFORE INSERT OR UPDATE ON app.sessions
    FOR EACH ROW EXECUTE FUNCTION app.check_session();

-- Ticket types: all tiers together fit the event capacity, and sales close by the time the event ends.
CREATE FUNCTION app.check_ticket_type() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    e app.events%ROWTYPE;
    allocated integer;
BEGIN
    SELECT * INTO e FROM app.events WHERE event_id = NEW.event_id FOR UPDATE;   -- serializes concurrent tier changes
    SELECT coalesce(sum(quantity_total), 0) INTO allocated
      FROM app.ticket_types
     WHERE event_id = NEW.event_id AND ticket_type_id IS DISTINCT FROM NEW.ticket_type_id;
    IF allocated + NEW.quantity_total > e.capacity THEN
        RAISE EXCEPTION 'ticket types of event % would total % seats, capacity is %',
            NEW.event_id, allocated + NEW.quantity_total, e.capacity USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.sales_end > e.ends_at THEN
        RAISE EXCEPTION 'ticket sales must end by the end of the event' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER ticket_types_check BEFORE INSERT OR UPDATE OF quantity_total, sales_end, event_id ON app.ticket_types
    FOR EACH ROW EXECUTE FUNCTION app.check_ticket_type();
