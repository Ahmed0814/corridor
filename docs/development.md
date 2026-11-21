# Local development

There are two ways to run Corridor locally. **Docker Compose is the reference** (it matches CI and
deployment). The portable Windows setup exists because the original workstation has no Docker
(DECISIONS D-032).

## A. Docker Compose (reference)

Requirements: Docker Desktop (or Docker Engine) with Compose v2.

```bash
docker compose up --build        # db, redis, elasticmq, migrate, api, realtime, worker, beat, web
./scripts/smoke_compose.sh       # the same smoke tests CI runs
docker compose down -v           # stop and delete the local database volume
```

| Service | URL |
|---|---|
| api | http://localhost:8000/healthz/ready · http://localhost:8000/api/v1/docs |
| realtime | ws://localhost:8001/ws/v1/ping/ |
| web | http://localhost:3000 (status page: /status) |
| Postgres | localhost:5432 (corridor / corridor, local only) |
| ElasticMQ (SQS) | http://localhost:9324 |

Optional: `SENTRY_DSN=... docker compose up` to send backend errors to a Sentry project.

## B. Portable Windows setup (no Docker, no admin rights)

Everything lives in the git-ignored `.devtools/` folder; delete the folder to remove it.

| Tool | Source | Notes |
|---|---|---|
| PostgreSQL 16.16 | EnterpriseDB Windows binaries zip | cluster in `.devtools/pgdata`, `localhost:5432` only |
| PostGIS 3.7.0 | OSGeo `postgis-bundle-pg16-3.7.0x64.zip` | its `bin/` also provides GDAL 3.13 and GEOS 3.15 for GeoDjango |
| Redis 8.10.3 | community `redis-windows` msys2 build | **unofficial build, dev only**; production uses ElastiCache Redis 7.4 |
| gitleaks 8.30.1 | official release zip | local secret scan |

Two DLLs that `libgdal` needs are missing from the PostGIS bundle's `bin/` and were copied in:
`libbrotlicommon.dll` and `libbrotlidec.dll` (from the bundle's own `postgisgui/`) and
`libnghttp2-14.dll` (from Git for Windows' MinGW64, same toolchain).

### Start / stop

```bash
# Postgres
.devtools/pgsql/bin/pg_ctl.exe -D .devtools/pgdata -l .devtools/pg.log start
.devtools/pgsql/bin/pg_ctl.exe -D .devtools/pgdata stop

# Redis (foreground; Ctrl+C to stop)
.devtools/redis/Redis-8.10.3-Windows-x64-msys2/redis-server.exe --bind 127.0.0.1 --port 6379 --save "" --appendonly no
```

### Backend

**Database roles (once per cluster).** The app never connects as a superuser (DECISIONS D-007,
D-044). Create the roles with throwaway local passwords, as the cluster superuser:

```bash
export PGPASSWORD=devonly-postgres   # the local cluster superuser from initdb
for db in template1 corridor; do
  .devtools/pgsql/bin/psql.exe -h localhost -U postgres -d "$db" -v ON_ERROR_STOP=1     -v migrator_password=corridor_migrator_local -v app_password=corridor_app_local     -v relay_password=corridor_relay_local -v platform_password=corridor_platform_local     -v allow_createdb=true -f backend/db/bootstrap_roles.sql
done
```
(The `corridor` database must be owned by `corridor_owner`, with PostGIS enabled in it and in
`template1`; see `docker/postgres/init/` for the same steps compose runs.)

`backend/.env` (git-ignored, only read when `DJANGO_ENV` is development or test). No database URLs
are needed locally: settings default to `corridor_app` for requests, `corridor_platform` for the
audited Super Admin path and `corridor_migrator` for migrations, all with the `<role>_local`
passwords above.

```
DJANGO_ENV=development
GDAL_LIBRARY_PATH=D:/corridor/.devtools/pgsql/bin/libgdal-39.dll
GEOS_LIBRARY_PATH=D:/corridor/.devtools/pgsql/bin/libgeos_c.dll
```

```bash
cd backend
uv sync                                   # Python 3.12 venv (uv installs 3.12 if missing)
# Migrations run as the migration role, never as the app role:
DATABASE_URL=postgis://corridor_migrator:corridor_migrator_local@localhost:5432/corridor   uv run python manage.py migrate
uv run pytest                             # creates the test DB as corridor_migrator, runs as corridor_app
uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run lint-imports
../scripts/check_backend.sh                # everything the CI backend job runs, before pushing
uv run uvicorn config.asgi:application --port 8000     # api
uv run daphne -p 8001 config.asgi:application          # realtime
```

**Signing in locally.** With `AUTH_ISSUER_MODE=local` (the default in development), the API serves
a development stand-in for Cognito at `/dev-auth/*`. Its page asks only for an email or phone
number, with **no password check**, and it is refused in staging and production (D-042). Create a
demo company and its owner with:

```bash
uv run python manage.py create_tenant --slug demo --name "DEMO — Freight"   --owner-email owner@demo.test --reason "local dev" --demo
```
Then sign in at http://localhost:3000 as `owner@demo.test`, ticking "TOTP MFA enrolled" (owners
need MFA). Invite drivers by phone number from there.

The Celery worker and beat need the SQS-compatible broker (ElasticMQ), which only runs in Docker,
so the beat → SQS → worker path is verified in CI's compose job.

### Web

```bash
cd apps/web
npm install
npm run dev            # http://localhost:3000 ; set API_INTERNAL_URL=http://127.0.0.1:8000
npm run lint && npm run typecheck && npm run test && npm run build
```

### Driver app

```bash
cd apps/driver-mobile
npm install
npm run typecheck
npx expo-doctor
```
Running on a device or emulator needs an Expo development build (Phase 5).

## Conventions
- Python: Ruff (lint and format), mypy strict, import-linter module contracts generated by
  `backend/scripts/gen_importlinter.py`. Regenerate after adding a module.
- New Django app: add it under `backend/corridor/`, list it in `INSTALLED_APPS`, rerun the
  import-linter generator.
- Never commit `.env` files, credentials or `.devtools/`.
