-- Runs once when the local Postgres volume is first created.
-- PostGIS in template1 so the test database (created by pytest-django) inherits it
-- without the application role needing superuser rights.
\connect template1
CREATE EXTENSION IF NOT EXISTS postgis;
\connect corridor
CREATE EXTENSION IF NOT EXISTS postgis;
-- 02-roles.sh then creates the database roles (docs/security/security-model.md §4.1).
