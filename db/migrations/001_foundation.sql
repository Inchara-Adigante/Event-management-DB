-- 001 Foundation: extensions, schemas, enum types and shared helpers.

CREATE EXTENSION IF NOT EXISTS citext;      -- case-insensitive emails and promo codes
CREATE EXTENSION IF NOT EXISTS btree_gist;  -- equality + range in one exclusion constraint
CREATE EXTENSION IF NOT EXISTS pgcrypto;    -- gen_random_uuid() for ticket codes
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- fuzzy search on names

CREATE SCHEMA IF NOT EXISTS app;     -- tables and business logic
CREATE SCHEMA IF NOT EXISTS report;  -- read-only views for analysts and dashboards
CREATE SCHEMA IF NOT EXISTS audit;   -- change history

COMMENT ON SCHEMA app    IS 'Operational tables and business logic of the event platform';
COMMENT ON SCHEMA report IS 'Read-only reporting views';
COMMENT ON SCHEMA audit  IS 'Row-level change history for sensitive tables';

CREATE TYPE app.event_status   AS ENUM ('draft', 'published', 'cancelled', 'completed');
CREATE TYPE app.order_status   AS ENUM ('pending', 'paid', 'cancelled', 'refunded', 'partially_refunded');
CREATE TYPE app.payment_status AS ENUM ('authorized', 'captured', 'failed', 'refunded');
CREATE TYPE app.payment_method AS ENUM ('card', 'paypal', 'apple_pay', 'bank_transfer');
CREATE TYPE app.ticket_status  AS ENUM ('valid', 'checked_in', 'cancelled');
CREATE TYPE app.member_role    AS ENUM ('owner', 'admin', 'staff');
CREATE TYPE app.waitlist_status AS ENUM ('waiting', 'offered', 'converted', 'expired', 'withdrawn');

-- Keeps updated_at honest without relying on the application.
CREATE FUNCTION app.set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END $$;

-- Used by a CHECK constraint so venues can only store real IANA time zones.
CREATE FUNCTION app.is_valid_timezone(tz text) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT EXISTS (SELECT 1 FROM pg_timezone_names WHERE name = tz)
$$;
COMMENT ON FUNCTION app.is_valid_timezone IS 'True for IANA time zone names known to the server (used by venues.timezone)';
