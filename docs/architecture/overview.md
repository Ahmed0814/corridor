# Architecture overview

Status: Phase 0 design. Nothing here is implemented yet. Fixed decisions come from `MASTER_PROMPT.md` §2. Choices made in this phase are in `DECISIONS.md` and referenced by ID (D-xxx).

## 1. System context

```mermaid
flowchart LR
    subgraph Users
        OPS[Office users<br/>Owner, Admin, Ops Manager,<br/>Dispatcher, Fleet Mgr, Finance]
        CUST[Customer users]
        PUB[Public link holder<br/>no login]
        DRV[Driver<br/>Android first, iOS second]
        SA[Platform Super Admin]
    end

    subgraph Corridor["Corridor platform (one AWS account per environment)"]
        WEB[Next.js web app<br/>ops / portal / admin route groups]
        API[api process<br/>Django + Ninja, ASGI]
        RT[realtime process<br/>Django Channels]
        WK[worker process<br/>Celery]
        BEAT[beat process<br/>celery-beat, exactly 1]
        DB[(PostgreSQL 16 + PostGIS<br/>RLS)]
        REDIS[(Redis<br/>channel layer, rate limits, cache)]
        SQS[[SQS queues + DLQ]]
        S3[(S3<br/>documents, photos, GPS archive, map tiles)]
    end

    COG[Amazon Cognito]
    MAIL[Email provider<br/>Amazon SES, needs credentials]
    SENTRY[Sentry]
    OSRM[OSRM routing<br/>self-hosted, D-016]

    OPS & CUST & SA --> WEB
    PUB --> WEB
    WEB -->|REST /api/v1| API
    WEB -->|WebSocket /ws/v1| RT
    DRV -->|REST, GPS batches| API
    OPS & CUST & DRV & SA -.login.-> COG
    API -.verify JWT via JWKS.-> COG
    RT -.verify JWT via JWKS.-> COG
    API --> DB
    RT --> DB
    WK --> DB
    BEAT --> SQS
    API --> REDIS
    RT <--> REDIS
    WK --> REDIS
    WK <--> SQS
    API --> S3
    WK --> S3
    WK --> MAIL
    API --> OSRM
    API & RT & WK & WEB & DRV -.errors.-> SENTRY
```

## 2. Processes (one Docker image, D-002)

| Process | Command (planned) | Responsibilities | Scale (pilot) |
|---|---|---|---|
| `api` | `gunicorn config.asgi:application -k uvicorn.workers.UvicornWorker` | REST API, GPS ingestion (inline, D-011), file pre-signing, health endpoints | 1–2 tasks |
| `realtime` | `daphne config.asgi:application` (Channels router, WebSocket only) | WebSocket auth, group subscription, fan-out of location and business events | 1 task |
| `worker` | `celery -A config worker` | Outbox event handlers, notifications, geofence/checkpoint evaluation, ETA recompute, retention archive | 1 task |
| `beat` | `celery -A config beat` | Outbox relay tick, freshness sweep, partition maintenance, retention, idempotency-key expiry | exactly 1 task (D-009) |

The brief describes "three processes" and also a separate beat task in the pilot config. Beat is the scheduler, not a fourth service type. It runs from the same image and must be a singleton.

## 3. Module map (Django apps under `backend/corridor/`)

```mermaid
flowchart TB
    subgraph platform[Platform layer]
        core[core<br/>TenantOwnedModel, tenant context,<br/>errors, pagination, idempotency]
        tenants[tenants]
        identity[identity<br/>users, memberships, roles, permissions]
        audit[audit]
        events[events<br/>outbox, relay, dispatcher]
    end
    subgraph logistics[Logistics domain]
        customers
        containers
        shipments
        fleet[fleet<br/>vehicles, trailers, gps_devices, maintenance]
        drivers
        dispatch[dispatch<br/>trip planning, assignments]
        trips[trips<br/>trip lifecycle, trip_events]
        delivery
        documents
    end
    subgraph tracking_layer[Tracking]
        tracking[tracking<br/>sessions, gps events, latest location]
        geofencing[geofencing<br/>geofences, checkpoints, deviation]
        realtime[realtime<br/>Channels consumers, group naming]
    end
    notifications

    logistics --> core
    tracking_layer --> core
    shipments -. services .-> customers
    shipments -. services .-> containers
    dispatch -. services .-> shipments
    dispatch -. services .-> fleet
    dispatch -. services .-> drivers
    dispatch -. services .-> trips
    tracking -. services .-> trips
    geofencing -. services .-> tracking
    delivery -. services .-> trips
    delivery -. services .-> shipments
    events -. outbox handlers .-> notifications
    events -. outbox handlers .-> realtime
```

Module boundary rules (D-005):
- A module's `models.py` is private. Other modules call its `services.py` functions, which return plain dataclasses or Pydantic DTOs, not model instances.
- Cross-module foreign keys exist at the database level for referential integrity, declared with string references such as `"customers.Customer"`. No ORM traversal across a module boundary (`shipment.customer.name` in shipments code is forbidden). The owning module's service resolves the data.
- Boundaries are enforced in CI with `import-linter` contracts: only `<module>.services` and `<module>.schemas` may be imported from outside the module.

## 4. Key flows

