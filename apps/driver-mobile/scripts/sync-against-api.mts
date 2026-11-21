/// <reference types="node" />
// Integration check: the app's own LocationQueue + SyncEngine upload N GPS events to a REAL Corridor
// API through a deliberately unreliable network, then verify nothing was lost or stored twice.
//
//   API_BASE_URL=http://127.0.0.1:8000 DRIVER_TOKEN=... TRIP_ID=... VEHICLE_ID=... \
//     node scripts/sync-against-api.mts [count=10000]
//
// Development/test tenants only (it writes GPS rows). Prints a JSON summary for PROGRESS.md.
import { randomUUID } from "node:crypto";

import { LocationQueue } from "../src/offline/queue.ts";
import { SyncEngine } from "../src/offline/sync.ts";
import { nodeDb, seeded } from "../src/offline/testing.ts";
import type { IngestResult, LocationEvent, Transport, TransportError } from "../src/offline/types.ts";

const API = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";
const TOKEN = process.env.DRIVER_TOKEN ?? "";
const TRIP_ID = process.env.TRIP_ID ?? "";
const VEHICLE_ID = process.env.VEHICLE_ID ?? "";
const COUNT = Number(process.argv[2] ?? 10_000);
const DROP_RATE = Number(process.env.DROP_RATE ?? 0.15);
const LOSE_RATE = Number(process.env.LOSE_RATE ?? 0.15);
if (!TOKEN || !TRIP_ID || !VEHICLE_ID) throw new Error("DRIVER_TOKEN, TRIP_ID and VEHICLE_ID are required");

const random = seeded(7);
const stats = { requests: 0, dropped: 0, responsesLost: 0, accepted: 0, duplicate: 0, rejected: 0, rejectReasons: {} as Record<string, number> };

const realTransport: Transport = {
  async sendBatch(events: LocationEvent[]): Promise<IngestResult> {
    const r = await fetch(`${API}/api/v1/tracking/location/batch`, {
      method: "POST",
      headers: { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" },
      body: JSON.stringify({ events }),
    });
    const body = (await r.json().catch(() => null)) as IngestResult | { error?: { code?: string } } | null;
    if (!r.ok) throw { kind: "http", status: r.status, code: (body as { error?: { code?: string } })?.error?.code ?? null } satisfies TransportError;
    return body as IngestResult;
  },
};

// Unreliable network: some requests never leave the phone; some reach the server (which stores the
// batch) but the response is lost on the way back.
const flaky: Transport = {
  async sendBatch(events) {
    stats.requests += 1;
    if (random() < DROP_RATE) {
      stats.dropped += 1;
      throw { kind: "network", message: "simulated: request dropped" } satisfies TransportError;
    }
    const result = await realTransport.sendBatch(events);
    if (random() < LOSE_RATE) {
      stats.responsesLost += 1;
      throw { kind: "network", message: "simulated: response lost after the server stored the batch" } satisfies TransportError;
    }
    stats.accepted += result.accepted.length;
    stats.duplicate += result.duplicate.length;
    stats.rejected += result.rejected.length;
    for (const x of result.rejected) stats.rejectReasons[x.reason] = (stats.rejectReasons[x.reason] ?? 0) + 1;
    return result;
  },
};

const queue = new LocationQueue(nodeDb(":memory:"));
const clock = { now: () => Date.now(), sleep: async () => {} };
const engine = new SyncEngine(queue, flaky, clock);
const deviceId = randomUUID();

// A plausible track: ~9 m/s north-west from the port of Djibouti, one point per second, ending 60 s ago.
const end = Date.now() - 60_000;
const events: LocationEvent[] = Array.from({ length: COUNT }, (_, i) => ({
  event_id: randomUUID(),
  device_id: deviceId,
  trip_id: TRIP_ID,
  vehicle_id: VEHICLE_ID,
  sequence_number: i + 1,
  latitude: 11.594 + i * 0.00006,
  longitude: 43.148 - i * 0.00006,
  accuracy_meters: 6,
  speed: 9,
  heading: 315,
  recorded_at: new Date(end - (COUNT - 1 - i) * 1000).toISOString(),
  source: "phone_gps",
}));

const t0 = performance.now();
queue.enqueueMany(events);
let rounds = 0;
while (queue.counts().pending > 0 && rounds < 1000) {
  rounds += 1;
  engine.resetBackoff(); // the test does not wait out backoff delays
  await engine.syncOnce();
}
const seconds = (performance.now() - t0) / 1000;
const summary = {
  events: COUNT,
  pendingAfter: queue.counts().pending,
  rejectedLocally: queue.counts().rejected,
  serverAccepted: stats.accepted,
  serverDuplicates: stats.duplicate,
  serverRejected: stats.rejected,
  rejectReasons: stats.rejectReasons,
  requests: stats.requests,
  requestsDropped: stats.dropped,
  responsesLost: stats.responsesLost,
  syncRounds: rounds,
  seconds: Number(seconds.toFixed(1)),
  eventsPerSecond: Math.round(COUNT / seconds),
};
console.log(JSON.stringify(summary, null, 2));
process.exit(summary.pendingAfter === 0 ? 0 : 1);
