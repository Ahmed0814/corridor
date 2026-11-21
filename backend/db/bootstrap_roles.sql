-- Database roles (DECISIONS D-007, docs/security/security-model.md §4.1).
--
-- Run ONCE per cluster as a superuser (or an RDS master user) BEFORE `manage.py migrate`:
--
--   psql -v ON_ERROR_STOP=1 \
--        -v migrator_password=... -v app_password=... \
--        -v relay_password=...    -v platform_password=... \
--        -v allow_createdb=false \
--        -d <database> -f backend/db/bootstrap_roles.sql
--
-- Passwords are psql variables, never literals in this file (hard rule 6). Local and CI runs
-- pass throwaway values; staging/production values come from Secrets Manager (Phase 7).
-- allow_createdb=true is for development and CI only: the test runner creates a test
-- database as corridor_migrator (acting as corridor_owner).
--
-- Idempotent: re-running updates passwords and attributes but never grants BYPASSRLS,
-- SUPERUSER or table ownership to a login role.

\set ON_ERROR_STOP on

-- SET (not SELECT set_config) so the values are never echoed in psql output.
SET corridor.migrator_password = :'migrator_password';
SET corridor.app_password = :'app_password';
SET corridor.relay_password = :'relay_password';
SET corridor.platform_password = :'platform_password';
SET corridor.allow_createdb = :'allow_createdb';

DO $$
DECLARE
    createdb text := CASE WHEN current_setting('corridor.allow_createdb') = 'true'
                          THEN 'CREATEDB' ELSE 'NOCREATEDB' END;
    r record;
BEGIN
    -- Owns every schema object. Cannot log in.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'corridor_owner') THEN
        CREATE ROLE corridor_owner NOLOGIN;
    END IF;
    EXECUTE format('ALTER ROLE corridor_owner NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE %s', createdb);

    FOR r IN SELECT * FROM (VALUES
        ('corridor_migrator', current_setting('corridor.migrator_password')),
        ('corridor_app',      current_setting('corridor.app_password')),
        ('corridor_relay',    current_setting('corridor.relay_password')),
        ('corridor_platform', current_setting('corridor.platform_password'))
    ) AS t(name, pw)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r.name) THEN
            EXECUTE format('CREATE ROLE %I LOGIN', r.name);
        END IF;
        EXECUTE format('ALTER ROLE %I LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOREPLICATION PASSWORD %L',
                       r.name, r.pw);
    END LOOP;

    -- Migrations: corridor_migrator logs in and immediately acts as corridor_owner, so every
    -- object it creates is owned by corridor_owner (never by a login role).
    GRANT corridor_owner TO corridor_migrator;
    ALTER ROLE corridor_migrator SET role = 'corridor_owner';
    EXECUTE format('ALTER ROLE corridor_migrator %s', createdb);

    -- Runtime roles get no CREATEDB and no membership in corridor_owner.
    ALTER ROLE corridor_app NOCREATEDB;
    ALTER ROLE corridor_relay NOCREATEDB;
    ALTER ROLE corridor_platform NOCREATEDB;
    -- Safety net against an older bootstrap or a manual grant.
    FOR r IN SELECT m.rolname AS name FROM pg_auth_members am
             JOIN pg_roles o ON o.oid = am.roleid AND o.rolname = 'corridor_owner'
             JOIN pg_roles m ON m.oid = am.member
             WHERE m.rolname IN ('corridor_app', 'corridor_relay', 'corridor_platform')
    LOOP
        EXECUTE format('REVOKE corridor_owner FROM %I', r.name);
    END LOOP;
END
$$;

-- Clear the temporary settings so passwords do not linger in this session.
RESET corridor.migrator_password;
RESET corridor.app_password;
RESET corridor.relay_password;
RESET corridor.platform_password;

-- The schema belongs to the database owner (PG15+ default: pg_database_owner). The runtime
-- roles may use it but never create objects in it.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO corridor_owner;
GRANT USAGE ON SCHEMA public TO corridor_app, corridor_relay, corridor_platform;