### 4.1 Authenticated request and tenant context (D-006, D-007)

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant MW as Middleware (api)
    participant DB as PostgreSQL (app role)
    C->>MW: Request + Bearer JWT (+ optional X-Tenant-Slug)
    MW->>MW: Verify JWT signature, iss, aud/client_id, exp, token_use (cached JWKS)
    MW->>DB: BEGIN
    MW->>DB: SET LOCAL app.user_sub = '<cognito sub>'
    MW->>DB: SELECT memberships WHERE user = me AND status = active
    Note over MW,DB: RLS on tenant_memberships allows rows where<br/>user matches app.user_sub, so no tenant is needed yet
    MW->>MW: Pick membership: X-Tenant-Slug if user is a member, else default.<br/>Not a member → 404. Suspended tenant or membership → 403.
    MW->>DB: SET LOCAL app.tenant_id = '<membership.tenant_id>'
    MW->>MW: Build RequestContext(user, tenant, role, permissions, customer_id?, driver_id?)
    MW->>DB: handler queries (RLS + scoped managers)
    MW->>DB: COMMIT
    MW-->>C: Response + X-Request-ID
```

The client may name which of its own memberships to act under. It can never supply a tenant id that is trusted. Any `tenant_id` in a request body is ignored by the schemas (they do not declare the field).

### 4.2 GPS batch ingestion (D-011, D-012, D-013)

```mermaid
sequenceDiagram
    autonumber
    participant APP as Driver app
    participant API as api: tracking.services
    participant DB as PostgreSQL
    participant CL as Redis channel layer
    participant RT as realtime consumers
    APP->>API: POST /api/v1/tracking/location/batch (≤ 500 events)
    API->>API: Auth, tenant context, driver identity from membership
    API->>DB: Load active tracking session(s) referenced by the batch
    API->>API: Per event: schema, coordinate range, accuracy, future/old ts,<br/>clock skew, session/trip/vehicle/driver authorization
    API->>API: Order by (device, recorded_at, sequence). Speed check vs previous point
    API->>DB: INSERT ... ON CONFLICT DO NOTHING RETURNING event_id
    Note over API,DB: Rows not returned = duplicates
    API->>DB: UPSERT vehicle_latest_locations<br/>WHERE excluded.recorded_at > current.recorded_at<br/>(only events with no blocking flag)
    API->>DB: COMMIT
    API-->>CL: on_commit: group_send(tenant:{t}:fleet, location.updated)
    CL-->>RT: fan-out to subscribed sockets
    API-->>APP: {accepted:[ids], duplicate:[ids], rejected:[{id, reason}]}
    APP->>APP: Delete accepted + duplicate rows from SQLite. Keep rejected for review
```

Realtime push is a non-critical side effect (`transaction.on_commit`). If Redis is down, the location is still stored and clients catch up by polling `GET /vehicles/{id}/location`.

### 4.3 Business transition (example: dispatch shipment) (D-014)

```mermaid
sequenceDiagram
    autonumber
    participant UI as Dispatcher UI
    participant API as api: shipments.services.dispatch_shipment
    participant DB as PostgreSQL
    participant RELAY as beat: outbox relay
    participant Q as SQS
    participant WK as worker
    UI->>API: POST /shipments/{id}/dispatch, Idempotency-Key: K
    API->>DB: Lookup idempotency_keys(tenant, user, K). Hit → replay stored response
    API->>DB: SELECT shipment FOR UPDATE (RLS-scoped, missing → 404)
    API->>API: Check permission shipments.dispatch, current state = confirmed,<br/>trip assigned with vehicle + driver, no conflicting active assignment
    API->>DB: UPDATE shipment status, INSERT shipment_events, INSERT outbox_events(shipment.dispatched)
    API->>DB: INSERT idempotency_keys(response), COMMIT
    API-->>UI: 200 ShipmentOut
    RELAY->>DB: SELECT unpublished outbox rows FOR UPDATE SKIP LOCKED
    RELAY->>Q: SendMessageBatch
    RELAY->>DB: mark published_at
    Q->>WK: deliver
    WK->>WK: handlers (idempotent by outbox event id): notify customer, push realtime, recompute ETA
```

## 5. Cross-cutting concerns

| Concern | Approach |
|---|---|
| Errors | One envelope: `{"error": {"code", "message", "details", "request_id"}}`. Other tenants' resources return 404 `not_found`. |
| Pagination | Cursor pagination (`?cursor=&limit=`, max 200) on lists. |
| Idempotency | `Idempotency-Key` required on state-changing POSTs. Stored per (tenant, user, key) with a request hash. Same key with a different body returns 422. Expires after 24 h (D-015). |
| Correlation | `X-Request-ID` accepted (if well formed) or generated. Bound into structlog context, Celery task headers and Sentry tags. |
| Time | All timestamps are `timestamptz` in UTC. The UI renders in EAT (UTC+3; Djibouti and Ethiopia share the offset). The Ethiopian calendar is not in the pilot (D-020). |
| Money | `amount_minor BIGINT` + `currency CHAR(3)`. Exponents: DJF 0, ETB 2, USD 2 (ISO 4217) (D-021). |
| i18n | Django `gettext` with `en`, `fr`. Web uses `next-intl` with logical CSS properties so RTL (Arabic) can be added. Mobile uses `i18next`. |
| Rate limits | Redis token buckets keyed by (tenant, user) and by IP for public endpoints. GPS endpoints get their own higher bucket per device. |
| Seed data | `manage.py seed_demo` creates a tenant flagged `is_demo=true` named "DEMO — …". It refuses to run unless `DJANGO_ENV=development`. The UI shows a DEMO banner for demo tenants. |

## 6. GPS freshness model

Freshness is computed from `now() - recorded_at` and session state. It is never stored as a column that could go stale.

| State | Rule | UI |
|---|---|---|
| LIVE | session active and age ≤ 2 min | green, "Live · recorded 14:02:11 · received 14:02:13" |
| DELAYED | ≤ 10 min | amber |
| STALE | ≤ 60 min | grey, "Last seen 37 min ago" |
| OFFLINE | > 60 min or session not active | outlined, "Offline since …" |

Thresholds live in `tenants.settings` with platform defaults. The UI always shows both `recorded_at` and `received_at` (hard rule 3).
