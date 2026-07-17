-- 006 Business operations. Applications call these functions instead of writing tables directly,
-- so every rule (inventory, sales windows, promo limits, refunds, door checks) lives in one place.
--
-- Custom SQLSTATEs (class EV) let the application map errors to messages:
--   EV001 sold out            EV002 not on sale          EV003 invalid promo code
--   EV004 per-order limit     EV005 event not available  EV006 refund not allowed
--   EV007 bad request

CREATE FUNCTION app.tickets_held(p_ticket_type_id bigint, p_except_user bigint DEFAULT NULL)
RETURNS integer LANGUAGE sql STABLE AS $$
    -- Seats reserved for people holding an unexpired waitlist offer.
    SELECT coalesce(sum(quantity), 0)::integer
      FROM app.waitlist
     WHERE ticket_type_id = p_ticket_type_id
       AND status = 'offered' AND offer_expires_at > now()
       AND user_id IS DISTINCT FROM p_except_user
$$;
COMMENT ON FUNCTION app.tickets_held IS 'Seats held for open waitlist offers (optionally ignoring one user''s own offer)';

-- ---------------------------------------------------------------------------
-- purchase_tickets: the checkout. Safe under heavy concurrency.
--   * ticket_type rows are locked FOR UPDATE in id order, so two buyers of the same tiers
--     queue instead of overselling, and can't deadlock each other;
--   * the CHECK (quantity_sold <= quantity_total) is the last line of defense.
-- ---------------------------------------------------------------------------
CREATE FUNCTION app.purchase_tickets(
    p_user_id    bigint,
    p_items      jsonb,                       -- [{"ticket_type_id": 1, "quantity": 2}, ...]
    p_promo_code text               DEFAULT NULL,
    p_method     app.payment_method DEFAULT 'card'
) RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE
    v_user      app.users%ROWTYPE;
    v_event     app.events%ROWTYPE;
    v_promo     app.promo_codes%ROWTYPE;
    v_order_id  bigint;
    v_item_id   bigint;
    v_subtotal  numeric(10,2) := 0;
    v_discount  numeric(10,2) := 0;
    v_requested integer;
    v_found     integer := 0;
    v_available integer;
    tt_ids      bigint[]  := '{}';
    qtys        integer[] := '{}';
    prices      numeric[] := '{}';
    r           record;
