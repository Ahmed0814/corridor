# Security model

## 1. Assets and threats

| Asset | Main threats | Primary controls |
|---|---|---|
| Tenant business data (shipments, customers, documents) | Cross-tenant read/write through IDOR, a missing filter, a manipulated `tenant_id`, or a bug in a background job | Server-derived tenant context, RLS with `FORCE`, scoped managers, 404 on foreign ids, security test suite run as the app role |
| Driver location and personal data (phone, license) | Over-collection, tracking outside a trip, exposure to customers | Tracking only inside a trip session, consent recorded, customers see trip position only during an active shipment, app-level encryption of license numbers, field allowlists on public links |
| GPS integrity | Spoofed or replayed points, an old point overwriting a new one, a stale point shown as live | Device-bound sessions, validation flags, a conditional latest-location upsert, freshness computed at read time |
| Lifecycle integrity (dispatch, delivery, customs clearance) | Unauthorized or duplicate transitions, races, retroactive edits | Explicit transition services, `FOR UPDATE` and partial unique indexes, append-only events, clearance only by an authorized human or integration |
| Credentials and secrets | Leaks in the repo, logs or images | Secrets Manager, gitleaks in CI, no secrets in committed env files, structlog redaction processor |
| Public tracking links | Guessing, sharing beyond intent, data over-exposure | 256-bit random tokens, stored hashed, expiry, revocation, allowlisted fields, IP rate limits |

## 2. Identity (Amazon Cognito)

- **One user pool, three app clients** (D-006): `web-office` (email sign-in, auth-code + PKCE), `web-portal` (customers, email), and `driver-mobile` (phone number as username, auth-code + PKCE via the system browser with `expo-auth-session`). Django accepts only tokens whose `client_id` is in the allowlist for the route group in use.
- Django verifies the **access token**: RS256 signature against cached JWKS, `iss`, `token_use = access`, `client_id`, and `exp` with 60 s leeway. The user is mapped by `sub` → `users.cognito_sub`. Roles come from `tenant_memberships`, **never from Cognito groups or token claims** (hard rule 2).
- **MFA for privileged roles** (Owner, Admin, Finance, Super Admin): the pool has MFA set to *optional* with TOTP enabled (no SMS cost or dependency). Server-side enforcement: a membership whose role has `requires_mfa` is treated as having **no permissions** until `users.mfa_verified_at` is set. The flag is set once Cognito confirms TOTP is the user's active MFA (a post-authentication trigger or an `AdminGetUser` check). The UI forces TOTP enrollment before anything else is shown (D-006).
- **Driver login**: phone number + password in the pilot. SMS OTP needs an SMS sender with deliverability to +253/+251 numbers and is listed under "Needs credentials".
- Web tokens: the Next.js server routes complete the code exchange and keep tokens in `HttpOnly; Secure; SameSite=Lax` cookies. The browser never sees refresh tokens. Mobile: tokens in `expo-secure-store` (Keystore/Keychain).
- Suspension: suspending a user or membership takes effect on the next request (memberships are checked on every request). Cognito global sign-out revokes refresh tokens.

## 3. Authorization

### 3.1 Request context
Middleware resolves `RequestContext(user, tenant, membership, role, permissions, customer_id, driver_id)` (see `docs/architecture/overview.md` §4.1). Every Ninja operation declares the permission it needs. A test enumerates all routes and fails if any route lacks a permission declaration, unless it is explicitly marked `public`.

### 3.2 Role → permission matrix (pilot defaults)

Generated from `backend/corridor/identity/permissions.py`, the single source of truth (D-008). The
database tables `roles`, `permissions` and `role_permissions` mirror it after every `migrate`, and a
test fails if this table, the database or the code disagree. A permission held by a Driver or a
Customer is further narrowed by their scope (§3.3): for example `shipments.read` means "assigned
shipments only" for a driver and "own shipments only" for a customer. Owner, Admin and Finance hold
**no** permissions until MFA is verified (§2).

