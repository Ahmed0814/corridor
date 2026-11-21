# DECISIONS

Each entry gives the context, the choice and the trade-off.
Status: **Fixed** = given by MASTER_PROMPT §2. **Decided** = chosen under rule §0.6 (simplest safe option). **Needs confirmation** = a working default is in place, but a human must confirm because it affects security, data integrity, cost or legal exposure.

| ID | Title | Status |
|---|---|---|
| D-001 | Modular monolith | Fixed |
| D-002 | One backend image, four process types | Decided |
| D-003 | AWS region and data residency | **Needs confirmation** |
| D-004 | Python 3.12 in containers | Decided |
| D-005 | Module boundary enforcement | Decided |
| D-006 | Cognito layout, MFA enforcement, local test issuer | Decided (driver SMS OTP needs credentials) |
| D-007 | Database roles | Decided |
| D-008 | Platform-defined roles for the pilot | Decided |
| D-009 | Celery on SQS, ElasticMQ locally, singleton beat | Decided |
| D-010 | Primary key strategy | Decided |
| D-011 | GPS ingestion is synchronous in the api | Decided |
| D-012 | GPS partitioning, dedupe key, duplicate detection | Decided (deviation from brief) |
| D-013 | Late uploads after a session closes | Decided |
| D-014 | Transition services and outbox | Fixed / Decided |
| D-015 | Idempotency keys | Decided |
| D-016 | Routing engine | Decided provisionally; evaluate in Phase 4/6 |
| D-017 | Public tracking link resolution | Decided |
| D-018 | Append-only enforcement via grants | Decided |
| D-019 | Application-level encryption of driver license numbers | Decided |
| D-020 | Timezone and calendar | Decided |
| D-021 | Currency minor units | Decided |
| D-022 | Upload scanning deferred | Decided |
| D-023 | Egress: NAT vs VPC interface endpoints | **Needs confirmation (cost)** |
| D-024 | Hosting the Next.js app | Decided |
| D-025 | Hardware telematics out of pilot | **Needs confirmation** |
| D-026 | Rail/multimodal out of pilot | **Needs confirmation** |
| D-027 | Corridor reference geofence coordinates | Decided (verification needed) |
| D-028 | Basemap tiles via self-hosted PMTiles | Decided |
| D-029 | Bracketed pilot targets adopted as defaults | **Needs confirmation (budget missing)** |
| D-030 | Repository root and git | Decided |
| D-031 | No Celery result backend | Decided |
| D-032 | Portable local dev tools (no Docker on workstation) | Decided |
| D-033 | Uvicorn workers instead of Gunicorn | Decided |
| D-034 | Next.js Cache Components off | Decided |
| D-035 | System font stack in the web app | Decided |
| D-036 | Strict Sentry data collection | Decided |
| D-037 | Mobile app identifiers `com.corridor.driver` | **Needs confirmation** |
| D-038 | Accepted moderate npm advisory (minimatch) | Decided (revisit) |
| D-039 | URL prefixes per web area | Decided |
| D-040 | Health endpoints outside request transactions | Decided |
| D-041 | GDAL >= 3.9 everywhere (Debian trixie base) | Decided |
| D-042 | Local OAuth issuer standing in for Cognito (dev/test only) | Decided |
| D-043 | Django admin in development only | Decided |
| D-044 | Database roles created by a bootstrap script before migrations | Decided |
| D-045 | Every API error response rolls back the request transaction | Decided |
| D-046 | WebSocket auth in the first message, with an origin allowlist | Decided |
| D-047 | Client IP and user agent only in audit rows, never in logs | Decided |
| D-048 | Driver app redirect via its custom URL scheme | Decided |
| D-049 | Driver app unit tests with `node --test` | Decided |
| D-050 | No package managers in the web runtime image | Decided |
| D-051 | Outbox relay on its own database role | Decided |
| D-052 | Trip assignments owned by trips; dispatch orchestrates | Decided |
| D-053 | Cursor pagination on every list | Decided |
| D-054 | License lookup hash ignores case, spaces and punctuation | Decided |
| D-055 | Delivery in Phase 3 needs status + recipient; evidence in Phase 6 | Decided |
| D-056 | Ops screens use server actions with per-form idempotency keys | Decided |
| D-057 | GPS device bound to the tracking session by the first upload | Decided |
| D-058 | Partition maintenance and retention via narrow SECURITY DEFINER functions | Decided (drop needs approval) |
| D-059 | Live map polls a same-origin feed every 5 s (WebSocket push server-side) | Decided (revisit) |
| D-060 | Development basemap: MapLibre demo tiles, configurable | Decided |
| D-061 | GPS validation limits | Decided |
| D-062 | Offline core as plain TypeScript over a SQL interface | Decided |
| D-063 | Capture cadence and on-device thinning | Decided (tune after device tests) |
| D-064 | Mock-location fixes are never recorded | Decided |
| D-065 | Malformed batches are bisected; 401 pauses uploads | Decided |
| D-066 | Driver app navigation without Expo Router (for now) | Decided (revisit) |

