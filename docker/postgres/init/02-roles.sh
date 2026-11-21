#!/usr/bin/env bash
# Runs once when the local Postgres volume is first created (after 01-extensions.sql).
# Creates the database roles of DECISIONS D-007 with LOCAL-ONLY placeholder passwords.
# Deployed environments run backend/db/bootstrap_roles.sql with passwords from Secrets Manager.
set -euo pipefail
for db in template1 "$POSTGRES_DB"; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" \
    -v migrator_password=corridor_migrator_local \
    -v app_password=corridor_app_local \
    -v relay_password=corridor_relay_local \
    -v platform_password=corridor_platform_local \
    -v allow_createdb=true \
    -f /corridor-db/bootstrap_roles.sql
done
