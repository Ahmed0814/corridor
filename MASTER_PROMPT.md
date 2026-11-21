# CORRIDOR — MASTER BUILD PROMPT (FINAL)
## Multi-tenant logistics, container tracking and fleet platform for the Djibouti–Ethiopia corridor

You are a senior engineer building a production-oriented logistics platform. You design, implement, test, secure and document it, phase by phase, from an empty repository to a pilot-ready system.

---

# 0. WORKING RULES (read first, follow always)

1. Work one phase per session. At the start of every session, read this file, PROGRESS.md and DECISIONS.md.
2. A phase is done only when its Definition of Done passes. Paste every test command and its real output into PROGRESS.md. Never mark a test as passing unless it ran and passed.
3. Stop and wait for human approval before:
   - terraform apply in any environment
   - the first production database migration, and any migration that drops or rewrites data
   - anything that sends real SMS, WhatsApp or email
   - any action that exposes real customer data
4. You cannot test on physical phones. Write a device test plan and run emulator/simulator tests. A human runs real-device tests and records results in PROGRESS.md. Production release waits for that sign-off.
5. Integrations that need credentials (SMS, WhatsApp, email, maps, payments) ship as an interface plus a test adapter, listed under "Needs credentials" in PROGRESS.md. That is not a TODO. Never fabricate credentials or claim an integration is live.
6. If a decision is not covered here, choose the simplest safe option, record it in DECISIONS.md (context, choice, trade-off), and continue. Ask only when it affects security, data integrity, cost or irreversible operations.
7. If you hit a blocker, diagnose it, apply the safest available fix, and record any remaining limitation.
8. Preserve existing working features when modifying an existing repository.

## Files you maintain
- PROGRESS.md — phase status, test commands with output, open issues, "Needs credentials", "Needs device testing", "Needs approval".
- DECISIONS.md — one entry per architectural decision.

---

# 1. HARD RULES (never break)

1. Never allow cross-tenant data access.
2. Never trust tenant_id, role or ownership sent from the client. Tenant context comes from authenticated server-side membership.
3. Never present stale GPS as live. Always show the recorded time and the server receipt time.
4. Never let an older GPS event overwrite a newer trusted location.
5. Never overwrite or delete historical events. Corrections are new events with an actor and a reason.
6. Never hardcode credentials, keys or passwords.
7. Never present seed or fake data as real. Seed data is clearly labelled and used only in development.
8. Never treat GPS arrival at a border as customs clearance. Clearance is confirmed by an authorized operator or a trusted integration.
9. AI never dispatches trucks, changes statuses, authorizes deliveries or makes financial decisions, and never invents locations.
10. Never bypass migrations. Never use production data in development tests.
11. Never claim completion without evidence.

---

# 2. FIXED DECISIONS

| Area | Decision |
|---|---|
| Architecture | Modular monolith. One repo, one PostgreSQL database, one Docker image, run as three processes: api (Django ASGI via Uvicorn/Gunicorn), realtime (Django Channels via Daphne or Uvicorn), worker (Celery). No microservices. |
| Module rule | Each Django app is one business module and owns its tables. Modules talk only through a services.py public interface and outbox events. No module imports another module's models directly for writes or queries another module's tables. |
| Backend | Python 3.12, Django 5.x, Django Ninja (typed REST API with Pydantic schemas), GeoDjango, Django migrations |
| Background jobs | Celery with Amazon SQS as broker; celery-beat for scheduled jobs (outbox relay, freshness checks, retention) |
| Realtime | Django Channels (WebSocket) with channels-redis on Amazon ElastiCache Redis (smallest node for the pilot) |
| Database | PostgreSQL 16 + PostGIS on Amazon RDS, Row-Level Security |
| Web | One Next.js + TypeScript + Tailwind + shadcn/ui app, with separate route groups and auth scopes for operations, customer portal and platform admin |
| Maps (web) | MapLibre GL + OpenStreetMap tiles. Routing via OSRM or a provider chosen after testing corridor road coverage; record the choice in DECISIONS.md. |
| Driver app | React Native + Expo (development build, not Expo Go), expo-location + expo-task-manager, expo-sqlite. Android first, iOS second. |
| Auth | Amazon Cognito. Django validates Cognito JWTs and maps users to tenant memberships. Email login for office users, phone-number login for drivers. MFA required for Super Admin, Company Owner, Company Admin, Finance Officer. |
| Infra | Terraform, ECS Fargate, ECR, RDS, ElastiCache Redis, S3, SQS (+ DLQ), CloudWatch, Secrets Manager, ALB, Route 53, CloudFront, WAF. VPC endpoints instead of a NAT Gateway where possible. No Kubernetes. No Kafka. |
| CI/CD | GitHub Actions |
| Error tracking | Sentry (free tier) for backend, web and mobile |
| AWS region | [me-central-1 — confirm data-residency requirements for Djibouti and Ethiopia] |
| Languages | UI in English and French first; use Django i18n and next-intl so Arabic (RTL), Amharic, Afar and Somali can be added. |
| Currencies | DJF, ETB, USD. Store amounts as integer minor units + currency code. |

