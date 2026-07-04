-- 003 Ticketing: ticket types with inventory, promo codes, orders, payments, refunds and tickets.

CREATE TABLE app.ticket_types (
    ticket_type_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id        bigint        NOT NULL REFERENCES app.events ON DELETE CASCADE,
    name            text          NOT NULL,
    price           numeric(10,2) NOT NULL CHECK (price >= 0),
    currency        char(3)       NOT NULL DEFAULT 'USD' CHECK (currency ~ '^[A-Z]{3}$'),
    quantity_total  integer       NOT NULL CHECK (quantity_total > 0),
    quantity_sold   integer       NOT NULL DEFAULT 0,
    sales_start     timestamptz   NOT NULL,
    sales_end       timestamptz   NOT NULL,
    max_per_order   smallint      NOT NULL DEFAULT 10 CHECK (max_per_order BETWEEN 1 AND 50),
    UNIQUE (event_id, name),
    CHECK (sales_end > sales_start),
    -- The inventory invariant: never oversold, never negative.
    CONSTRAINT ticket_types_inventory CHECK (quantity_sold BETWEEN 0 AND quantity_total)
);
COMMENT ON TABLE  app.ticket_types IS 'Ticket tiers of an event (Early bird, General, VIP) with their own inventory';
COMMENT ON COLUMN app.ticket_types.quantity_sold IS 'Inventory counter maintained only by purchase_tickets and refund_order';

CREATE TABLE app.promo_codes (
    promo_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id        bigint        NOT NULL REFERENCES app.events ON DELETE CASCADE,
    code            citext        NOT NULL CHECK (code ~ '^[A-Za-z0-9_-]{3,32}$'),
    discount_type   text          NOT NULL CHECK (discount_type IN ('percent', 'amount')),
    discount_value  numeric(10,2) NOT NULL CHECK (discount_value > 0),
    max_uses        integer       CHECK (max_uses > 0),
    times_used      integer       NOT NULL DEFAULT 0 CHECK (times_used >= 0),
    valid_from      timestamptz   NOT NULL,
    valid_until     timestamptz   NOT NULL,
    UNIQUE (event_id, code),
    CHECK (valid_until > valid_from),
    CHECK (discount_type <> 'percent' OR discount_value <= 100),
    CHECK (max_uses IS NULL OR times_used <= max_uses)
);
COMMENT ON TABLE app.promo_codes IS 'Discount codes, limited per event, by date window and by number of uses';

CREATE TABLE app.orders (
    order_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     bigint           NOT NULL REFERENCES app.users,
    event_id    bigint           NOT NULL REFERENCES app.events,
    promo_id    bigint           REFERENCES app.promo_codes,
    status      app.order_status NOT NULL DEFAULT 'pending',
    subtotal    numeric(10,2)    NOT NULL CHECK (subtotal >= 0),
    discount    numeric(10,2)    NOT NULL DEFAULT 0 CHECK (discount >= 0),
    total       numeric(10,2)    NOT NULL,
    created_at  timestamptz      NOT NULL DEFAULT now(),
    paid_at     timestamptz,
    updated_at  timestamptz      NOT NULL DEFAULT now(),
    CHECK (discount <= subtotal),
    CHECK (total = subtotal - discount),
    CHECK ((status IN ('pending', 'cancelled')) = (paid_at IS NULL))
);
COMMENT ON TABLE  app.orders IS 'One checkout: a buyer, one event, one or more ticket types';
COMMENT ON COLUMN app.orders.total IS 'Always subtotal - discount (CHECK constraint)';
CREATE TRIGGER orders_updated_at BEFORE UPDATE ON app.orders
    FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();

CREATE TABLE app.order_items (
    order_item_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id        bigint        NOT NULL REFERENCES app.orders ON DELETE CASCADE,
    ticket_type_id  bigint        NOT NULL REFERENCES app.ticket_types,
    quantity        integer       NOT NULL CHECK (quantity > 0),
    unit_price      numeric(10,2) NOT NULL CHECK (unit_price >= 0),
    line_total      numeric(10,2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
    UNIQUE (order_id, ticket_type_id)
);
COMMENT ON TABLE  app.order_items IS 'Lines of an order; unit_price is frozen at purchase time';
