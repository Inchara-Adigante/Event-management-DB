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

-- Tickets and check-ins must point at the same event as their order.
CREATE FUNCTION app.check_ticket_event() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    expected bigint;
BEGIN
    IF TG_TABLE_NAME = 'tickets' THEN
        SELECT o.event_id INTO expected
          FROM app.order_items oi JOIN app.orders o USING (order_id)
         WHERE oi.order_item_id = NEW.order_item_id;
    ELSE
        SELECT event_id INTO expected FROM app.tickets WHERE ticket_id = NEW.ticket_id;
    END IF;
    IF NEW.event_id IS DISTINCT FROM expected THEN
        RAISE EXCEPTION '%: event_id % does not match the order''s event %', TG_TABLE_NAME, NEW.event_id, expected
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER tickets_event_check BEFORE INSERT OR UPDATE OF event_id, order_item_id ON app.tickets
    FOR EACH ROW EXECUTE FUNCTION app.check_ticket_event();
CREATE TRIGGER check_ins_event_check BEFORE INSERT ON app.check_ins
    FOR EACH ROW EXECUTE FUNCTION app.check_ticket_event();

-- Refunds can never add up to more than was captured.
CREATE FUNCTION app.check_refund() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    captured numeric;
    refunded numeric;
BEGIN
    SELECT amount INTO captured FROM app.payments
     WHERE payment_id = NEW.payment_id AND order_id = NEW.order_id AND status IN ('captured', 'refunded')
       FOR UPDATE;                                   -- serializes concurrent refunds of one payment
    IF captured IS NULL THEN
        RAISE EXCEPTION 'payment % is not a captured payment of order %', NEW.payment_id, NEW.order_id
            USING ERRCODE = 'check_violation';
    END IF;
    SELECT coalesce(sum(amount), 0) INTO refunded FROM app.refunds WHERE payment_id = NEW.payment_id;
    IF refunded + NEW.amount > captured THEN
        RAISE EXCEPTION 'refunds would total %, more than the % captured', refunded + NEW.amount, captured
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER refunds_check BEFORE INSERT ON app.refunds
    FOR EACH ROW EXECUTE FUNCTION app.check_refund();

-- Only people who were actually there can rate an event.
CREATE FUNCTION app.check_feedback() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM app.orders o
          JOIN app.order_items oi USING (order_id)
          JOIN app.tickets t USING (order_item_id)
         WHERE o.user_id = NEW.user_id AND o.event_id = NEW.event_id AND t.status = 'checked_in'
    ) THEN
        RAISE EXCEPTION 'user % did not attend event %', NEW.user_id, NEW.event_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER feedback_check BEFORE INSERT ON app.feedback
    FOR EACH ROW EXECUTE FUNCTION app.check_feedback();