BEGIN
    SELECT * INTO v_user FROM app.users WHERE user_id = p_user_id AND is_active;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'user % not found or inactive', p_user_id USING ERRCODE = 'EV007';
    END IF;
    IF jsonb_typeof(p_items) IS DISTINCT FROM 'array' OR jsonb_array_length(p_items) = 0 THEN
        RAISE EXCEPTION 'items must be a non-empty JSON array' USING ERRCODE = 'EV007';
    END IF;

    SELECT count(DISTINCT (x ->> 'ticket_type_id')::bigint) INTO v_requested FROM jsonb_array_elements(p_items) x;

    FOR r IN
        SELECT tt.*, i.qty
          FROM (SELECT (x ->> 'ticket_type_id')::bigint AS ticket_type_id, sum((x ->> 'quantity')::integer) AS qty
                  FROM jsonb_array_elements(p_items) x GROUP BY 1) i
          JOIN app.ticket_types tt USING (ticket_type_id)
         ORDER BY tt.ticket_type_id
           FOR UPDATE OF tt
    LOOP
        v_found := v_found + 1;
        IF v_event.event_id IS NULL THEN
            SELECT * INTO v_event FROM app.events WHERE event_id = r.event_id;
            IF v_event.status <> 'published' OR v_event.starts_at <= now() THEN
                RAISE EXCEPTION 'event "%" is not open for booking', v_event.title USING ERRCODE = 'EV005';
            END IF;
        ELSIF r.event_id <> v_event.event_id THEN
            RAISE EXCEPTION 'one order can only contain tickets for one event' USING ERRCODE = 'EV007';
        END IF;

        IF r.qty IS NULL OR r.qty < 1 THEN
            RAISE EXCEPTION 'quantity must be at least 1' USING ERRCODE = 'EV007';
        END IF;
        IF now() < r.sales_start OR now() >= r.sales_end THEN
            RAISE EXCEPTION '"%" is not on sale right now', r.name USING ERRCODE = 'EV002';
        END IF;
        IF r.qty > r.max_per_order THEN
            RAISE EXCEPTION 'at most % "%" tickets per order', r.max_per_order, r.name USING ERRCODE = 'EV004';
        END IF;

        v_available := r.quantity_total - r.quantity_sold - app.tickets_held(r.ticket_type_id, p_user_id);
        IF r.qty > v_available THEN
            RAISE EXCEPTION '"%" sold out: % requested, % available', r.name, r.qty, greatest(v_available, 0)
                USING ERRCODE = 'EV001';
        END IF;

        tt_ids     := tt_ids || r.ticket_type_id;
        qtys       := qtys   || r.qty;
        prices     := prices || r.price;
        v_subtotal := v_subtotal + r.qty * r.price;
    END LOOP;

    IF v_found <> v_requested THEN
        RAISE EXCEPTION 'unknown ticket type in order' USING ERRCODE = 'EV007';
    END IF;

    IF p_promo_code IS NOT NULL THEN
        SELECT * INTO v_promo FROM app.promo_codes
         WHERE event_id = v_event.event_id AND code = p_promo_code::citext   -- text = citext would compare case-sensitively
           FOR UPDATE;                                 -- serializes the last use of a limited code
        IF NOT FOUND OR now() NOT BETWEEN v_promo.valid_from AND v_promo.valid_until
           OR (v_promo.max_uses IS NOT NULL AND v_promo.times_used >= v_promo.max_uses) THEN
            RAISE EXCEPTION 'promo code "%" is not valid', p_promo_code USING ERRCODE = 'EV003';
        END IF;
        v_discount := CASE v_promo.discount_type
                          WHEN 'percent' THEN round(v_subtotal * v_promo.discount_value / 100, 2)
                          ELSE least(v_promo.discount_value, v_subtotal) END;
        UPDATE app.promo_codes SET times_used = times_used + 1 WHERE promo_id = v_promo.promo_id;
    END IF;

    INSERT INTO app.orders (user_id, event_id, promo_id, status, subtotal, discount, total, paid_at)
    VALUES (p_user_id, v_event.event_id, v_promo.promo_id, 'paid', v_subtotal, v_discount, v_subtotal - v_discount, now())
    RETURNING order_id INTO v_order_id;

    FOR i IN 1 .. array_length(tt_ids, 1) LOOP
        INSERT INTO app.order_items (order_id, ticket_type_id, quantity, unit_price)
        VALUES (v_order_id, tt_ids[i], qtys[i], prices[i])
        RETURNING order_item_id INTO v_item_id;

        INSERT INTO app.tickets (order_item_id, event_id, attendee_name, attendee_email)
        SELECT v_item_id, v_event.event_id, v_user.full_name, v_user.email
          FROM generate_series(1, qtys[i]);

        UPDATE app.ticket_types SET quantity_sold = quantity_sold + qtys[i] WHERE ticket_type_id = tt_ids[i];

        UPDATE app.waitlist SET status = 'converted'
         WHERE ticket_type_id = tt_ids[i] AND user_id = p_user_id AND status IN ('waiting', 'offered');
    END LOOP;

    INSERT INTO app.payments (order_id, amount, method, status, provider_ref)
    VALUES (v_order_id, v_subtotal - v_discount, p_method, 'captured', 'pay_' || replace(gen_random_uuid()::text, '-', ''));

    RETURN v_order_id;
END $$;
COMMENT ON FUNCTION app.purchase_tickets IS 'Checkout: validates sales window, limits, inventory and promo code, then issues tickets atomically';

-- ---------------------------------------------------------------------------
-- offer_waitlist: when seats free up, offer them to the queue in arrival order (24 h to buy).
-- ---------------------------------------------------------------------------
CREATE FUNCTION app.offer_waitlist(p_ticket_type_id bigint, p_offer_hours integer DEFAULT 24)
RETURNS integer LANGUAGE plpgsql AS $$
DECLARE
    v_free   integer;
    v_offers integer := 0;
    w        record;