## Pilot targets
- Tenants: [3]
- Trucks: [up to 300] active
- Drivers: [up to 400]
- Shipments: [up to 2,000 per month]
- Office users online at once: [up to 100]
- Budget: [pilot AWS cost under $X per month — fill in]
- API p95 latency: [< 300 ms] for normal reads
- GPS: an event is visible on the live map within [10 s] of the server receiving it
- RPO [24 h] / RTO [4 h] for the pilot

## GPS freshness thresholds (time since recorded_at)
- LIVE: ≤ [2 min]
- DELAYED: ≤ [10 min]
- STALE: ≤ [60 min]
- OFFLINE: > [60 min] or tracking session not active

## GPS retention
- Raw events kept [12 months] in PostgreSQL (monthly partitions), then archived to S3.

---

# 3. PRODUCT SCOPE

## Pilot scope (build fully)
1. Platform administration: tenants, activation/suspension, platform audit log (Django admin may be used for internal super-admin tools, never for tenant users)
2. Tenant and company management: profile, settings, users, invitations, memberships, roles
3. Identity and access: roles below, granular permissions, multi-company membership, suspension, MFA for privileged roles
4. Customers: profiles, contacts, shipment history, customer-scoped access
5. Containers: number, type, size, owner, condition, availability, movements, inspections
6. Shipments: reference, customer, containers, cargo, origin, destination, weight/dimensions, documents, status, history, ETA
7. Fleet: trucks, trailers, registration, availability, GPS devices, maintenance and inspections
8. Drivers: profiles, license, employment status, device registration, availability, tracking permissions (protect personal data)
9. Trips and dispatch: create, assign shipments/vehicles/drivers, plan route, start, pause, resume, checkpoints, incidents, delays, complete
10. GPS tracking: ingestion, validation, history, latest trusted location, freshness, geofences, checkpoint detection, route deviation
11. Offline driver tracking (critical)
12. Customer tracking link
13. Delivery confirmation: recipient, signature, photos, time, location, failed delivery
14. Notifications: email and in-app

## Post-pilot (design interfaces now, build later)
- Billing, invoices, payments, financial reports (local wallets such as D-Money, Waafi, CAC Pay via a payment interface)
- Analytics and reporting beyond the operations dashboard
- SMS and WhatsApp notifications
- AI logistics intelligence (pilot uses deterministic ETA only; no LLM features yet)
- Hardware telematics devices [in or out — decide]
- Rail / multimodal [in or out — decide]
- Multi-region

## Roles
Platform Super Admin, Company Owner, Company Admin, Operations Manager, Dispatcher, Fleet Manager, Driver, Finance Officer, Customer.

## Modeling rules
- A container is a physical asset.
- A shipment is a cargo movement or customer transaction.
- A trip is an actual journey; one shipment may use several trips.
- A vehicle is a transport asset; a driver is an assigned operator.
- Never merge these into one entity.

---

# 4. CRITICAL SYSTEMS

## 4.1 GPS ingestion
Pipeline: device → authenticate (Cognito JWT) → derive tenant from membership → validate trip and active tracking session → validate event → store history → update latest location → push to realtime via Channels group.

Event fields: event_id, tenant_id, driver_id, vehicle_id, trip_id, device_id, sequence_number, latitude, longitude, accuracy_meters, speed, heading, recorded_at, received_at, source.

Validation: coordinate range, accuracy threshold, future timestamps, old timestamps, duplicates, out-of-order, impossible speed between consecutive points, unauthorized vehicle/driver, invalid or closed trip, device clock skew (compare recorded_at with received_at within a tolerance; prefer GPS fix time).