<!-- BEGIN GENERATED PERMISSION MATRIX (backend/scripts/gen_permission_matrix.py) -->
| Permission | Company Owner | Company Admin | Operations Manager | Dispatcher | Fleet Manager | Finance Officer | Driver | Customer |
|---|---|---|---|---|---|---|---|---|
| `tenant.read` Read the company profile | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `tenant.settings` Change company profile and settings | ✓ | ✓ | – | – | – | – | – | – |
| `users.manage` Invite, suspend and reactivate members | ✓ | ✓ | – | – | – | – | – | – |
| `roles.assign` Change a member's role | ✓ | ✓ | – | – | – | – | – | – |
| `audit.read` Read the company audit log | ✓ | ✓ | – | – | – | – | – | – |
| `customers.read` Read customers | ✓ | ✓ | ✓ | ✓ | – | ✓ | – | ✓ |
| `customers.write` Create and edit customers | ✓ | ✓ | ✓ | – | – | – | – | – |
| `containers.read` Read containers | ✓ | ✓ | ✓ | ✓ | ✓ | – | – | ✓ |
| `containers.write` Create and edit containers | ✓ | ✓ | ✓ | ✓ | – | – | – | – |
| `shipments.read` Read shipments | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `shipments.write` Create and edit shipments | ✓ | ✓ | ✓ | ✓ | – | – | – | – |
| `shipments.dispatch` Dispatch shipments | ✓ | ✓ | ✓ | ✓ | – | – | – | – |
| `shipments.confirm_clearance` Confirm border/customs clearance | ✓ | ✓ | ✓ | – | – | – | – | – |
| `shipments.correct` Record corrections on shipments | ✓ | ✓ | – | – | – | – | – | – |
| `trips.assign` Assign vehicles and drivers to trips | ✓ | ✓ | ✓ | ✓ | – | – | – | – |
| `trips.start` Start trips | ✓ | ✓ | ✓ | ✓ | – | – | ✓ | – |
| `trips.pause` Pause and resume trips | ✓ | ✓ | ✓ | ✓ | – | – | ✓ | – |
| `trips.complete` Complete trips | ✓ | ✓ | ✓ | ✓ | – | – | ✓ | – |
| `trips.act_on_behalf` Start/pause/complete a trip on behalf of its driver (reason required) | ✓ | ✓ | ✓ | ✓ | – | – | – | – |
| `trips.correct` Record corrections on trips | ✓ | ✓ | – | – | – | – | – | – |
| `fleet.read` Read vehicles, trailers and GPS devices | ✓ | ✓ | ✓ | ✓ | ✓ | – | ✓ | – |
| `fleet.write` Manage vehicles, trailers and GPS devices | ✓ | ✓ | – | – | ✓ | – | – | – |
| `drivers.read` Read driver profiles | ✓ | ✓ | ✓ | ✓ | ✓ | – | ✓ | – |
| `drivers.write` Manage driver profiles | ✓ | ✓ | – | – | ✓ | – | – | – |
| `drivers.pii` See driver personal data (license number, phone) | ✓ | ✓ | – | – | ✓ | – | – | – |
| `tracking.ingest` Send GPS locations for an own tracking session | – | – | – | – | – | – | ✓ | – |
| `tracking.read` See live and historical locations | ✓ | ✓ | ✓ | ✓ | ✓ | – | ✓ | ✓ |
| `tracking_links.create` Create public tracking links | ✓ | ✓ | ✓ | ✓ | – | – | – | – |
| `tracking_links.revoke` Revoke public tracking links | ✓ | ✓ | ✓ | ✓ | – | – | – | – |
| `delivery.confirm` Confirm or fail a delivery | ✓ | ✓ | ✓ | – | – | – | ✓ | – |
| `documents.read` Read documents | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `documents.upload` Upload documents | ✓ | ✓ | ✓ | ✓ | – | – | ✓ | – |

| Role | MFA required | Scope | App clients |
|---|---|---|---|
| Company Owner (`owner`) | yes | tenant | web-office |
| Company Admin (`admin`) | yes | tenant | web-office |
| Operations Manager (`ops_manager`) | no | tenant | web-office |
| Dispatcher (`dispatcher`) | no | tenant | web-office |
| Fleet Manager (`fleet_manager`) | no | tenant | web-office |
| Finance Officer (`finance`) | yes | tenant | web-office |
| Driver (`driver`) | no | driver | driver-mobile |
| Customer (`customer`) | no | customer | web-portal |
<!-- END GENERATED PERMISSION MATRIX -->

Rules enforced in code beyond the matrix: only an Owner can grant, change or suspend an Owner; nobody
changes their own membership; a company always keeps at least one active Owner.

### 3.3 Scope rules beyond the tenant
- **Customer**: every query goes through `shipments.services.visible_shipments(ctx)`, which adds `customer_id = ctx.customer_id`. Other customers' shipments in the same tenant return 404.
- **Driver**: only trips with an active or past assignment for `ctx.driver_id`. Ingestion checks `session.driver_id == ctx.driver_id` and that the device matches the registered device.
- **Foreign ids**: lookups always go through the tenant-scoped manager, so an id from another tenant (or another customer) raises `NotFound` → 404, never 403.

## 4. Database-level isolation

### 4.1 Roles (D-007)

| Role | Owns tables | BYPASSRLS | Used by |
|---|---|---|---|
| `corridor_owner` | yes | no (NOLOGIN) | owns schema objects |
| `corridor_migrator` | member of `corridor_owner` | no | `manage.py migrate` only (one-off CI/CD task) |
| `corridor_app` | no | **no** | api, realtime, worker (regular tasks) |
| `corridor_relay` | no | no | outbox relay and partition/retention jobs; narrow cross-tenant policy on `outbox_events` only |
| `corridor_platform` | no | no | Platform Super Admin path; its own `platform_read` policies on selected tables; every query audited |

Tests connect as `corridor_app`. A dedicated test asserts `rolbypassrls = false`, `rolsuper = false`, and that `corridor_app` owns no table.