---

## D-001 Modular monolith
**Context:** Brief §2. **Choice:** One repo, one PostgreSQL database, one Django codebase split into business-module apps. **Trade-off:** Simple operations and transactions across modules. Each module can only scale with the whole monolith, which is acceptable at pilot scale (300 trucks).

## D-002 One backend image, four process types
**Context:** The brief says "three processes" (api, realtime, worker) but the pilot config also lists a beat task. **Choice:** One backend image run with four commands: api, realtime, worker and beat. Beat is a scheduler singleton, not a separate service type. The Next.js web app has its own image (D-024). **Trade-off:** Each process scales separately. An extra small task for beat.

## D-003 AWS region and data residency — NEEDS CONFIRMATION
**Context:** The brief proposes `me-central-1` (UAE) and asks to confirm data residency for Djibouti and Ethiopia. Both countries have data-protection legislation that may restrict cross-border transfer of personal data (driver identities, phone numbers, GPS traces). I have not verified the current legal requirements and must not guess. **Choice:** Design with `me-central-1` as the working assumption. Keep the region a single Terraform variable. Before Phase 7, verify that every needed service is available there, including Cognito user pools, RDS PostgreSQL 16 with PostGIS, ElastiCache, SES (email may need a different region), ACM for CloudFront (always `us-east-1`) and WAF. **Needs:** Legal confirmation from counsel in both jurisdictions before any real customer data is loaded. The fallback, if in-country hosting is mandated, would be a different hosting model and would invalidate parts of D-023/Phase 7. **Trade-off:** Phases 1–6 are region-independent, so the work proceeds.

## D-004 Python 3.12 in containers
**Context:** The brief fixes Python 3.12. The workstation has Python 3.13.15 and no 3.12. **Choice:** Containers and CI use `python:3.12-slim` (pinned digest). Local tooling may run on 3.13, but test evidence for Phase DoD comes from the 3.12 container or CI. **Trade-off:** Local-only runs can differ slightly. CI is authoritative.

## D-005 Module boundary enforcement
**Context:** The brief's module rule. **Choice:** Each module's `services.py` and `schemas.py` are its only public surface. Cross-module foreign keys are allowed at the database level, using string references, for referential integrity. ORM traversal across modules is forbidden. Enforcement: `import-linter` contracts in CI, plus code review. **Trade-off:** Some duplicated DTOs and extra service calls, in exchange for boundaries that hold.

## D-006 Cognito layout, MFA enforcement, local test issuer
**Context:** Email login for office users, phone login for drivers, and MFA required for privileged roles. Roles must not be trusted from the client. **Choice:**
- One user pool per environment. Three app clients: `web-office`, `web-portal`, `driver-mobile`. Authorization code + PKCE. Django validates **access tokens** (JWKS, iss, client_id, token_use, exp).
- Roles live only in `tenant_memberships`. Cognito groups are not used for authorization.
- MFA: pool MFA *optional*, TOTP only (no SMS cost). The server refuses all permissions of a `requires_mfa` role until it has confirmed through Cognito that TOTP MFA is active for that user (`users.mfa_verified_at`). A separate pool for privileged users was rejected because the same person can hold different roles in different tenants.
- Drivers: phone number + password in the pilot. SMS OTP is listed under "Needs credentials".
- Tests and dev: a local RSA key pair issues Cognito-shaped JWTs, served from a test JWKS endpoint. The same verification code path runs. It is enabled only when `DJANGO_ENV in {development, test}`, and a startup check refuses it otherwise.
**Trade-off:** MFA enforcement relies on a server-side check instead of a Cognito pool setting, which is more code. It gives per-role enforcement.

## D-007 Database roles
**Context:** The app role must not own tables or bypass RLS. Migrations use a separate role. Some jobs legitimately span tenants. **Choice:** `corridor_owner` (NOLOGIN, owns objects), `corridor_migrator` (migrations), `corridor_app` (runtime), `corridor_relay` (outbox relay and partition maintenance, with narrow cross-tenant policies), `corridor_platform` (audited Super Admin path, read policies on selected tables). Django has a `platform` DB alias for the last one, and a database router stops ordinary code from using it. The session-variable "bypass" was rejected because any SQL injection could set it. **Trade-off:** Several credentials to manage in Secrets Manager. More connection pools.

## D-008 Platform-defined roles for the pilot
**Context:** The brief asks for roles and granular permissions. **Choice:** Nine fixed roles. The permission matrix is defined in code and seeded by migration. Tenant-customizable roles are post-pilot. **Trade-off:** Less flexible, but no tenant can grant themselves an unexpected capability.

