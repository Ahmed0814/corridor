#!/usr/bin/env bash
# Runs once when the Postgres volume is first created (after 01-extensions.sql).
# Creates the database roles of DECISIONS D-007 with passwords from SSM (passed as container env).
set -euo pipefail
for db in template1 "$POSTGRES_DB"; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" \
    -v migrator_password="$CORRIDOR_MIGRATOR_PASSWORD" \
    -v app_password="$CORRIDOR_APP_PASSWORD" \
    -v relay_password="$CORRIDOR_RELAY_PASSWORD" \
    -v platform_password="$CORRIDOR_PLATFORM_PASSWORD" \
    -v allow_createdb=false \
    -f /docker-entrypoint-initdb.d/bootstrap_roles.sql.inc
done
