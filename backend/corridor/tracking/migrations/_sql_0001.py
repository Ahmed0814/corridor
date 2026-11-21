"""Raw SQL for tracking 0001: the partitioned GPS history and its maintenance functions.

Kept in a separate module so the migration stays readable. MASTER_PROMPT §4.1, DECISIONS D-012, D-058.
"""

# Native monthly partitions by recorded_at. PostgreSQL requires unique constraints on a partitioned
# table to include the partition key, so the dedupe key is (tenant_id, device_id, event_id, recorded_at).
GPS_TABLE = """
CREATE TABLE gps_location_events (
    id              BIGINT GENERATED ALWAYS AS IDENTITY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id),
    event_id        UUID NOT NULL,
    device_id       UUID NOT NULL,
    session_id      UUID NOT NULL,
    trip_id         UUID NOT NULL,
    vehicle_id      UUID NOT NULL,
    driver_id       UUID NOT NULL,
    sequence_number BIGINT,
    point           geometry(Point, 4326) NOT NULL,
    accuracy_m      DOUBLE PRECISION,
    speed_mps       DOUBLE PRECISION,
    heading_deg     DOUBLE PRECISION,
    recorded_at     TIMESTAMPTZ NOT NULL,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    source          VARCHAR(16) NOT NULL,
    flags           INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (id, recorded_at),
    CONSTRAINT gps_dedupe UNIQUE (tenant_id, device_id, event_id, recorded_at)
) PARTITION BY RANGE (recorded_at);
CREATE TABLE gps_location_events_default PARTITION OF gps_location_events DEFAULT;
CREATE INDEX gps_events_recorded_brin ON gps_location_events USING BRIN (recorded_at);
CREATE INDEX gps_events_trip_idx ON gps_location_events (tenant_id, trip_id, recorded_at);
CREATE INDEX gps_events_vehicle_idx ON gps_location_events (tenant_id, vehicle_id, recorded_at);
CREATE INDEX gps_events_device_idx ON gps_location_events (tenant_id, device_id, event_id);
CREATE INDEX gps_events_point_gist ON gps_location_events USING GIST (point);

-- Isolation: the app role reads/writes only its tenant's rows through the parent table and may only
-- INSERT and SELECT (append-only, hard rule 5). No role has privileges on the partitions themselves,
-- so they cannot be queried around the policy.
ALTER TABLE gps_location_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE gps_location_events FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON gps_location_events TO corridor_app
    USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id());
GRANT SELECT, INSERT ON gps_location_events TO corridor_app;
CREATE POLICY maintenance_owner_read ON gps_location_events FOR SELECT TO corridor_owner USING (true);
"""