Storage rules:
- gps_location_events: append-only, native PostgreSQL partitioning by month (created via raw SQL in a Django migration), BRIN index on recorded_at, PostGIS PointField.
- Dedupe key: unique (tenant_id, device_id, event_id). Batch insert with bulk_create(ignore_conflicts=True), then compare returned IDs to classify duplicates.
- Suspicious events are kept with validation flags. Invalid events never update the live location.
- vehicle_latest_locations: conditional update only when valid and recorded_at is newer (UPDATE … WHERE recorded_at < new value, or INSERT … ON CONFLICT DO UPDATE … WHERE).
- High-frequency GPS does NOT go through the outbox. Only business events do (checkpoint reached, deviation detected, session started/stopped).

Batch endpoint response: lists of accepted, duplicate and rejected event IDs (with reasons), so the app clears its queue correctly.

## 4.2 Offline-first driver app
Flow: login → fetch assigned trips → download trip data → start authorized tracking session → capture → save to SQLite (status pending) → try sync → queue on failure → detect reconnection → upload batches → process acknowledgements → retry with backoff → resume after restart → stop when the session ends.

Rules:
- Save every event locally before any network call.
- Delete local events only after the server acknowledges them (accepted or duplicate).
- Tracking frequency (configurable): moving 15–30 s, stationary 1–3 min, important events immediately.
- Android: foreground service with persistent notification; detect and guide the driver through OEM battery-optimization settings.
- Never pretend background GPS is running when the OS has stopped it. Show: tracking active, offline, synchronizing, last successful sync, pending events, tracking stopped.
- Browser geolocation is not acceptable for background tracking.

## 4.3 Lifecycle state machines
Independent state machines for shipment, trip, vehicle, driver assignment, tracking session and delivery. Implement as explicit service functions (e.g., dispatch_shipment(), start_trip()) — no generic "update status" endpoint, no direct status edits in Django admin.

Every transition: check current state → validate business rules → check permission → check tenant ownership → run inside transaction.atomic() with select_for_update() or a conditional update → write an immutable event with actor and timestamp → honour Idempotency-Key.

Prevent: invalid dispatch, unauthorized trip start, duplicate active assignments (also enforced by partial unique constraints), premature delivery, invalid completion, unauthorized reopening, inconsistent shipment/trip statuses.

Corrections: an authorized correction action with a required reason, recorded as a new event.

## 4.4 Multi-tenant security
- Every tenant-owned model inherits a TenantOwnedModel base with tenant FK and a tenant-scoped default manager.
- Every tenant-owned table has an RLS policy based on current_setting('app.tenant_id').
- Tenant context: a middleware resolves the tenant from the authenticated membership, and every request runs in a transaction (ATOMIC_REQUESTS or explicit atomic) that first executes SET LOCAL app.tenant_id. Celery tasks and Channels consumers use the same tenant-context helper. Never set it at session level.
- The application database role does not own tables and does not have BYPASSRLS. Migrations run with a separate migration role.
- Platform Super Admin cross-tenant access uses a separate, audited path.
- Return 404 (not 403) for resources in another tenant.
- Customers see only their own shipments. Drivers see only their own assignments.
- Public tracking links use cryptographically random (secrets.token_urlsafe), revocable, expiring tokens and expose only explicitly allowed fields.
- Tests run as the real application role, not a superuser.

---

# 5. DATA, EVENTS, API

## Core tables
tenants, users, tenant_memberships, roles, permissions, customers, drivers, vehicles, trailers, gps_devices, containers, shipments, shipment_containers, trips, trip_assignments, routes, route_stops, checkpoints, geofences, tracking_sessions, gps_location_events, vehicle_latest_locations, shipment_events, trip_events, delivery_records, documents, notifications, audit_logs, outbox_events, idempotency_keys.
(Post-pilot: invoices, payments.)

Use GeoDjango fields (PointField, PolygonField, LineStringField) with spatial indexes. Keep current status columns for fast queries and append-only event tables for history. All schema changes via Django migrations; RLS policies and partitions via RunSQL migrations.

## Events (transactional outbox)
tenant.created, shipment.created, shipment.confirmed, shipment.dispatched, shipment.delayed, shipment.delivered, trip.created, trip.assigned, trip.started, trip.completed, tracking.session.started, tracking.session.stopped, checkpoint.reached, border.arrived, border.clearance.confirmed, route.deviation.detected.
Events are written to outbox_events in the same transaction as the change. A Celery beat task relays them to SQS; Celery workers process them. Failed jobs go to a DLQ with alarms. Use transaction.on_commit() only for non-critical side effects.

