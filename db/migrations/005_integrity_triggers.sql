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