# Partition maintenance and retention run as corridor_relay through these SECURITY DEFINER functions
# only. Each validates its input; none accepts free-form SQL.
GPS_FUNCTIONS = r"""
CREATE FUNCTION gps_secure_partition(p_name text) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS
$fn$
BEGIN
    -- Defence in depth: partitions get the same forced policy as the parent, so even an accidental
    -- grant on a partition could not expose another tenant's rows.
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', p_name);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', p_name);
    EXECUTE format('CREATE POLICY tenant_isolation ON %I TO corridor_app USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())', p_name);
    -- The SECURITY DEFINER retention export runs as the owner; FORCE RLS would otherwise hide every
    -- row from it and an archive would silently be empty.
    EXECUTE format('CREATE POLICY maintenance_owner_read ON %I FOR SELECT TO corridor_owner USING (true)', p_name);
END
$fn$;
REVOKE ALL ON FUNCTION gps_secure_partition(text) FROM PUBLIC;
SELECT gps_secure_partition('gps_location_events_default');

CREATE FUNCTION gps_partition_name(month_start date) RETURNS text
    LANGUAGE sql IMMUTABLE AS
$fn$ SELECT 'gps_location_events_y' || to_char(month_start, 'YYYY') || 'm' || to_char(month_start, 'MM') $fn$;

CREATE FUNCTION gps_ensure_partitions(months_back integer, months_ahead integer) RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS
$fn$
DECLARE
    m date;
    created integer := 0;
BEGIN
    IF months_back < 0 OR months_back > 36 OR months_ahead < 0 OR months_ahead > 12 THEN
        RAISE EXCEPTION 'gps_ensure_partitions: out-of-range arguments';
    END IF;
    FOR i IN -months_back..months_ahead LOOP
        m := (date_trunc('month', now() AT TIME ZONE 'UTC') + make_interval(months => i))::date;
        IF to_regclass(gps_partition_name(m)) IS NULL THEN
            EXECUTE format(
                'CREATE TABLE %I PARTITION OF gps_location_events FOR VALUES FROM (%L) TO (%L)',
                gps_partition_name(m), (m::timestamp AT TIME ZONE 'UTC'),
                ((m + interval '1 month')::timestamp AT TIME ZONE 'UTC'));
            PERFORM gps_secure_partition(gps_partition_name(m));
            created := created + 1;
        END IF;
    END LOOP;
    RETURN created;
END
$fn$;

CREATE FUNCTION gps_partitions() RETURNS TABLE (name text, month_start date)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$fn$
    SELECT c.relname::text,
           to_date(substring(c.relname FROM 'y([0-9]{4}m[0-9]{2})$'), 'YYYY"m"MM')
    FROM pg_inherits i
    JOIN pg_class c ON c.oid = i.inhrelid
    WHERE i.inhparent = 'gps_location_events'::regclass
      AND c.relname ~ '^gps_location_events_y[0-9]{4}m[0-9]{2}$'
    ORDER BY 2
$fn$;

CREATE FUNCTION gps_retention_cutoff(keep_months integer) RETURNS date
    LANGUAGE sql STABLE AS
$fn$ SELECT (date_trunc('month', now() AT TIME ZONE 'UTC') - make_interval(months => keep_months))::date $fn$;

-- Archive export: rows of ONE partition that is entirely past the retention window, as JSON.
CREATE FUNCTION gps_partition_export(p_name text, keep_months integer) RETURNS SETOF jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$fn$
DECLARE
    m date;
BEGIN
    SELECT p.month_start INTO m FROM gps_partitions() p WHERE p.name = p_name;
    IF m IS NULL THEN RAISE EXCEPTION 'unknown partition %', p_name; END IF;
    IF keep_months < 1 OR m >= gps_retention_cutoff(keep_months) THEN
        RAISE EXCEPTION 'partition % is inside the retention window', p_name;
    END IF;
    RETURN QUERY EXECUTE format(
        'SELECT jsonb_build_object(''id'', id, ''tenant_id'', tenant_id, ''event_id'', event_id,
                ''device_id'', device_id, ''session_id'', session_id, ''trip_id'', trip_id,
                ''vehicle_id'', vehicle_id, ''driver_id'', driver_id, ''sequence_number'', sequence_number,
                ''lat'', ST_Y(point), ''lng'', ST_X(point), ''accuracy_m'', accuracy_m,
                ''speed_mps'', speed_mps, ''heading_deg'', heading_deg, ''recorded_at'', recorded_at,
                ''received_at'', received_at, ''source'', source, ''flags'', flags)
         FROM %I ORDER BY id', p_name);
END
$fn$;

-- Detach and drop ONE partition past the retention window. Called only after a verified archive and
-- only when retention drops are enabled (they delete data: approval required in production).
CREATE FUNCTION gps_drop_partition(p_name text, keep_months integer) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS
$fn$
DECLARE
    m date;
BEGIN
    SELECT p.month_start INTO m FROM gps_partitions() p WHERE p.name = p_name;
    IF m IS NULL THEN RAISE EXCEPTION 'unknown partition %', p_name; END IF;
    IF keep_months < 1 OR m >= gps_retention_cutoff(keep_months) THEN
        RAISE EXCEPTION 'partition % is inside the retention window', p_name;
    END IF;
    EXECUTE format('ALTER TABLE gps_location_events DETACH PARTITION %I', p_name);
    EXECUTE format('DROP TABLE %I', p_name);
    RETURN true;
END
$fn$;

-- Test/ops helper: create the partition for one specific (past) month, e.g. to restore an archive.
CREATE FUNCTION gps_create_month_partition(month_start date) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS
$fn$
DECLARE
    m date := date_trunc('month', month_start)::date;
BEGIN
    IF m < date '2020-01-01' OR m > (now() + interval '1 year')::date THEN
        RAISE EXCEPTION 'gps_create_month_partition: month out of range';
    END IF;
    IF to_regclass(gps_partition_name(m)) IS NOT NULL THEN RETURN false; END IF;
    EXECUTE format('CREATE TABLE %I PARTITION OF gps_location_events FOR VALUES FROM (%L) TO (%L)',
        gps_partition_name(m), (m::timestamp AT TIME ZONE 'UTC'), ((m + interval '1 month')::timestamp AT TIME ZONE 'UTC'));
    PERFORM gps_secure_partition(gps_partition_name(m));
    RETURN true;
END
$fn$;

REVOKE ALL ON FUNCTION gps_ensure_partitions(integer, integer), gps_partitions(),
    gps_partition_export(text, integer), gps_drop_partition(text, integer),
    gps_create_month_partition(date) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gps_ensure_partitions(integer, integer), gps_partitions(),
    gps_partition_export(text, integer), gps_drop_partition(text, integer),
    gps_create_month_partition(date) TO corridor_relay;

-- Partitions for the accepted window (12 months back, D-012) plus 3 months ahead.
SELECT gps_ensure_partitions(12, 3);
"""

GPS_REVERSE = """
DROP FUNCTION IF EXISTS gps_create_month_partition(date);
DROP FUNCTION IF EXISTS gps_drop_partition(text, integer);
DROP FUNCTION IF EXISTS gps_partition_export(text, integer);
DROP FUNCTION IF EXISTS gps_retention_cutoff(integer);
DROP FUNCTION IF EXISTS gps_partitions();
DROP FUNCTION IF EXISTS gps_ensure_partitions(integer, integer);
DROP FUNCTION IF EXISTS gps_partition_name(date);
DROP FUNCTION IF EXISTS gps_secure_partition(text);
DROP TABLE IF EXISTS gps_location_events CASCADE;
"""