BEGIN
    SELECT quantity_total - quantity_sold - app.tickets_held(ticket_type_id) INTO v_free
      FROM app.ticket_types WHERE ticket_type_id = p_ticket_type_id FOR UPDATE;

    FOR w IN
        SELECT waitlist_id, quantity FROM app.waitlist
         WHERE ticket_type_id = p_ticket_type_id AND status = 'waiting'
         ORDER BY joined_at, waitlist_id
           FOR UPDATE SKIP LOCKED
    LOOP
        EXIT WHEN v_free <= 0;
        CONTINUE WHEN w.quantity > v_free;               -- a smaller request further back may still fit
        UPDATE app.waitlist
           SET status = 'offered', offered_at = now(), offer_expires_at = now() + make_interval(hours => p_offer_hours)
         WHERE waitlist_id = w.waitlist_id;
        v_free   := v_free - w.quantity;
        v_offers := v_offers + 1;
    END LOOP;
    RETURN v_offers;
END $$;
COMMENT ON FUNCTION app.offer_waitlist IS 'Offers freed seats to waiting people in arrival order; returns the number of offers made';

CREATE FUNCTION app.join_waitlist(p_user_id bigint, p_ticket_type_id bigint, p_quantity integer DEFAULT 1)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE
    v_free integer;
    v_id   bigint;
BEGIN
    SELECT quantity_total - quantity_sold - app.tickets_held(ticket_type_id) INTO v_free
      FROM app.ticket_types WHERE ticket_type_id = p_ticket_type_id;
    IF v_free IS NULL THEN
        RAISE EXCEPTION 'unknown ticket type %', p_ticket_type_id USING ERRCODE = 'EV007';
    END IF;
    IF v_free >= p_quantity THEN
        RAISE EXCEPTION 'tickets are still available; buy them instead of joining the waitlist' USING ERRCODE = 'EV007';
    END IF;
    INSERT INTO app.waitlist (ticket_type_id, user_id, quantity)
    VALUES (p_ticket_type_id, p_user_id, p_quantity)
    RETURNING waitlist_id INTO v_id;
    RETURN v_id;
END $$;

COMMENT ON FUNCTION app.join_waitlist IS 'Joins the queue for a sold-out ticket type; refused while seats are still available';

-- Offers that ran out go back into circulation (run every few minutes by a scheduler).
CREATE FUNCTION app.expire_waitlist_offers() RETURNS integer LANGUAGE plpgsql AS $$
DECLARE
    v_expired integer;
    tt        bigint;
BEGIN
    WITH expired AS (
        UPDATE app.waitlist SET status = 'expired'
         WHERE status = 'offered' AND offer_expires_at <= now()
        RETURNING ticket_type_id
    )
    SELECT count(*) INTO v_expired FROM expired;

    FOR tt IN SELECT DISTINCT ticket_type_id FROM app.waitlist WHERE status = 'waiting' ORDER BY 1 LOOP
        PERFORM app.offer_waitlist(tt);
    END LOOP;
    RETURN v_expired;
END $$;

COMMENT ON FUNCTION app.expire_waitlist_offers IS 'Expires unanswered offers and passes the seats to the next people waiting; returns offers expired';

-- ---------------------------------------------------------------------------
-- refund_order: full refund before the event starts. Returns seats to inventory
-- and immediately offers them to the waitlist.
-- ---------------------------------------------------------------------------
CREATE FUNCTION app.refund_order(p_order_id bigint, p_reason text, p_processed_by bigint DEFAULT NULL)
RETURNS numeric LANGUAGE plpgsql AS $$
DECLARE
    v_order   app.orders%ROWTYPE;
    v_payment app.payments%ROWTYPE;
    v_starts  timestamptz;
    li        record;
