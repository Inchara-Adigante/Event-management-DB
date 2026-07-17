-- 007 Audit trail: who changed what, with before/after values, for money- and inventory-related tables.

CREATE TABLE audit.change_log (
    change_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    table_name  text        NOT NULL,
    operation   text        NOT NULL CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE')),
    row_id      bigint      NOT NULL,
    old_values  jsonb,
    new_values  jsonb,
    changed_by  text        NOT NULL DEFAULT current_user,
    app_user    text        DEFAULT current_setting('app.user_id', true),
    changed_at  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE  audit.change_log IS 'Append-only history of changes to events, ticket types, orders, refunds and promo codes';
COMMENT ON COLUMN audit.change_log.app_user IS 'Application user id, set per transaction with SET LOCAL app.user_id';
CREATE INDEX change_log_lookup ON audit.change_log (table_name, row_id, changed_at);

-- Generic trigger; TG_ARGV[0] names the primary-key column.
CREATE FUNCTION audit.log_change() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    full_old jsonb := CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) END;
    full_new jsonb := CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) END;
    old_j    jsonb := full_old;
    new_j    jsonb := full_new;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        -- Keep only the columns that actually changed.
        SELECT jsonb_object_agg(k, full_old -> k), jsonb_object_agg(k, full_new -> k)
          INTO old_j, new_j
          FROM jsonb_object_keys(full_new) k
         WHERE full_old -> k IS DISTINCT FROM full_new -> k AND k NOT IN ('updated_at', 'search');
        IF old_j IS NULL THEN
            RETURN NULL;                               -- no real change
        END IF;
    END IF;
    INSERT INTO audit.change_log (table_name, operation, row_id, old_values, new_values)
    VALUES (TG_TABLE_NAME, TG_OP, (coalesce(full_new, full_old) ->> TG_ARGV[0])::bigint, old_j, new_j);
    RETURN NULL;
END $$;

CREATE TRIGGER audit_events       AFTER INSERT OR UPDATE OR DELETE ON app.events
    FOR EACH ROW EXECUTE FUNCTION audit.log_change('event_id');
CREATE TRIGGER audit_ticket_types AFTER INSERT OR UPDATE OR DELETE ON app.ticket_types
    FOR EACH ROW EXECUTE FUNCTION audit.log_change('ticket_type_id');
CREATE TRIGGER audit_orders       AFTER UPDATE OR DELETE ON app.orders
    FOR EACH ROW EXECUTE FUNCTION audit.log_change('order_id');
CREATE TRIGGER audit_refunds      AFTER INSERT OR UPDATE OR DELETE ON app.refunds
    FOR EACH ROW EXECUTE FUNCTION audit.log_change('refund_id');
CREATE TRIGGER audit_promo_codes  AFTER INSERT OR UPDATE OR DELETE ON app.promo_codes
    FOR EACH ROW EXECUTE FUNCTION audit.log_change('promo_id');
