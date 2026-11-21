-- Runs once when the local Postgres volume is first created.
-- PostGIS in template1 so the test database (created by pytest-django) inherits it
-- without the application role needing superuser rights.
\connect template1
CREATE EXTENSION IF NOT EXISTS postgis;
\connect corridor
CREATE EXTENSION IF NOT EXISTS postgis;
-- Phase 2 adds the dedicated roles (corridor_owner / corridor_migrator / corridor_app /
-- corridor_relay / corridor_platform) described in docs/security/security-model.md §4.1.