## D-009 Celery on SQS, ElasticMQ locally, singleton beat
**Context:** SQS is the fixed broker. Celery on SQS has no remote control or broadcast, and the visibility timeout must exceed the longest task. **Choice:** Queues `corridor-events` (outbox-delivered business events), `corridor-default` and `corridor-events-dlq` (redrive after 5 receives), with visibility timeout 15 min and `task_acks_late = True`. All handlers are idempotent (the `processed_messages` table). The local compose file runs ElasticMQ (SQS-compatible) so dev matches prod. Beat uses a static code schedule (no django-celery-beat DB scheduler) and runs as exactly one ECS task. The outbox relay uses `FOR UPDATE SKIP LOCKED`, so an accidental second beat cannot double-publish, though it may publish concurrently. **Trade-off:** No Celery Flower or remote control. Handlers must be idempotent anyway.

## D-010 Primary key strategy
**Choice:** UUID4 primary keys on business tables (non-enumerable, safe in URLs). `BIGINT IDENTITY` on high-volume append-only tables (`gps_location_events`, `*_events`, `outbox_events`, `audit_logs`). **Trade-off:** UUID index locality is worse than with UUIDv7. That is acceptable at this volume, and the switch can come once Python 3.14's `uuid.uuid7` is available in the runtime.

## D-011 GPS ingestion is synchronous in the api
**Context:** 300 trucks × one batch every ~30 s ≈ 10 requests/s. **Choice:** Validate and insert inside the request so the batch response can report accepted, duplicate and rejected ids accurately. No queue in the GPS path. The realtime push is sent `on_commit` (non-critical). **Trade-off:** API latency includes the DB insert. A batch of 500 events with one multi-row insert fits the budget. Revisit if ingestion exceeds about 200 requests/s.

## D-012 GPS partitioning, dedupe key, duplicate detection (deviation from brief)
**Context:** The brief asks for unique `(tenant_id, device_id, event_id)` on a table partitioned by month, and duplicate classification by comparing IDs returned from `bulk_create(ignore_conflicts=True)`. PostgreSQL requires unique constraints on partitioned tables to include the partition key. Django does not set primary keys on objects when `ignore_conflicts=True`. **Choice:** Partition by `RANGE (recorded_at)`, monthly, plus a DEFAULT partition. Unique key `(tenant_id, device_id, event_id, recorded_at)`. Insert with raw `INSERT … ON CONFLICT DO NOTHING RETURNING event_id`. Event ids that are not returned are duplicates. The app generates `event_id` and `recorded_at` together at capture and persists them, so honest retries always collide. **Trade-off:** A client that reuses an `event_id` with a *different* `recorded_at` will not be caught by the constraint. The validator also checks the `(device_id, event_id)` pair against the device's recent events (last 7 days, indexed) and flags reuse. An alternative global dedupe table was rejected because it doubles writes.

## D-013 Late uploads after a session closes
**Context:** Offline drivers may upload hours after the trip completed. Writes to closed trips must be rejected. **Choice:** Accept events for a closed session only if `received_at ≤ closed_at + 24 h` **and** `recorded_at` falls within the session's active interval. Flag them `late_upload`. They never move the latest location backwards (the conditional upsert prevents that). **Trade-off:** A 24 h window. Configurable per tenant.

## D-014 Transition services and outbox
**Context:** Brief §4.3 and §5. **Choice:** One explicit service function per transition, following a shared template (decorator for permission, idempotency and event emission). Outbox rows are written in the same transaction. The relay runs every 2 s from beat (`corridor_relay` role) and sends to SQS with SendMessageBatch. `transaction.on_commit` is used only for realtime pushes and cache invalidation. **Trade-off:** About 2 s publication latency for business events, which is fine. GPS is not on this path.

## D-015 Idempotency keys
**Choice:** Required on state-changing POSTs (400 if missing). Scope `(tenant_id, user_id, key)`. Store a SHA-256 of method + path + body. The same key with a different hash returns 422 `idempotency_key_reused`. A concurrent duplicate waits on a row lock and then replays. TTL 24 h, purged by beat. GPS batch endpoints rely on per-event dedupe instead of a header. **Trade-off:** One more write per mutation.

## D-016 Routing engine (provisional)
**Context:** The brief allows OSRM or another provider after a corridor coverage test. **Choice:** Self-hosted OSRM (car profile) with a Djibouti + Ethiopia OpenStreetMap extract, run as a small ECS service. No per-request cost, no credentials, no customer data sent to a third party. Phase 4/6 runs a coverage test on the Djibouti–Galafi–Addis and Djibouti–Dewele–Dire Dawa corridors and records the result here. **Trade-off:** We own updates to the OSM extract (a monthly rebuild job). A truck profile with weight and height limits is not in the pilot.

## D-017 Public tracking link resolution
**Context:** A public request has no tenant context, but RLS hides every row. **Choice:** Store `sha256(token)`. Resolve it through a `SECURITY DEFINER` function owned by `corridor_owner` that returns only `(tenant_id, shipment_id, allowed_fields)` for live links. The API then sets tenant context as usual. Responses use an allowlist of fields, coarse position by default, a uniform 404 and a per-IP rate limit. **Trade-off:** A small, audited bypass surface instead of a broad one.