BEGIN
    SELECT * INTO v_order FROM app.orders WHERE order_id = p_order_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'order % not found', p_order_id USING ERRCODE = 'EV007';
    END IF;
    IF v_order.status <> 'paid' THEN
        RAISE EXCEPTION 'order % is %, only paid orders can be refunded', p_order_id, v_order.status USING ERRCODE = 'EV006';
    END IF;
    SELECT starts_at INTO v_starts FROM app.events WHERE event_id = v_order.event_id;
    IF v_starts <= now() THEN
        RAISE EXCEPTION 'refunds close when the event starts' USING ERRCODE = 'EV006';
    END IF;
    IF EXISTS (SELECT 1 FROM app.tickets t JOIN app.order_items oi USING (order_item_id)
                WHERE oi.order_id = p_order_id AND t.status = 'checked_in') THEN
        RAISE EXCEPTION 'order % has tickets that were already used', p_order_id USING ERRCODE = 'EV006';
    END IF;

    SELECT * INTO v_payment FROM app.payments
     WHERE order_id = p_order_id AND status = 'captured' ORDER BY payment_id LIMIT 1;
    IF v_order.total > 0 THEN
        INSERT INTO app.refunds (order_id, payment_id, amount, reason, processed_by)
        VALUES (p_order_id, v_payment.payment_id, v_order.total, p_reason, p_processed_by);
        UPDATE app.payments SET status = 'refunded' WHERE payment_id = v_payment.payment_id;
    END IF;

    UPDATE app.orders SET status = 'refunded' WHERE order_id = p_order_id;
    UPDATE app.tickets t SET status = 'cancelled'
      FROM app.order_items oi WHERE oi.order_item_id = t.order_item_id AND oi.order_id = p_order_id;

    FOR li IN SELECT ticket_type_id, quantity FROM app.order_items WHERE order_id = p_order_id ORDER BY ticket_type_id LOOP
        UPDATE app.ticket_types SET quantity_sold = quantity_sold - li.quantity WHERE ticket_type_id = li.ticket_type_id;
        PERFORM app.offer_waitlist(li.ticket_type_id);
    END LOOP;

    RETURN v_order.total;
END $$;
COMMENT ON FUNCTION app.refund_order IS 'Full refund before the event: money back, tickets cancelled, seats returned and offered to the waitlist';

-- ---------------------------------------------------------------------------
-- check_in_ticket: the door scanner. Every scan is logged; a ticket can only be used once,
-- even if two gates scan the same code at the same moment.
-- ---------------------------------------------------------------------------
CREATE FUNCTION app.check_in_ticket(p_code uuid, p_event_id bigint, p_gate text, p_scanned_by bigint DEFAULT NULL)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE
    v_ticket app.tickets%ROWTYPE;
    v_starts timestamptz;
    v_result text;
BEGIN
    SELECT * INTO v_ticket FROM app.tickets WHERE code = p_code FOR UPDATE;
    IF NOT FOUND THEN
        v_result := 'not_found';
    ELSIF v_ticket.event_id <> p_event_id THEN
        v_result := 'wrong_event';
    ELSIF v_ticket.status = 'cancelled' THEN
        v_result := 'cancelled';
    ELSIF v_ticket.status = 'checked_in' THEN
        v_result := 'already_checked_in';
    ELSE
        SELECT starts_at INTO v_starts FROM app.events WHERE event_id = p_event_id;
        IF now() < v_starts - interval '2 hours' THEN
            v_result := 'too_early';
        ELSE
            INSERT INTO app.check_ins (ticket_id, event_id, gate, scanned_by)
            VALUES (v_ticket.ticket_id, v_ticket.event_id, p_gate, p_scanned_by);
            UPDATE app.tickets SET status = 'checked_in' WHERE ticket_id = v_ticket.ticket_id;
            v_result := 'admitted';
        END IF;
    END IF;

    INSERT INTO app.scan_attempts (code, gate, result) VALUES (p_code, p_gate, v_result);
    RETURN v_result;
END $$;
COMMENT ON FUNCTION app.check_in_ticket IS 'Door scan: returns admitted / already_checked_in / cancelled / not_found / wrong_event / too_early';

-- Nightly housekeeping: close events that have ended. A procedure so it can commit in batches.
CREATE PROCEDURE app.complete_finished_events(p_batch integer DEFAULT 500)
LANGUAGE plpgsql AS $$
DECLARE
    n integer;
BEGIN
    LOOP
        UPDATE app.events SET status = 'completed'
         WHERE event_id IN (SELECT event_id FROM app.events
                             WHERE status = 'published' AND ends_at < now() LIMIT p_batch);
        GET DIAGNOSTICS n = ROW_COUNT;
        COMMIT;
        EXIT WHEN n < p_batch;
    END LOOP;
END $$;
COMMENT ON PROCEDURE app.complete_finished_events IS 'Nightly job: marks published events that have ended as completed, committing in batches';
