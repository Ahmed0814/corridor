# PROGRESS

| Phase | Status | Date |
|---|---|---|
| 0 Discovery & architecture | **Done** (DoD evidence below) | 2026-11-20 |
| 1 Foundation | **Done**: CI green incl. `docker compose up` + smoke tests (run 44924202637) | 2026-11-21 |
| 2 Security & tenancy | **Done except real Cognito login** (needs a user pool; local issuer verified). CI green | 2026-11-21 |
| 3 Core logistics | **Done**: CI green on `cfed399` (run 44958080301), all 5 jobs | 2026-11-21 |
| 4 GPS tracking | Not started | — |
| 5 Driver app & offline | Not started | — |
| 6 Customer & operations | Not started | — |
| 7 Infrastructure & deployment | Not started | — |
| 8 Final verification | Not started | — |

---

## Phase 0 — Discovery and architecture

### Definition of Done
| Criterion | Evidence |
|---|---|
| Architecture diagram in docs/ | `docs/architecture/overview.md`: system context, module map, 3 sequence diagrams (tenant context, GPS batch ingestion, dispatch + outbox). `docs/architecture/state-machines.md`: shipment, trip and tracking-session state diagrams plus assignment, vehicle and delivery rules |
| ERD in docs/ | `docs/database/erd.md`: 3 ER diagrams (identity/tenancy, logistics core, tracking/geofencing), partitioning DDL, validation flags, RLS template |
| Security model in docs/ | `docs/security/security-model.md`: threats, Cognito, role → permission matrix, DB roles, tenant context, realtime auth, public links, data protection, audit |
| Deployment diagram in docs/ | `docs/deployment/deployment.md`: AWS topology, pilot vs prod, environments, CI/CD pipeline diagram, health endpoints |
| Roadmap in docs/ | `docs/roadmap.md`: phase dependency diagram, deliverables, human gates, risks |
| DECISIONS.md has an entry for every choice that needed confirming | `DECISIONS.md`: D-001…D-031. Six are marked **Needs confirmation** (D-003, D-023, D-025, D-026, D-029, plus D-006's SMS OTP dependency) |

### Verification commands and real output

All Mermaid diagrams were rendered with `@mermaid-js/mermaid-cli@11.4.2` (installed in a temporary directory, not in the repo) using the local Chrome:

```
$ for f in docs/architecture/overview.md docs/architecture/state-machines.md docs/database/erd.md docs/deployment/deployment.md docs/roadmap.md; do mmdc -p pp.json -i "$f" -o out/$(basename $f .md).md -q && echo "OK $f" || echo "FAIL $f"; done
```
First run: 2 failures, which were fixed:
```
FAIL docs/architecture/overview.md
Error: Parse error on line 11: ... got 'NEWLINE'          # ';' inside sequence message text
FAIL docs/deployment/deployment.md
Error: Parse error on line 26: ... got 'PS'               # unquoted '(' in node label
```
After the fixes:
```
OK   docs/architecture/overview.md (5 diagrams)
OK   docs/architecture/state-machines.md (3 diagrams)
OK   docs/database/erd.md (3 diagrams)
OK   docs/deployment/deployment.md (2 diagrams)
OK   docs/roadmap.md (1 diagrams)
```

Decision cross-reference check (every `D-0xx` cited in docs/ is defined in DECISIONS.md):
```
$ refs=$(grep -rhoE "D-0[0-9]{2}" docs | sort -u); defined=$(grep -oE "^## D-0[0-9]{2}" DECISIONS.md | sed 's/## //' | sort -u); comm -23 <(echo "$refs") <(echo "$defined")
referenced in docs: 24, defined: 31
missing:
(end)
```

### Notable design findings (deviations from the brief, each recorded)
- **D-012**: PostgreSQL requires unique constraints on a partitioned table to include the partition key, so the GPS dedupe key becomes `(tenant_id, device_id, event_id, recorded_at)`. Django's `bulk_create(ignore_conflicts=True)` does not return ids, so duplicates are classified with `INSERT … ON CONFLICT DO NOTHING RETURNING event_id`.
- **D-023**: VPC interface endpoints alone cannot cover egress to Sentry, Cognito JWKS and SES, and may cost more than one NAT. To be decided with real prices in Phase 7.
- **D-028**: The public OSM tile servers are not allowed for production use. Basemap planned as a self-hosted PMTiles extract.
- **D-017 / D-007**: Public tracking links and the outbox relay need narrowly scoped cross-tenant access (a SECURITY DEFINER function and a dedicated role) instead of any general RLS bypass.

---

## Phase 1 — Foundation

### What was built
- **Backend** (`backend/`, Python 3.12, uv-managed): Django 5.2.19 project with 18 module apps (each with models/services/schemas/api/tasks/tests), Django Ninja API at `/api/v1` with a uniform error envelope and OpenAPI, the custom `identity.User` (UUID, Cognito-ready, no local passwords for tenant users), `ATOMIC_REQUESTS` on, health endpoints `/healthz/live` and `/healthz/ready`, structlog JSON logging with a stdlib bridge, correlation ids (HTTP → logs → Celery headers → Sentry tag), redaction of sensitive keys, Sentry with a strict data policy (D-036), Celery app on SQS with a beat heartbeat, Channels with a `/ws/v1/ping/` consumer, safety checks for deployed settings, and import-linter module contracts (D-005).
- **Docker**: `docker/backend.Dockerfile` (one image, four processes, non-root, GDAL), `apps/web/Dockerfile` (Next standalone, non-root), `docker-compose.yml` (db PostGIS 16-3.7, redis 7.4, ElasticMQ, migrate, api, realtime, worker, beat, web), and `scripts/smoke_compose.sh` (9 end-to-end checks).
- **Web** (`apps/web/`): Next.js 16.4.6, React 19, Tailwind 4, shadcn/ui (RTL-ready), next-intl with en/fr and cookie/Accept-Language resolution, the `(ops)/ops`, `(portal)/portal` and `(admin)/admin` route groups (D-039), a `/status` page backed by the API readiness check, Sentry instrumentation (inactive without a DSN), and Vitest tests.
- **Driver app** (`apps/driver-mobile/`): Expo SDK 58 TypeScript shell that explicitly says no tracking is active (no location code yet, Phase 5).
- **CI** (`.github/workflows/ci.yml`): backend (ruff, format, import-linter + generator drift check, mypy, Django checks, `makemigrations --check`, pytest against real PostGIS + Redis with `REQUIRE_SERVICES=1`, pip-audit), web (eslint, tsc, vitest, build, npm audit), mobile (tsc, expo-doctor, npm audit), gitleaks, and a compose job (build, `up`, smoke tests, Trivy on both images). Actions are pinned to commit SHAs.
- **Docs**: `docs/development.md`, `.env.example`.

### Definition of Done — status
| Criterion | Status | Evidence |
|---|---|---|
| `docker compose up` starts api, realtime, worker, beat, Postgres+PostGIS, Redis and web | **Verified in CI** (compose job, run 44924202637: Start the stack + 9 smoke checks incl. beat → SQS → worker heartbeat) | No Docker on this workstation. The compose file and smoke script are written, and the CI `compose` job runs them, but they have **never run**. Equivalent processes were run natively (below), except worker/beat. |
| CI runs lint, type check, makemigrations --check and tests on every push, and passes | **Verified**: all 5 jobs green on `18eb72e` (run 44924202637) | The workflow is written, but the repo has no GitHub remote and no commits yet. Every CI command was run locally with the results below. |
| Structured logging works | **Verified locally** | Tests + a live uvicorn process (below) |
| Sentry works | **Verified with an in-memory transport** | No real DSN exists (Needs credentials). Capture, request_id tag, scrubbing and data policy are tested. |

Phase 1 closed on 2026-11-21: https://github.com/Ahmed0814/corridor/actions/runs/44924202637 is green.

### CI history (first runs on GitHub; each failure was a real issue, fixed)
| Run commit | Failed step | Cause | Fix |
|---|---|---|---|
| `3eaf688` | backend: mypy | `os.add_dll_directory` is Windows-only, so the Linux type check failed | `sys.platform` guard |
| `5a28cd5` | backend: Django checks | `gis.W001`: GDAL < 3.9 cannot block file/network access (Ubuntu 3.8, bookworm 3.6) | Debian trixie GDAL 3.10 in image and CI (D-041) |
| `0d639ab` | compose: start | ElasticMQ health check used bash, which the Alpine image lacks | busybox `wget` probe |
| `39e1af3` | compose: smoke tests | script stored as non-executable (Windows git) | `git update-index --chmod=+x` |
| `41c89fa` | backend image scan | zlib CVE-2026-85091 in the base image | `apt-get upgrade` in the image |
| `7934442` | backend image scan | secret scanner: example key in autobahn's docstring | narrow `skip-files` (verified false positive) |
| `a13b66b`, `b976da8`, `cc203b8` | web image scan | npm bundled in the node base image: undici 6.28.0 (4 HIGH), brace-expansion 5.0.9 (2 HIGH) | remove package managers from the runtime image (D-050); findings now published as annotations |
| `18eb72e` | — | **all green** | — |

### Verification (real output, 2026-11-21, Windows workstation, portable Postgres 16.16 + PostGIS 3.7, Redis running)

Backend (`cd backend`):
```
$ uv run ruff check .                                      -> All checks passed!                              [exit 0]
$ uv run ruff format --check .                             -> 168 files already formatted                     [exit 0]
$ uv run mypy .                                            -> Success: no issues found in 168 source files    [exit 0]
$ uv run lint-imports                                      -> Contracts: 17 kept, 0 broken.                   [exit 0]
$ uv run python manage.py check --fail-level WARNING       -> System check identified no issues (0 silenced). [exit 0]
$ uv run python manage.py makemigrations --check --dry-run -> No changes detected                             [exit 0]
$ REQUIRE_SERVICES=1 uv run pytest -q                      -> 39 passed in 11.88s                             [exit 0]
$ uv run pip-audit --strict --skip-editable                -> No known vulnerabilities found                  [exit 0]
```
Resolved stack: Python 3.12.14, Django 5.2.19, django-ninja 1.8.0, Celery 5.7.0, Channels 4.3.2, structlog 26.1.0, sentry-sdk 2.75.0, GDAL 3.13.1, GEOS 3.15.0.

Negative checks:
```
# module boundary: a planted `from corridor.identity.models import User` in shipments
$ uv run lint-imports -> Only identity.services / identity.schemas are public BROKEN
                         Contracts: 16 kept, 1 broken.     (probe removed afterwards -> 17 kept)
# CI service gate: Redis unreachable must fail, not skip
$ REQUIRE_SERVICES=1 REDIS_URL=redis://127.0.0.1:6390/0 uv run pytest -q
  ERROR: REQUIRE_SERVICES=1 but Redis at redis://127.0.0.1:6390/0 is unreachable   [pytest exit=4]
```

Web (`cd apps/web`): `npm run lint` [exit 0] · `npm run typecheck` [exit 0] · `npm run test` -> 2 files, 10 tests passed [exit 0] · `npm run build` -> 6 routes compiled [exit 0] · `npm audit --audit-level=high` [exit 0; 1 moderate accepted, D-038]

Driver app (`cd apps/driver-mobile`): `npm run typecheck` [exit 0] · `npx expo-doctor@1.21.8` -> 20/20 checks passed [exit 0] · `npm audit --audit-level=high` [exit 0; 3 moderate accepted, D-038]

Secret scan (gitleaks 8.30.1 over the 270 files git would commit):
```
$ gitleaks dir <copy of `git ls-files -co --exclude-standard`> --config .gitleaks.toml --redact -> no leaks found
```

Native process smoke run (the smoke script's checks, run against `uvicorn` :8000, `daphne` :8001 and `node .next/standalone/server.js` :3000):
```
1 live:  {"status": "ok"}
2 ready: {"status": "ok", "checks": {"database": true, "redis": true}} [200]
3 request id: x-request-id: smoke-test-0001
4 access log: {"method": "GET", "path": "/api/v1/meta", "status": 200, "duration_ms": 46.7, "event": "http_request", "request_id": "smoke-test-0001", "level": "info", "logger": "corridor.access", "timestamp": "2026-11-21T05:31:04.246048Z"}
5 openapi title: Corridor API
6 postgis: 3.7.0
7 websocket: {'type': 'pong'}
9 web home [200]; web /status -> data-readiness="ok"; Accept-Language fr -> lang="fr", "Choisissez un espace"
Redis stopped -> api ready: {"status": "unavailable", "checks": {"database": true, "redis": false}} [503]
                 web /status -> data-readiness="degraded"; log: {"event": "readiness_redis_failed", "request_id": "68f9...", "level": "warning", ...}
```
Not run locally: smoke check 8 (beat -> SQS -> worker heartbeat), which needs ElasticMQ (Docker only). It runs in the CI compose job.

### Bugs found and fixed during verification
- Sentry captured each API error twice (logging integration + explicit capture). Logs are now breadcrumbs only.
- `cookies: False` silently resolved to Sentry's "denylist" mode. The correct form is `{"mode": "off"}`, caught by the policy test.
- `.env` would have been read in production (a leftover dev `DATABASE_URL`). It is now read only for development/test.
- The smoke test's web check would always have failed: next-intl sends every message string to the client, so text matching cannot detect state. It now uses an explicit `data-readiness` attribute.
- `grep -qv` in the smoke script could never fail. Rewritten.

### Phase 1 open items
- Push to GitHub and get the first green CI run. This closes the two unverified DoD rows. The compose job's Trivy scan may flag base-image CVEs on first run.
- ~~Mobile lint~~: done (ESLint with eslint-config-expo, fails on warnings, runs in CI). Sentry for React Native remains for Phase 5.

---

## Phase 2 — Security and tenancy

Started in a separate session, which was stopped before it recorded anything. Taken over and finished in the main session: its uncommitted work was reviewed and verified, and the driver sign-in was completed.

### What was built
- **Database roles** (D-007, D-044): `corridor_owner` (NOLOGIN, owns everything), `corridor_migrator`, `corridor_app`, `corridor_relay`, `corridor_platform`, created by `backend/db/bootstrap_roles.sql`. Runtime roles own nothing and cannot bypass RLS.
- **Tenancy**: `TenantOwnedModel` with a scoped manager that refuses to run without a tenant, forced RLS on every tenant table (`SET LOCAL app.tenant_id` inside the request transaction only), `tenant_context()` for Celery tasks (`@tenant_task`) and Channels consumers, and a platform-admin path on its own role with every action audited.
- **Identity**: tenants, users, memberships, platform-defined roles and the permission matrix in code (`identity/permissions.py`; the docs table is generated and checked in CI), invitations, suspension and reactivation, company switching, and an MFA gate for privileged roles (no permissions until MFA is verified).
- **Auth**: verification of Cognito-shaped RS256 access tokens (JWKS, issuer, client id, token use), client-kind enforcement (office / portal / driver), and a local OAuth issuer for dev/test (D-042).
- **Audit**: append-only `audit_logs` (the app role cannot update or delete) with rows for login (once per Cognito session), role change, company switch, invitation, suspension and platform actions.
- **Realtime**: `/ws/v1/tracking/` with first-message auth, origin allowlist, server-built group names and periodic membership re-checks (D-046).
- **Web**: OAuth code + PKCE sign-in, HttpOnly session cookies, a refresh route, company switching, a `proxy.ts` gate per area, and en/fr session messages.
- **Driver app** (finished in this session): sign-in via the system browser (expo-auth-session, PKCE), tokens in expo-secure-store, refresh before expiry and on 401, a profile screen, and driver-facing error messages. It still states that no tracking runs.

### Bugs found and fixed while verifying
- **Driver sign-in could never complete**: Django refused to redirect to `corridor-driver://`. Found by the end-to-end check, fixed in the local issuer (D-048), regression test added.
- The local `backend/.env` still pointed `DATABASE_URL` at the old Phase 1 superuser-like role, which would have run local tests as the wrong role. The line was removed, so settings default to `corridor_app`.
- One lint error (line length) in `tests/test_settings_safety.py`.

### Definition of Done — status
| Criterion | Status | Evidence |
|---|---|---|
| Cognito login works for web and driver flows | **Partly**: flows verified against the local issuer (same protocol and token checks), **not against real Cognito** | E2E run below (web office + driver-mobile clients). Real Cognito needs a user pool (Needs credentials). |
| RLS on every tenant table | Verified | `test_every_tenant_table_has_forced_rls_and_a_tenant_policy`, `test_global_tables_with_tenant_data_have_forced_rls` |
| Security test suite passes as the app role | Verified | 163 passed; `test_tests_run_as_the_application_role` asserts `current_user = corridor_app` |
| App role has no BYPASSRLS and owns no tables | Verified | `test_app_role_has_no_bypassrls_superuser_or_createrole`, `test_app_role_owns_no_tables_sequences_views_or_functions`, plus a direct check of the local cluster (below) |
| Changing tenant_id in a request has no effect | Verified | API tests + E2E: body `tenant_id` -> 422 (unknown fields forbidden); raw SQL cannot insert, update or move rows into another tenant; forged session variable rejected |
| Celery tasks and WebSocket consumers respect tenant context | Verified | `test_tenant_task_sees_only_its_tenant`, `test_fleet_subscription_is_limited_to_own_tenant`, `test_cannot_authenticate_into_another_tenant`, and 8 more WebSocket tests |
| Audit rows for login, role change, tenant switch | Verified | `test_login_is_audited_once_per_cognito_session`, `test_role_change_is_audited_and_visible_to_auditors`, `test_tenant_switch_is_audited_in_the_destination_tenant`; E2E produced `auth.login` x5, `membership.invited` x2, `membership.activated` x3, `tenant.created` x1 |

### Verification (real output, 2026-11-21, local Postgres 16.16 + PostGIS 3.7, Redis)

Backend (`cd backend`):
```
$ uv run ruff check .                                      -> All checks passed!                              [exit 0]
$ uv run ruff format --check .                             -> 191 files already formatted                     [exit 0]
$ uv run mypy .                                            -> Success: no issues found in 191 source files    [exit 0]
$ uv run mypy . --platform linux                           -> Success: no issues found in 191 source files    [exit 0]
$ uv run lint-imports                                      -> Contracts: 17 kept, 0 broken.                   [exit 0]
$ uv run python manage.py check --fail-level WARNING       -> System check identified no issues (0 silenced). [exit 0]
$ uv run python manage.py makemigrations --check --dry-run -> No changes detected                             [exit 0]
$ REQUIRE_SERVICES=1 uv run pytest -q                      -> 163 passed in 23.50s                            [exit 0]
$ uv run pip-audit --strict --skip-editable                -> No known vulnerabilities found                  [exit 0]
```

Local cluster roles (`select rolname, rolcanlogin, rolbypassrls, rolsuper from pg_roles where rolname like 'corridor%'`):
```
corridor|t|f|f   corridor_app|t|f|f   corridor_migrator|t|f|f   corridor_owner|f|f|f   corridor_platform|t|f|f   corridor_relay|t|f|f
```
Dev database: owned by `corridor_owner`, 16 application tables owned by `corridor_owner` (plus PostGIS's `spatial_ref_sys`).

Web (`cd apps/web`): `npm run lint` [exit 0] · `npm run typecheck` [exit 0] · `npm run test` -> 30 passed [exit 0] · `npm run build` -> 12 routes incl. `/auth/*` and the Proxy (Middleware) [exit 0]

Driver app (`cd apps/driver-mobile`): `npm run typecheck` [exit 0] · `npm test` -> 11 passed, 0 failed [exit 0] · `npx expo-doctor@1.21.8` -> 20/20 checks passed [exit 0]

End-to-end over HTTP against the running API (the same requests the web app and driver app make: authorization code + PKCE at the local issuer, then API calls). Demo company `demo-e2e` created with `manage.py create_tenant --demo`:
```
PASS  web: owner signs in, /me shows company + owner role  status=200 tenant=demo-e2e
PASS  web: owner without MFA is refused privileged actions  status=403 code=mfa_required
PASS  driver: uninvited phone has no company access  status=403 active_tenant=None code=no_access
PASS  web: owner invites a driver by phone  status=201
PASS  api: tenant_id in a request body is rejected (schema forbids unknown fields)  status=422 code=validation_error
PASS  driver app: invited driver signs in, /me shows company + driver role  status=200 role=driver client=driver-mobile
PASS  driver signing in through the office web client is refused  status=403 code=wrong_client
PASS  driver cannot list the company's members  status=403 code=forbidden
8/8 end-to-end checks passed
```
(The first E2E run failed at the driver step with `DisallowedRedirect: Unsafe redirect to URL with protocol 'corridor-driver'`. That is the bug fixed above.)

### Not verified / open
- **Real Cognito**: hosted UI, TOTP enrollment, phone verification and Cognito's token claims. Needs a user pool per environment (Needs credentials).
- **Driver app on a device or emulator**: the sign-in was verified at the HTTP level only. The browser hand-off and secure storage need an Expo development build (Phase 5 device plan).
- ~~First CI run of Phase 2~~: green (run 44924202637), including migrations as `corridor_migrator`, tests as `corridor_app`, and compose with the role bootstrap.

---

## Phase 3 — Core logistics

### What was built
- **Customers** (profiles, contacts, scoped access), **containers** (ISO 6346 number and check digit validated, availability, append-only movements/inspections), **fleet** (vehicles, trailers; "assigned" derived from the active assignment), **drivers** (license number encrypted at rest with a normalised keyed hash, PII only with `drivers.pii` or to the driver themselves, consent recording, link to the sign-in membership).
- **Shipments** state machine: draft → confirmed → dispatched → in_transit ⇄ at_border (clearance only with `shipments.confirm_clearance`, hard rule 8) → delivered / delivery_failed → reattempt; cancel from draft/confirmed; delayed is a flag. Containers are reserved on confirm and released on delivery/cancel; one container on at most one active shipment (partial unique index).
- **Trips** state machine: planned → assigned → in_progress ⇄ paused → completed / aborted; cancel from planned/assigned; only the assigned driver acts, or an office user with `trips.act_on_behalf` and a reason. Starting a trip moves its dispatched shipments to in_transit.
- **Dispatch**: `POST /dispatch` creates a trip, assigns vehicle + driver and dispatches the shipments in one transaction (all or nothing).
- **Corrections**: `/shipments/{id}/corrections` and `/trips/{id}/corrections` (owner/admin, reason required) append a `correction` event; history is never rewritten.
- **Idempotency** (D-015): `Idempotency-Key` required on every mutation; replay is byte-identical, a reused key with a different body gets 422, concurrent duplicates run once.
- **Transactional outbox** (D-014, D-051): business events written in the same transaction; relay on `corridor_relay` every 5 s.
- **Cursor pagination** on every list (D-053). All new tables have forced RLS (checked automatically by the Phase 2 coverage test); event tables are append-only for the app role.
- **Ops UI** (`/ops`): overview, shipments (list, filter, create, detail with status history and the allowed actions), dispatch, fleet (vehicles, drivers), customers, in English and French, via server actions (D-056).

### Bugs found and fixed while verifying
- Idempotent replay returned timestamps with microseconds while the original had milliseconds (Pydantic vs Ninja's encoder). Now stored exactly as Ninja renders.
- The duplicate-license check treated "ET-123456" and "ET123456" as different licenses (D-054).
- Ninja 1.8 deprecates `(201, body)` tuples. Endpoints now return `Status(201, body)`.
- Six services imported `identity.permissions`, which the boundary contracts now forbid. Caught by import-linter; switched to the public `identity.schemas`.

### Definition of Done — status
| Criterion | Status | Evidence |
|---|---|---|
| Customers, containers, shipments, vehicles, drivers, trips and dispatch work end to end | Verified locally | API: `tests/test_logistics.py` (full lifecycle from creation to delivery and trip completion, the dispatch endpoint, scopes). UI: 12/12 page checks + 7/7 real form submissions over HTTP (below). |
| All state machines enforce valid transitions | Verified | invalid/duplicate/premature transitions return 409 `invalid_transition` with the allowed sources; rules return specific codes (`no_assigned_trip`, `shipments_not_dispatched`, `vehicle_unavailable`, `assignment_conflict`, `container_unavailable`, `reason_required`). |
| Lifecycle tests pass, including the concurrent dispatch race test | Verified | `tests/test_dispatch_race.py::test_concurrent_dispatch_race_has_exactly_one_winner`: two threads, committed data, barrier-synchronised; results `["assignment_conflict", "ok"]`, trips end `["assigned", "planned"]`. |

### Verification (real output, 2026-11-21, local Postgres 16.16 + PostGIS 3.7, Redis)
Backend:
```
$ uv run ruff check .                                      -> All checks passed!                           [exit 0]
$ uv run ruff format --check .                             -> 197 files already formatted                  [exit 0]
$ uv run mypy .  /  uv run mypy . --platform linux         -> Success: no issues found in 197 source files [exit 0]
$ uv run lint-imports                                      -> Contracts: 17 kept, 0 broken.                [exit 0]
$ uv run python manage.py makemigrations --check --dry-run -> No changes detected                          [exit 0]
$ REQUIRE_SERVICES=1 uv run pytest -q                      -> 190 passed in 23.90s                         [exit 0]
```
(190 = 164 from Phases 1-2 + 23 in `test_logistics.py` + 3 in `test_dispatch_race.py`.)

Web: `npm run lint` [exit 0] · `npm run typecheck` [exit 0] · `npm run test` -> 4 files, 36 tests passed [exit 0] · `npm run build` -> `/ops`, `/ops/shipments`, `/ops/shipments/[id]`, `/ops/dispatch`, `/ops/fleet`, `/ops/customers` [exit 0]

UI end to end against the running API and web app (signed in through the web app's own OAuth flow; demo company `demo-e2e`):
```
PASS  web sign-in: callback sets the session  status=307
PASS  seed: shipment dispatched through /dispatch
PASS  page /ops · /ops/shipments · /ops/shipments/{id} · /ops/dispatch · /ops/fleet · /ops/customers · ?status=confirmed  (all 200, data present)
PASS  detail: dispatched shipment offers only 'Mark delayed' (state machine)  ['Mark delayed']
PASS  detail: confirmed shipment offers cancel + delay, no border clearance  ['Cancel shipment', 'Mark delayed']
PASS  detail: unknown id is a 404 page
12/12 UI checks passed
PASS  form carries a server action id and an idempotency key
PASS  form submit redirects back  303
PASS  double submit of one form creates exactly one customer  count=1
PASS  cancel via form succeeds
PASS  shipment shows cancelled with the reason in its history
PASS  a second cancel is refused by the state machine  ?error=invalid_transition&ref=…
PASS  the refusal is shown on the page with a reference
7/7 form checks passed
```

### CI
All five jobs green on the first run: https://github.com/Ahmed0814/corridor/actions/runs/44958080301
(backend incl. migrations as `corridor_migrator` and 190 tests as `corridor_app`; web; driver-mobile; gitleaks;
docker compose up with the relay role + smoke tests + Trivy on both images).

### Not in Phase 3 (by design)
- Opening a GPS tracking session on trip start, geofence-based border arrival, ETA: Phase 4/6.
- Delivery photo/signature/location evidence: Phase 6 (D-055).
- Driver app trip screens: Phase 5.

### Incident during this session
- The local PostgreSQL stopped at 16:58: Windows could not start a new backend process (`0xC0000142`, DLL initialisation failed), which happens under memory/resource exhaustion. The machine had been reporting low memory. Postgres shut down cleanly and recovered with no data loss on restart. Not a code issue; local dev servers are now stopped when not in use.

---

## Open issues
1. **Docker is not installed** on this workstation. Mitigated by D-032 (portable Postgres/PostGIS/Redis for local tests) and the CI compose job, which is green. Optional: install Docker Desktop with WSL2 to run `docker compose up` locally.
2. **Terraform is not installed** locally. Not needed until Phase 7.
3. Local Python is 3.13.15. The brief fixes 3.12, so containers and CI will use 3.12 (D-004).
4. `D:\` contains an unrelated git repository with an ownership mismatch. `D:\corridor` now has its own repository (D-030). No commits have been made yet.
5. `.devtools/` (about 1 GB, git-ignored) holds the portable dev tools. Delete it to remove them.

## Needs approval / human input
- **D-003** AWS region and data residency for Djibouti and Ethiopia (legal confirmation before real data).
- **D-029** Pilot AWS budget ("under $X/month") is blank. Needed before Phase 7 apply.
- **D-025** Hardware telematics in/out of pilot (default: out).
- **D-026** Rail/multimodal in/out of pilot (default: out).
- **D-023** Egress design (NAT vs interface endpoints): decide with Phase 7 prices.
- **D-037** Mobile app identifiers (`com.corridor.driver` placeholder) before the first store/EAS build.
- **D-027** Operators must verify the corridor reference geofences (port, borders, cities) before border events are trusted.

## Needs credentials
(Interfaces plus test adapters will ship. None of these are live.)
- Amazon Cognito user pools (dev/staging/prod)
- Email sending (Amazon SES: verified domain, production access)
- SMS sender for driver OTP to +253/+251 (post-pilot unless approved)
- Sentry DSNs (backend, web, mobile)
- Expo/EAS account and Android keystore, Apple developer account (iOS)
- AWS accounts and GitHub OIDC role (Phase 7)

## Needs device testing
- Phase 5: real Android devices (include at least one Tecno/Infinix and one Samsung, common in the region) and iOS if in scope. A human signs off here.
