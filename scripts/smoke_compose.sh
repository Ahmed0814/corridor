#!/usr/bin/env bash
# Smoke tests against a running `docker compose up` stack (CI and local).
# Proves every Phase 1 process is up and wired: api, realtime, worker, beat, Postgres+PostGIS,
# Redis, the SQS-compatible broker, and web.
set -euo pipefail

API=${API:-http://localhost:8000}
WEB=${WEB:-http://localhost:3000}
fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }

echo "0. waiting for api readiness (up to 300 s)"
for _ in $(seq 1 60); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' "$API/healthz/ready" || true)" = "200" ] && break
  sleep 5
done

echo "1. api liveness"
curl -fsS "$API/healthz/live" | grep -q '"ok"' || fail "api /healthz/live"

echo "2. api readiness (database + redis)"
ready=$(curl -sS -w '\n%{http_code}' "$API/healthz/ready")
[ "$(echo "$ready" | tail -1)" = "200" ] || fail "api /healthz/ready -> $ready"
echo "$ready" | head -1

echo "3. correlation id echoed"
curl -fsS -D - -o /dev/null -H 'X-Request-ID: smoke-test-0001' "$API/api/v1/meta" \
  | grep -qi '^x-request-id: smoke-test-0001' || fail "X-Request-ID not echoed"

echo "4. JSON access log line carries the request id"
sleep 1
docker compose logs api --no-color | grep -F '"request_id": "smoke-test-0001"' | grep -q '"event": "http_request"' \
  || fail "no structured access log line for smoke-test-0001"

echo "5. OpenAPI schema"
curl -fsS "$API/api/v1/openapi.json" | grep -q '"Corridor API"' || fail "openapi.json"

echo "6. PostGIS available to the app"
docker compose exec -T api python manage.py shell -c \
  "from django.db import connection; c=connection.cursor(); c.execute('select postgis_lib_version()'); print('postgis', c.fetchone()[0])" \
  || fail "postgis query"

echo "7. realtime websocket ping/pong"
docker compose exec -T realtime python - <<'PY' || fail "websocket ping"
import asyncio, json, websockets
async def main():
    async with websockets.connect("ws://127.0.0.1:8001/ws/v1/ping/") as ws:
        await ws.send(json.dumps({"type": "ping"}))
        reply = json.loads(await asyncio.wait_for(ws.recv(), 5))
        assert reply == {"type": "pong"}, reply
        print("pong")
asyncio.run(main())
PY

echo "8. beat -> SQS (ElasticMQ) -> worker: waiting for a heartbeat (up to 150 s)"
for _ in $(seq 1 30); do
  if docker compose logs worker --no-color | grep -q '"event": "celery_heartbeat"'; then
    echo "heartbeat received by worker"; break
  fi
  sleep 5
done
docker compose logs worker --no-color | grep -q '"event": "celery_heartbeat"' || fail "no celery_heartbeat in worker logs"

echo "9. web serves the home page and the status page sees the API"
for _ in $(seq 1 30); do curl -fsS -o /dev/null "$WEB/" && break; sleep 5; done
curl -fsS "$WEB/" | grep -q 'Corridor' || fail "web /"
status_page=$(curl -fsS "$WEB/status") || fail "web /status"
# Match the explicit state attribute: message text is always present in the page payload.
echo "$status_page" | grep -q 'data-readiness="ok"' || fail "web /status does not report the API as ready"

echo "ALL SMOKE TESTS PASSED"
