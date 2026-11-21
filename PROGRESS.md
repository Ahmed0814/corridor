# PROGRESS

| Phase | Status | Date |
|---|---|---|
| 0 Discovery & architecture | **Done** (DoD evidence below) | 2026-11-20 |
| 1 Foundation | **Implemented. DoD partially verified**: compose + CI items await a first CI run or Docker (see Phase 1) | 2026-11-21 |
| 2 Security & tenancy | Not started | — |
| 3 Core logistics | Not started | — |
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
| `docker compose up` starts api, realtime, worker, beat, Postgres+PostGIS, Redis and web | **NOT YET VERIFIED** | No Docker on this workstation. The compose file and smoke script are written, and the CI `compose` job runs them, but they have **never run**. Equivalent processes were run natively (below), except worker/beat. |
| CI runs lint, type check, makemigrations --check and tests on every push, and passes | **NOT YET VERIFIED** | The workflow is written, but the repo has no GitHub remote and no commits yet. Every CI command was run locally with the results below. |
| Structured logging works | **Verified locally** | Tests + a live uvicorn process (below) |
| Sentry works | **Verified with an in-memory transport** | No real DSN exists (Needs credentials). Capture, request_id tag, scrubbing and data policy are tested. |

Phase 1 closes when the first CI run on GitHub is green (backend, web, mobile, secrets, compose).

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
- Mobile lint (`expo lint`) is not configured yet (its first run is interactive). To be added in Phase 5 along with mobile tests and Sentry for React Native.

---

## Open issues
1. **Docker is not installed** on this workstation. Mitigated by D-032 (portable Postgres/PostGIS/Redis for local tests) and the CI compose job. **Action for human:** create a GitHub repository and push (closes Phase 1), or install Docker Desktop with WSL2 to run `docker compose up` locally.
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