## API (Django Ninja)
Versioned REST under /api/v1. Pydantic schemas for input and output, pagination, one error format, rate limiting (Redis-backed), Cognito JWT authentication, permission checks on every endpoint, Idempotency-Key header on mutations, OpenAPI docs, request correlation IDs. Never expose internal database structures.

Key endpoints:
POST /api/v1/shipments
GET /api/v1/shipments
GET /api/v1/shipments/{id}
POST /api/v1/shipments/{id}/dispatch
POST /api/v1/shipments/{id}/deliver
POST /api/v1/trips/{id}/start
POST /api/v1/trips/{id}/complete
POST /api/v1/tracking/location
POST /api/v1/tracking/location/batch
GET /api/v1/vehicles/{id}/location
GET /api/v1/trips/{id}/locations
GET /api/v1/public/tracking/{token}
WebSocket: /ws/v1/tracking/ (tenant-scoped groups; customers subscribe only to their shipments)

---

# 6. USER INTERFACE

Professional enterprise SaaS look: clear navigation, the design system's type scale only, consistent spacing, responsive, accessible (WCAG AA), searchable/filterable tables, status badges, maps, clear loading/empty/error states.

Screens:
- Company dashboard: active shipments, active trucks, active drivers, live map, delayed shipments, recent events, delivery metrics
- Shipment detail: info, containers, customer, origin/destination, status timeline, trips, GPS track, documents, delivery evidence
- Fleet: vehicles, assignments, availability, maintenance, GPS freshness
- Dispatch: create trip, pick shipment/vehicle/driver, route, status
- Customer portal: progress, map, ETA, timeline, allowed documents, delivery confirmation
- Driver app: login, assigned trips, trip detail, start trip, tracking status, offline status, checkpoints, incidents, photos, delivery confirmation, complete trip
- Platform admin: tenants, users, usage, configuration

Map: Port of Djibouti, Djibouti City, Galafi and Dewele border crossings, Dire Dawa, Addis Ababa. Vehicle markers, route lines, checkpoints, geofences, timestamps, accuracy indicators, ETA, deviation alerts.

---

# 7. INFRASTRUCTURE, CI/CD, OBSERVABILITY

## AWS (Terraform)
VPC with public and private subnets; ALB in public; ECS tasks, RDS and ElastiCache in private; database never public; HTTPS everywhere; least-privilege IAM per ECS service; encryption at rest and in transit; Secrets Manager for all secrets; S3 with versioning and pre-signed URLs; remote Terraform state with locking.
Environments: dev (docker-compose locally), staging, prod.
Two configurations:
- Pilot: 1–2 api tasks, 1 realtime task, 1 worker task, 1 beat task, single-AZ RDS with point-in-time recovery, single small Redis node.
- Production: 2+ tasks per service across two AZs with autoscaling (workers on SQS depth), Multi-AZ RDS, Redis with replica, tested restores.
Explain the purpose and monthly cost of every paid resource before it is applied.

## CI/CD (GitHub Actions)
push → lint (Ruff, ESLint) → type check (mypy + django-stubs, tsc) → unit tests (pytest-django) → integration tests (real Postgres + PostGIS + Redis in service containers) → makemigrations --check → secret scan (gitleaks) → dependency scan (pip-audit, npm audit) → Docker build → Trivy scan → push to ECR → deploy staging → run migrations → smoke tests → manual approval → deploy production → health check.
terraform fmt, validate and plan on every PR; apply only after approval. Never auto-apply destructive changes. Back up before production migrations.

## Observability
Structured JSON logs (structlog) with correlation IDs. Sentry for errors. CloudWatch metrics and alarms for: API latency and errors, DB CPU and connections, GPS ingestion rate, validation failures, stale vehicles, offline drivers, queue depth and age, DLQ messages, failed Celery tasks, notification failures, WebSocket connections.
Health, readiness and liveness endpoints. Separate infrastructure health from business health (e.g., "trucks with no GPS for 30 min").
Runbooks for: database restore, stuck queue, GPS outage, tenant data incident.

---

# 8. TESTING

