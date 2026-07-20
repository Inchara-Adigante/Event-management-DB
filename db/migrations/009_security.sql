-- 009 Security: least-privilege roles and row-level security.
--
--   ems_app        the web/API backend: runs the business functions, reads and writes app tables
--   ems_organizer  an organizer's staff: sees ONLY their own organization's events, orders and tickets
--   ems_analyst    BI tools: read-only access to the report schema
--
-- Roles are cluster-wide, so create them only if they don't exist yet.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ems_app')       THEN CREATE ROLE ems_app NOLOGIN;       END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ems_organizer') THEN CREATE ROLE ems_organizer NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ems_analyst')   THEN CREATE ROLE ems_analyst NOLOGIN;   END IF;
END $$;

REVOKE ALL ON SCHEMA app, report, audit FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA app FROM PUBLIC;

-- Backend
GRANT USAGE ON SCHEMA app, report TO ems_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA app TO ems_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA app TO ems_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app TO ems_app;
GRANT INSERT ON audit.change_log TO ems_app;
GRANT SELECT ON ALL TABLES IN SCHEMA report TO ems_app;

-- Organizer staff
GRANT USAGE ON SCHEMA app TO ems_organizer;
GRANT SELECT ON app.events, app.ticket_types, app.orders, app.order_items, app.tickets, app.check_ins,
                app.sessions, app.venues, app.rooms, app.event_categories TO ems_organizer;
GRANT UPDATE (title, description, status) ON app.events TO ems_organizer;
GRANT EXECUTE ON FUNCTION app.check_in_ticket(uuid, bigint, text, bigint), app.tickets_held(bigint, bigint) TO ems_organizer;
GRANT INSERT ON app.check_ins, app.scan_attempts TO ems_organizer;
GRANT UPDATE (status) ON app.tickets TO ems_organizer;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA app TO ems_organizer;

-- Analysts
GRANT USAGE ON SCHEMA report TO ems_analyst;
GRANT SELECT ON ALL TABLES IN SCHEMA report TO ems_analyst;

-- ---------------------------------------------------------------------------
-- Row-level security. The backend sets the organizer for the session:
--     SET app.org_id = '42';
-- and every query an ems_organizer runs is filtered to that organization, even SELECT *.
-- ---------------------------------------------------------------------------
CREATE FUNCTION app.current_org() RETURNS bigint LANGUAGE sql STABLE AS $$
    SELECT nullif(current_setting('app.org_id', true), '')::bigint
$$;
COMMENT ON FUNCTION app.current_org IS 'Organization of the current session (SET app.org_id), used by row-level security policies';
GRANT EXECUTE ON FUNCTION app.current_org() TO ems_organizer, ems_app;

ALTER TABLE app.events       ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.ticket_types ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.orders       ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.order_items  ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.tickets      ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.check_ins    ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.sessions     ENABLE ROW LEVEL SECURITY;

-- The backend sees everything.
CREATE POLICY app_all ON app.events       TO ems_app USING (true) WITH CHECK (true);
CREATE POLICY app_all ON app.ticket_types TO ems_app USING (true) WITH CHECK (true);
CREATE POLICY app_all ON app.orders       TO ems_app USING (true) WITH CHECK (true);
CREATE POLICY app_all ON app.order_items  TO ems_app USING (true) WITH CHECK (true);
CREATE POLICY app_all ON app.tickets      TO ems_app USING (true) WITH CHECK (true);
CREATE POLICY app_all ON app.check_ins    TO ems_app USING (true) WITH CHECK (true);
CREATE POLICY app_all ON app.sessions     TO ems_app USING (true) WITH CHECK (true);

-- Organizers see their own organization only.
CREATE POLICY own_org ON app.events TO ems_organizer
    USING (org_id = app.current_org()) WITH CHECK (org_id = app.current_org());
CREATE POLICY own_org ON app.ticket_types TO ems_organizer
    USING (event_id IN (SELECT event_id FROM app.events WHERE org_id = app.current_org()));
CREATE POLICY own_org ON app.sessions TO ems_organizer
    USING (event_id IN (SELECT event_id FROM app.events WHERE org_id = app.current_org()));
CREATE POLICY own_org ON app.orders TO ems_organizer
    USING (event_id IN (SELECT event_id FROM app.events WHERE org_id = app.current_org()));
CREATE POLICY own_org ON app.order_items TO ems_organizer
    USING (order_id IN (SELECT order_id FROM app.orders));          -- orders are already filtered
CREATE POLICY own_org ON app.tickets TO ems_organizer
    USING (event_id IN (SELECT event_id FROM app.events WHERE org_id = app.current_org()));
CREATE POLICY own_org ON app.check_ins TO ems_organizer
    USING (event_id IN (SELECT event_id FROM app.events WHERE org_id = app.current_org()))
    WITH CHECK (event_id IN (SELECT event_id FROM app.events WHERE org_id = app.current_org()));
