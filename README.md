# Corridor

Multi-tenant logistics, container tracking and fleet platform for the Djibouti–Ethiopia corridor.

**Status:** Phase 0 complete. Phase 1 (foundation) implemented; awaiting first CI run. See `PROGRESS.md`. Local setup: `docs/development.md`.

## Start here
- `MASTER_PROMPT.md`: the build brief, with rules, scope and phases
- `PROGRESS.md`: phase status, test evidence, open issues, approvals and credentials needed
- `DECISIONS.md`: architectural decisions (D-001…)

## Design docs
- `docs/architecture/overview.md`: system context, processes, modules, key flows
- `docs/architecture/state-machines.md`: shipment, trip, assignment, tracking session and delivery lifecycles
- `docs/database/erd.md`: ERD, partitioning, RLS
- `docs/security/security-model.md`: identity, authorization, tenant isolation, public links, data protection
- `docs/deployment/deployment.md`: AWS topology, environments, CI/CD
- `docs/roadmap.md`: phases, gates, risks

## Stack (fixed)
Django 5 + Django Ninja + GeoDjango, PostgreSQL 16 + PostGIS with RLS, Celery on SQS, Django Channels on Redis, Next.js + Tailwind + shadcn/ui, React Native + Expo, Amazon Cognito, Terraform on AWS ECS Fargate.