## D-018 Append-only enforcement via grants
**Choice:** `corridor_app` gets only `SELECT, INSERT` on `*_events`, `audit_logs` and `gps_location_events`. `UPDATE`/`DELETE` are revoked. A test checks this. The retention drop runs as `corridor_relay` on detached partitions, with approval in production. **Trade-off:** Corrections must be modeled as new rows, which the brief requires anyway.

## D-019 Application-level encryption of driver license numbers
**Choice:** Fernet (via `cryptography`) with a key list from Secrets Manager (MultiFernet for rotation). A separate keyed hash column allows exact-match lookups. Other PII relies on RDS encryption at rest plus access control. **Trade-off:** No database-side search on license numbers except exact match.

## D-020 Timezone and calendar
**Choice:** Store UTC. Djibouti (`Africa/Djibouti`) and Ethiopia (`Africa/Addis_Ababa`) are both UTC+3 with no DST, so the UI displays EAT by default and the timezone is a per-user setting. The Ethiopian calendar and 12-hour Ethiopian clock display are post-pilot (needed with Amharic). **Trade-off:** None for the pilot.

## D-021 Currency minor units
**Choice:** `amount_minor BIGINT` + `currency CHAR(3)`. Exponents from ISO 4217: DJF 0, ETB 2, USD 2, held in a code table. No floats anywhere in money paths. **Trade-off:** None.

## D-022 Upload scanning deferred
**Choice:** Pilot: pre-signed uploads with a content-type allowlist, magic-byte sniffing in a worker, a 10 MB limit and tenant-prefixed keys. A document is `pending` until sniffing passes. Malware scanning (ClamAV or GuardDuty Malware Protection for S3) is post-pilot. **Trade-off:** Residual risk from malicious PDFs being downloaded by other users of the same tenant. Recorded in the security review.

## D-023 Egress: NAT vs VPC interface endpoints — NEEDS CONFIRMATION (cost)
**Context:** The brief prefers VPC endpoints over a NAT Gateway. But tasks also need internet egress for Sentry, Cognito JWKS and possibly SES, which endpoints alone cannot all cover. Each interface endpoint is billed per AZ-hour, so 6–8 endpoints across 2 AZs can cost more than one NAT. **Choice:** Always use the free S3 gateway endpoint. In Phase 7, compare (a) one NAT Gateway, (b) a small NAT instance, and (c) interface endpoints (ECR api/dkr, logs, secretsmanager, sqs) plus a minimal egress path. Present prices for the confirmed region before applying anything. **Trade-off:** Decided with real prices, not in advance.

## D-024 Hosting the Next.js app
**Context:** The web app needs server routes (the auth code exchange and HttpOnly cookies), so a pure static export does not work. **Choice:** Next.js `output: "standalone"` in its own image, run as an ECS service behind the same ALB and CloudFront. **Trade-off:** One more ECS service. Avoids adding Amplify Hosting or Vercel as a new vendor.

## D-025 Hardware telematics — out of pilot (NEEDS CONFIRMATION)
**Choice:** The pilot uses the driver phone app as the only GPS source. The schema already has `source` and `gps_devices`, and ingestion validation does not depend on the source, so a telematics adapter (device-credential auth, vendor webhook or TCP gateway) can be added later. **Confirm:** whether any pilot tenant already has trackers installed, which would change the priority.

## D-026 Rail / multimodal — out of pilot (NEEDS CONFIRMATION)
**Choice:** `trips.mode` exists with `road` as the only allowed value in the pilot. Container and shipment modeling already supports multiple trips per shipment, so a rail leg (Addis Ababa–Djibouti railway) can be added as another trip mode later. **Confirm:** with pilot tenants.

## D-027 Corridor reference geofence coordinates
**Context:** The map must show the Port of Djibouti, Djibouti City, the Galafi and Dewele border crossings, Dire Dawa and Addis Ababa. Hard rule 9 (no invented locations) applies in spirit to reference data. **Choice:** Reference geofences are platform-owned rows (`tenant_id NULL`), loaded by a data migration from a reviewed GeoJSON file that cites its source (OpenStreetMap ids). Polygons are drawn from OSM and **marked `verified=false` until an operator confirms them**. Border-arrival events from unverified geofences are labelled as such in the UI. **Trade-off:** One manual verification step before the pilot.

## D-028 Basemap tiles via self-hosted PMTiles
**Context:** The brief fixes MapLibre + OpenStreetMap data. The public `tile.openstreetmap.org` servers must not be used for production apps (OSMF tile usage policy). **Choice:** A Protomaps PMTiles extract covering Djibouti and Ethiopia, stored in S3 and served through CloudFront. No API key, no per-request vendor fee, and attribution displayed. Dev uses the same file served locally. **Trade-off:** We rebuild the extract periodically. A commercial tile provider stays a fallback behind the same style URL (a "Needs credentials" item if chosen).

## D-029 Bracketed pilot targets adopted as defaults — NEEDS CONFIRMATION
**Choice:** The bracketed values in the brief (3 tenants, 300 trucks, 400 drivers, 2,000 shipments per month, 100 office users, p95 < 300 ms, 10 s map latency, RPO 24 h / RTO 4 h, freshness thresholds 2/10/60 min, GPS retention 12 months) are adopted as working defaults. Freshness thresholds are tenant settings. **Missing:** the pilot AWS budget ("under $X/month") is not filled in. The Phase 7 cost estimate will be checked against it, and a budget is needed before `terraform apply`.