- GPS: valid, invalid coordinates, low accuracy, duplicate, old, future, out-of-order, impossible speed, unauthorized vehicle, closed trip, stale location, older-event-cannot-overwrite.
- Offline: network loss, local persistence, app restart, interrupted batch, acknowledgements, retry, duplicate prevention, reconnection, 10,000-event queue sync.
- Lifecycle: valid and invalid transitions, unauthorized dispatch, duplicate dispatch, conflicting vehicle/driver assignment, invalid delivery, completed-trip correction, concurrent dispatch race (two threads, one wins).
- Security: cross-tenant access for every tenant-owned resource, manipulated IDs, manipulated tenant_id in body, token from another tenant, tenant switching, role violations, driver and customer scope violations, RLS bypass attempts (raw SQL as app role), WebSocket subscription to another tenant's vehicles, public token revocation.
- Load: k6 or Locust simulating [300] trucks sending batches plus [100] office users; record results in PROGRESS.md.

---

# 9. REPOSITORY

```
corridor-platform/
├── apps/
│   ├── web/                 (Next.js: operations, customer portal, admin)
│   └── driver-mobile/       (Expo)
├── backend/
│   ├── config/              (settings, asgi, celery, urls)
│   ├── corridor/
│   │   ├── core/ tenants/ identity/ customers/ containers/ shipments/
│   │   ├── fleet/ drivers/ dispatch/ trips/ tracking/ geofencing/
│   │   ├── delivery/ documents/ notifications/ events/ audit/ realtime/
│   │   └── (post-pilot) billing/ analytics/ ai/
│   ├── tests/
│   └── manage.py
├── infrastructure/terraform/{modules,environments}
├── docker/
├── docs/{architecture,database,api,security,deployment,runbooks}
├── .github/workflows/
├── PROGRESS.md
├── DECISIONS.md
├── docker-compose.yml
└── README.md
```

Each Django app contains: models.py, services.py (public interface + state transitions), api.py (Ninja router), schemas.py, tasks.py, tests/.

---

# 10. PHASES AND DEFINITION OF DONE

PHASE 0 — Discovery and architecture
Done when: architecture diagram, ERD, security model, deployment diagram and roadmap exist in docs/; DECISIONS.md has an entry for every choice that needed confirming.

PHASE 1 — Foundation
Done when: docker-compose up starts api, realtime, worker, beat, Postgres+PostGIS, Redis and web; CI runs lint, type check, makemigrations --check and tests on every push and passes; structured logging and Sentry work.

PHASE 2 — Security and tenancy
Done when: Cognito login works for web and driver flows; RLS is on every tenant table; the security test suite passes as the app role; a test confirms the app role has no BYPASSRLS and owns no tables; changing tenant_id in a request has no effect; Celery tasks and WebSocket consumers respect tenant context; audit rows exist for login, role change and tenant switch.

PHASE 3 — Core logistics
Done when: customers, containers, shipments, vehicles, drivers, trips and dispatch work end to end; all state machines enforce valid transitions; lifecycle tests pass, including the concurrent dispatch race test.

PHASE 4 — GPS tracking
Done when: single and batch ingestion work; every GPS validation test passes; partitions and retention job work; freshness states display correctly; the live map updates within the target time; older events never overwrite newer ones.

PHASE 5 — Driver app and offline
Done when: emulator tests pass for network loss, restart, interrupted batch and 10,000-event sync; the device test plan is written; a human has signed off real-device tests in PROGRESS.md (Android required, iOS if in scope).

PHASE 6 — Customer and operations
Done when: public tracking links work and are revocable; checkpoints and geofences trigger events; deterministic ETA displays; email and in-app notifications run through Celery without blocking requests; delivery confirmation with photo and signature works.

PHASE 7 — Infrastructure and deployment
Done when: terraform plan is clean for staging; a monthly cost estimate is written; after approval, staging is deployed and smoke tests pass; backup and restore have been tested once.

PHASE 8 — Final verification
Done when: all tests pass; load test results are recorded; security review is written; the final report is complete.

(Post-pilot phases: billing, analytics, SMS/WhatsApp, AI.)

---

# 11. FINAL REPORT

PROGRESS.md ends with:
- What is implemented
- What passed testing (with evidence)
- What failed
- What needs external credentials
- What needs physical device testing
- What needs human approval
- What is safe for a pilot
- What is not yet production-ready

Deliverables: source code, web app, backend API, driver app (EAS build config with credential setup documented), migrations, tests, Docker config, Terraform, CI/CD workflows, OpenAPI docs, architecture diagrams, ERD, security docs, deployment guide, .env.example with no real secrets, backup and recovery guide, pilot testing checklist.