### 4.2 Tenant context
- `SET LOCAL app.tenant_id` (and `app.user_sub`) runs inside the request transaction (`ATOMIC_REQUESTS = True`, plus explicit `atomic()` in async views). `SET LOCAL` disappears at commit or rollback, so pooled connections cannot leak context.
- **Never** session-level `SET`. A test greps the codebase and rejects `SET app.` without `LOCAL`.
- **Celery**: tasks carry `tenant_id` from server-side state (an outbox row), never from user input. A `@tenant_task` decorator wraps execution in `tenant_context(tenant_id)` → `atomic()` → `SET LOCAL`.
- **Channels**: the consumer authenticates on connect (token in the first message or `Sec-WebSocket-Protocol`, never in the URL query, which ends up in logs) and resolves the membership. Each DB access runs through `database_sync_to_async` + `tenant_context`.
- **Memberships special case**: `tenant_memberships` has a second permissive policy allowing rows where `user_id` matches the user resolved from `app.user_sub`, so middleware can list *its own* memberships before a tenant is chosen.

### 4.3 Defence in depth
1. The scoped default manager (`TenantOwnedModel.objects`) filters by the context tenant and **raises** if no context is set. An unscoped manager exists only on the platform path.
2. RLS policies are the backstop if application filtering is wrong.
3. Grants make event and audit tables append-only.
4. The security test suite (Phase 2) tries every tenant-owned endpoint with foreign ids, a manipulated body `tenant_id`, another tenant's token and a tenant-switch header, and runs raw SQL as `corridor_app` without context.

## 5. Realtime authorization

Group names are built server-side only:
- `t.{tenant_id}.fleet`: all vehicle locations in a tenant (roles with `tracking.read`)
- `t.{tenant_id}.shipment.{shipment_id}`: customer and portal views
- `t.{tenant_id}.user.{user_id}`: in-app notifications

A client sends `{"action":"subscribe","topic":"shipment","id":"…"}`. The consumer checks via `shipments.services` that the shipment is visible to this context, and only then joins the group. Requests for other tenants or invisible shipments get a generic `not_found` that does not reveal whether the resource exists. Membership is re-checked every 15 minutes, and the socket closes on suspension.

## 6. Public tracking links (D-017)

- Token: `secrets.token_urlsafe(32)` (256 bits). Only `sha256(token)` is stored. The plaintext is shown once to the creator.
- Fields: `expires_at` (default 30 days, max 90), `revoked_at`, and `allowed_fields` (allowlist: status, ETA, coarse position, timeline labels; never driver name or phone, and never vehicle plate unless the tenant enables it).
- Resolution: the API hashes the token and calls `public_resolve_tracking_link(hash)`, a `SECURITY DEFINER` function owned by `corridor_owner`. It returns only `(tenant_id, shipment_id, allowed_fields)` for a live link. The API then sets tenant context and builds the allowlisted response.
- Position is shown only while the shipment is in transit. It is rounded (default 0.01°, about 1 km) unless the tenant allows exact positions. Responses are `Cache-Control: no-store`. The endpoint has a per-IP rate limit and returns a uniform 404 for invalid, expired and revoked links.

## 7. Data protection

- PII inventory: user email and phone, driver name, phone, license number and photo, recipient name and signature, and GPS traces (personal data while linked to a driver).
- License numbers are encrypted at app level (key from Secrets Manager, with rotation support) (D-019). RDS storage, S3 (SSE-KMS) and backups are encrypted at rest. TLS everywhere, including `sslmode=verify-full` to RDS.
- Driver GPS is collected only during an active trip session, never off shift. Consent is recorded per driver with a timestamp.
- Retention: raw GPS 12 months, then archive (tenant-scoped S3 prefixes). Audit logs 24 months (to confirm). Deleting a driver anonymizes the profile but keeps events with a pseudonymous id.
- Data residency: **unresolved**. See D-003. Must be confirmed with counsel under Djiboutian and Ethiopian data-protection law before any real customer data is loaded.

## 8. Application security baseline
- Ninja input schemas reject unknown fields. `tenant_id` is never declared on input schemas.
- S3 uploads use pre-signed POST with a content-type allowlist (jpeg, png, webp, pdf), a 10 MB size limit and tenant-prefixed keys. Malware scanning is post-pilot. The pilot relies on type sniffing plus the size limit (D-022).
- Django security middleware: HSTS, `SECURE_PROXY_SSL_HEADER` behind the ALB, CSP on the web app, and a CORS allowlist of the web origin only.
- WAF: AWS managed common rule set, IP-reputation list, and rate-based rules on `/api/v1/public/*` and auth paths.
- Logging: structlog processors redact authorization headers, tokens, passwords, phone numbers, license numbers and signature data. GPS coordinates are not logged at INFO.
- Dependencies: pip-audit, npm audit, Trivy on images, Dependabot.

## 9. Audit
`audit_logs` gets a row for: login (first request of a new Cognito session), tenant switch, role or membership change, invitation, suspension, permission-denied on privileged endpoints, public link create and revoke, every platform-admin cross-tenant read, corrections, and border clearance confirmation. Rows are append-only (grants) and include `request_id`, IP and user agent.