## D-030 Repository root and git
**Context:** The brief's tree is rooted at `corridor-platform/`. The working directory is `D:\corridor`, and the enclosing drive root `D:\` contains an unrelated git repository owned by a different user (git reported "dubious ownership"). **Choice:** `D:\corridor` is the repository root, with its own `git init -b main`, so the platform is isolated from the drive-level repo. The directory name differs from the brief's tree. Nothing else changes. **Trade-off:** None.

## D-031 No Celery result backend
**Choice:** `task_ignore_result = True`. Business state lives in PostgreSQL, so no Redis/SQS result backend is used. **Trade-off:** `AsyncResult` cannot be used, and nothing needs it.

## D-032 Portable local dev tools (no Docker on workstation)
**Context:** Phase 1 DoD needs `docker compose up`, but this workstation has no Docker, WSL or admin installs. Rule §0.7 says to apply the safest available fix. **Choice:** (1) CI runs the real compose stack plus `scripts/smoke_compose.sh` on every push. That is the authoritative DoD check. (2) For local tests, `.devtools/` (git-ignored) holds EnterpriseDB's PostgreSQL 16.16 binaries, the OSGeo PostGIS 3.7 bundle (also the GDAL/GEOS source for GeoDjango on Windows), a community Redis build, and gitleaks. All are bound to localhost. `settings.py` registers the GDAL DLL directory on Windows only. **Trade-off:** local Redis 8.10 differs from production 7.4, and the Redis build is unofficial. Celery/SQS cannot run locally without ElasticMQ, so it is CI-only. See `docs/development.md`.

## D-033 Uvicorn workers instead of Gunicorn
**Context:** The brief allows "Uvicorn/Gunicorn". Gunicorn's `uvicorn.workers` class is deprecated, and Gunicorn does not run on Windows. **Choice:** `uvicorn --workers N --proxy-headers` for `api`, Daphne for `realtime`. **Trade-off:** Gunicorn's more advanced worker management is unavailable. ECS replaces unhealthy tasks anyway.

## D-034 Next.js Cache Components off
**Context:** Next 16's scaffold enables `cacheComponents`. The root layout reads the locale cookie for `<html lang dir>`, and every page is per-tenant. **Choice:** `cacheComponents: false` until a page actually benefits from static caching. **Trade-off:** no partial pre-rendering. Irrelevant for authenticated dashboards.

## D-035 System font stack in the web app
**Choice:** system UI fonts (including Noto Sans Ethiopic where installed) instead of `next/font/google`. No build-time font download, and no font requests to third parties from users' browsers. **Trade-off:** typography varies slightly by OS.

## D-036 Strict Sentry data collection
**Context:** Sentry's newer SDKs (Python 2.75, JS 11.x) replace `send_default_pii` with `data_collection`, and their defaults collect cookies, headers and bodies. **Choice:** explicit policy on backend and web: user info off, cookies off, query strings off, bodies off, stack-frame local variables off, request headers allowlisted (`user-agent`, `x-request-id`, `accept-language`). Plus our `before_send` scrubber. A test asserts the resolved policy. **Trade-off:** less context in error reports. The request id links an event to our own logs.

## D-037 Mobile app identifiers — NEEDS CONFIRMATION
**Choice:** Android package and iOS bundle id `com.corridor.driver` as placeholders. These become permanent once an app is published to Google Play or the App Store. **Confirm:** the organization's reverse-domain name before the first store or EAS build (Phase 5).

## D-038 Accepted moderate npm advisory (minimatch)
**Context:** `npm audit` reports GHSA-g3hv-75wg-m249 (moderate, ReDoS) in `minimatch`, pulled in by Expo's build-time `@expo/fingerprint` (mobile) and by the shadcn CLI's `ts-morph` (web). The suggested fix downgrades Expo 58 to 52. **Choice:** accept for now. These are build-time tools that never process untrusted input at runtime. CI fails on high/critical (`npm audit --audit-level=high`). **Revisit:** at each dependency update.

## D-039 URL prefixes per web area
**Context:** The brief asks for separate route groups and auth scopes for operations, the customer portal and platform admin. Route groups alone do not change URLs. **Choice:** `app/(ops)/ops`, `app/(portal)/portal`, `app/(admin)/admin`: a group per area for its own layout, and a URL prefix so `proxy.ts` (Next 16's renamed middleware) can enforce each auth scope by path in Phase 2.

## D-040 Health endpoints outside request transactions
**Context:** `ATOMIC_REQUESTS` (needed for `SET LOCAL app.tenant_id`) would open a DB transaction for every probe. **Choice:** `/healthz/live` and `/healthz/ready` are `non_atomic_requests`. Liveness touches no dependency, and readiness runs its own `SELECT 1` and Redis `PING`.

## D-041 GDAL >= 3.9 everywhere (Debian trixie base)
**Context:** The first CI run failed `manage.py check --fail-level WARNING` with Django's `gis.W001`: GDAL older than 3.9 cannot block file and network access triggered by malicious spatial references. Ubuntu 24.04 (CI) ships GDAL 3.8.4 and Debian bookworm (the image) ships 3.6.2. Locally it passed only because the PostGIS bundle carries GDAL 3.13. **Choice:** the backend image uses `python:3.12.16-slim-trixie` (GDAL 3.10.3), and the CI backend job runs inside that same image, so CI tests the production GDAL. The warning stays an error, and is not silenced. **Trade-off:** trixie is newer than bookworm, so some package names differ (`libcurl4t64`).

## D-042 Local OAuth issuer standing in for Cognito (dev/test only)
**Context:** No Cognito user pool exists yet (Needs credentials), but Phase 2 needs real login flows to test against. **Choice:** `corridor.identity.local_issuer` implements the same OAuth 2.0 authorization code + PKCE (S256) flow and refresh grant as Cognito, issuing RS256 access tokens with a published JWKS. Django verifies them through the same code path as Cognito tokens. Its sign-in page has **no password check** and says so. Settings refuse `AUTH_ISSUER_MODE=local` outside development/test (tested). Redirect URIs are an exact-match allowlist per client. **Trade-off:** real Cognito behaviour (MFA enrollment, phone verification, hosted UI) is untested until a pool exists.

## D-043 Django admin in development only
**Choice:** `/platform-admin/` (Django admin) is mounted only when `DJANGO_ENV=development`. Tenant data sits behind RLS, so the admin could not browse it anyway. Platform administration in deployed environments uses the audited `/api/v1/platform` API on the `corridor_platform` role (D-007). **Trade-off:** no admin UI in staging/production until a platform-admin screen is built.

## D-044 Database roles created by a bootstrap script before migrations
**Context:** Creating roles needs superuser rights, which migrations must not have. **Choice:** `backend/db/bootstrap_roles.sql` runs once per cluster as a superuser (the RDS master user in AWS), with passwords passed as psql variables, never in the file. It is idempotent, and never grants BYPASSRLS, SUPERUSER or ownership to a login role. `corridor_migrator` logs in and immediately acts as `corridor_owner`, so every object is owned by the NOLOGIN owner role. Compose runs it from `docker/postgres/init/02-roles.sh`, and CI runs it before migrating. **Trade-off:** one manual (or Terraform-run) step per new database.

## D-045 Every API error response rolls back the request transaction
**Context:** Ninja turns exceptions into responses *inside* the `ATOMIC_REQUESTS` transaction, so writes made before an error would otherwise commit. **Choice:** `error_response()` marks the transaction for rollback, so no error response leaves a partial write (e.g. no half-recorded login audit row; tested). **Trade-off:** none.

## D-046 WebSocket auth in the first message, with an origin allowlist
**Choice:** `/ws/v1/tracking/` accepts the connection, then requires `{"action":"auth","token":...}` within 10 s, resolved exactly like an HTTP request. A token in the URL is ignored, because URLs end up in logs. Browser origins must be in `WEB_ALLOWED_ORIGINS`. Groups are named server-side only. Membership is re-checked every 15 minutes. **Trade-off:** a socket is briefly open before authentication (closed on timeout; tested).

## D-047 Client IP and user agent only in audit rows, never in logs
**Choice:** the request middleware binds `REMOTE_ADDR` (after uvicorn/daphne apply the ALB's forwarded headers; `X-Forwarded-For` is never read directly) and the user agent for audit rows only. IP addresses are personal data and are not written to application logs. **Trade-off:** IP-based debugging needs the audit table or ALB logs.

## D-048 Driver app redirect via its custom URL scheme
**Context:** The driver app signs in through the system browser (auth code + PKCE) and must receive the code back. Django's redirect response only allows http/https/ftp, so the `corridor-driver://auth/callback` redirect was blocked. Driver sign-in never completed, and the end-to-end check caught it. **Choice:** the local issuer allows exactly the `corridor-driver` scheme, and only for targets already matching the redirect allowlist (regression test added). With Cognito, the same URI must be registered as the driver-mobile app client's callback URL. **Trade-off:** custom schemes can in principle be claimed by another app on the device. PKCE prevents a stolen code from being exchanged. Android App Links (verified https) can replace the scheme before release.

## D-049 Driver app unit tests with `node --test`
**Choice:** pure logic (session expiry, refresh, error mapping) lives in React Native-free modules and is tested with Node 24's built-in runner, which runs TypeScript natively. Node types are referenced only from test files (TypeScript 6 no longer loads `@types/*` by default), so app code cannot use Node APIs that do not exist on phones. Component and device tests (Jest/Detox) arrive in Phase 5. **Trade-off:** no UI tests for the sign-in screen yet.

## D-050 No package managers in the web runtime image
**Context:** The CI Trivy scan of `corridor-web:dev` failed on 6 HIGH CVEs (undici 6.28.0: CVE-2026-87018, CVE-2026-19534, CVE-2026-109869, CVE-2026-109383; brace-expansion 5.0.9: CVE-2026-102278, CVE-2026-102276). Both sit inside **npm**, which the official `node:24.22.3-alpine` image bundles. Our own dependencies use fixed versions and none ships in the standalone output. **Choice:** the runtime stage deletes npm, npx, corepack and yarn. It only runs `node server.js`, and the build stages keep npm. A remote Trivy scan of the base image with those directories excluded reports 0 HIGH/CRITICAL findings. **Trade-off:** no `npm` inside the running container for debugging (use the build stage image instead). The CI step "Report scan findings as annotations" makes any future scan failure readable from the public API.

## D-051 Outbox relay on its own database role
**Context:** The relay must read unpublished business events of *every* tenant, but RLS hides other tenants from the app role, and no role may bypass RLS. **Choice:** a `relay` database alias logs in as `corridor_relay`, which has one `relay_all` policy on `outbox_events`: SELECT, plus UPDATE of `published_at` and `attempts` only. It has no access to any other table (tested) and no BYPASSRLS. The relay runs from beat every 5 s with `FOR UPDATE SKIP LOCKED`, publishes to SQS through Celery, and marks a row published only after the broker accepted it. Events of rolled-back transactions never exist (tested). Settings require `RELAY_DATABASE_URL` in staging/production. **Trade-off:** one more credential in Secrets Manager, and up to ~5 s latency for business events (GPS never uses the outbox).

## D-052 Trip assignments owned by trips; dispatch orchestrates
**Context:** The brief lists `trip_assignments` under dispatch, but every trip transition (start, pause, complete, release) needs the active assignment, which would make `trips` and `dispatch` import each other's internals. **Choice:** the `trips` module owns `trips`, `trip_shipments`, `trip_assignments` and `trip_events`. The `dispatch` module is the orchestration API (`POST /dispatch`: create a trip, assign vehicle and driver, and dispatch its shipments in one transaction, all or nothing; tested). Conflicting assignments are stopped by partial unique indexes (vehicle, driver, trailer, trip: one active each). The concurrent race has exactly one winner, and the loser gets 409 `assignment_conflict` (tested with two real threads). **Trade-off:** `dispatch` is a thin module.

## D-053 Cursor pagination on every list
**Choice:** keyset pagination on `(created_at DESC, id DESC)` with an opaque cursor; `limit` defaults to 50, max 200. Stable under concurrent inserts, with no OFFSET scans. **Trade-off:** no "jump to page N" (not needed by any screen).

## D-054 License lookup hash ignores case, spaces and punctuation
**Context:** The duplicate-license check compares keyed hashes without decrypting. "ET-123456", "et 123456" and "ET123456" are the same license and must collide. A test caught that the first version treated them as different. **Choice:** the hash input is upper-cased with every non-alphanumeric character removed; the encrypted value keeps the formatting as entered. **Trade-off:** none.

## D-055 Delivery in Phase 3 needs status + recipient; evidence in Phase 6
**Choice:** `deliver_shipment` is allowed only from `in_transit` (premature delivery from draft, confirmed, dispatched or at_border is rejected; tested), only when a trip carrying the shipment has started, and only by `delivery.confirm` holders. A driver can deliver only shipments on their own trips. It records the recipient name and time and releases the containers. Photo, signature and location evidence (the `delivery` module) arrive in Phase 6 and will become required then. **Trade-off:** until Phase 6, a delivery has no photo or signature evidence.

## D-056 Ops screens use server actions with per-form idempotency keys
**Choice:** the operations screens are server-rendered pages. Forms post to Next.js server actions that call the API with the user's session, and work without client JavaScript. Each rendered form carries a fresh `Idempotency-Key`, so a double click or resubmit replays the first result (tested over HTTP: one form submitted twice creates one customer). API errors come back as `?error=<code>&ref=<request id>` and are shown on the page. Which action buttons appear mirrors the state machine and the user's permissions (unit-tested), but the API stays the authority. **Trade-off:** full page reloads instead of in-place updates, which is acceptable for back-office forms.

## D-057 GPS device bound to the tracking session by the first upload
**Context:** A tracking session opens when the trip starts. That may be done by a dispatcher on the driver's behalf, who does not know the phone's install id. **Choice:** the session's `device_id` is set by the first accepted upload; later uploads from any other device are rejected with `device_mismatch` (tested). Together with "only the assigned driver's account may ingest", this stops a second phone, or another user, from writing into a trip. **Trade-off:** a driver who changes phones mid-trip needs a new session (end and restart, or an office action in a later phase).

## D-058 Partition maintenance and retention via narrow SECURITY DEFINER functions
**Context:** Creating and dropping partitions needs table ownership, which no runtime role has (D-007), and dropping deletes data, which needs approval (MASTER_PROMPT §0.3). **Choice:** `gps_ensure_partitions`, `gps_partitions`, `gps_partition_export`, `gps_drop_partition` and `gps_create_month_partition` are owned by `corridor_owner` and executable only by `corridor_relay`. Each validates its input: the export and the drop refuse any partition inside the retention window. Every partition (and the default) has forced RLS, the tenant policy, and an owner-only read policy for the export. The daily beat job creates partitions 12 months back to 3 months ahead, exports expired partitions to the archive (gzip JSON lines + manifest with row count and SHA-256), re-verifies the archive, and drops only if `GPS_RETENTION_DROP_ENABLED=true`. Otherwise it logs `gps_partition_drop_pending_approval`. The S3 archive adapter needs credentials (Phase 7). **Found while testing:** without the owner read policy, FORCE RLS made the export return 0 rows. Archives would have been empty, which is why the verify step exists. **Trade-off:** one extra policy on GPS tables, readable only by the NOLOGIN owner role.

## D-059 Live map polls a same-origin feed every 5 s (WebSocket push server-side)
**Context:** The browser never holds the access token (HttpOnly cookie, D-006), so it cannot authenticate the `/ws/v1/tracking/` socket directly. **Choice:** the API pushes every newly trusted position to the tenant's fleet group right after commit (measured: 16 ms in tests, immediate on the live stack). The web map polls `/ops/map/fleet` (a server route that calls the API with the cookie) every 5 s, so a position is visible within receipt + 5 s, inside the 10 s target. If polls stop succeeding, the map shows a banner and keeps ageing the positions; it never shows them as live. **Revisit:** a short-lived, single-use WebSocket ticket endpoint to switch the browser to push.

## D-060 Development basemap: MapLibre demo tiles, configurable
**Choice:** `NEXT_PUBLIC_MAP_STYLE_URL` selects the style. The development default is MapLibre's public demo style (low detail, intended for demos). The map labels it as development tiles. Production points it at the self-hosted PMTiles style (D-028); OpenStreetMap's public tile servers are not used. **Trade-off:** low-detail basemap until Phase 7.

## D-061 GPS validation limits
**Choice (tenant-independent):** reject coordinates outside ±90/±180 and (0, 0); reject accuracy outside 0–100 km; reject timestamps without a timezone, more than 5 min in the future, or older than the 12-month retention window; reject without an authorized session, on vehicle or device mismatch, and on reused event ids. Flag (stored, never the latest) accuracy over 100 m, out-of-order points (recorded at or before the current latest), implied speed over 150 km/h, and clocks ahead by more than 60 s. Informational flags: while paused, uploaded more than 1 h late, network (non-GPS) fix. A closed session accepts late uploads for 24 h, only for points recorded while it was open (D-013). **Trade-off:** fixed limits; tenant-tunable later if pilots need it.

## D-062 Offline core as plain TypeScript over a SQL interface
**Choice:** the queue (`LocationQueue`) and sync engine (`SyncEngine`) have no React Native imports. They depend on a 4-method `SqlDb` interface (`exec`, `run`, `all`, `transaction`) implemented by expo-sqlite on the phone and by Node 24's built-in `node:sqlite` in tests (the same SQLite engine). Tests use a file database to prove restarts, and a fake server with switchable failures. `scripts/sync-against-api.mts` runs the same classes against a real API. **Trade-off:** constructor parameter properties are avoided, since Node's type stripping cannot run them.

## D-063 Capture cadence and on-device thinning
**Choice:** the OS is asked for a fix every 20 s (high accuracy, foreground service on Android). On the device, a fix is kept when it is the first, when moving (≥ 2 m/s), when the truck moved ≥ 25 m, or as a stationary heartbeat every 2 min (the brief's 15–30 s moving and 1–3 min stationary). Each kept fix is saved to SQLite before any upload attempt; uploads are attempted after captures, on reconnect and every 5 s while the app is open, with backoff after failures. **Trade-off:** fixed values until device tests (D3, D4, D15) show the battery cost.

## D-064 Mock-location fixes are never recorded
**Choice:** fixes with `mocked: true` (Android mock-location providers) are dropped before they are queued, and the status card warns the driver. A faked truck position is worse than a gap. **Trade-off:** testers must use emulator route playback (which may be marked mocked on some images) with care; see the device test plan.

## D-065 Malformed batches are bisected; 401 pauses uploads
**Choice:** a whole-batch 422 (malformed request) is split in halves until the offending event is isolated and marked `invalid_payload` locally; the rest still uploads. 401/403 sets "Sign-in needed" and pauses uploads (events stay queued) until sign-in succeeds. Network errors and 5xx retry with exponential backoff (2 s → 5 min, ±20 % jitter). Server-rejected events are kept, marked, and never resent. **Trade-off:** none known.

## D-066 Driver app navigation without Expo Router (for now)
**Context:** the project's `AGENTS.md` recommends Expo Router. **Choice:** the driver app has two states (signed out, trips screen) and keeps simple state-based rendering. Expo Router will be introduced when delivery confirmation, photos and checkpoints add screens (Phase 6). **Trade-off:** a later refactor of `App.tsx`.
