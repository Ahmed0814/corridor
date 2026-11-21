/// <reference types="node" />
// Test-only helpers (never imported by the app): a node:sqlite adapter with the same SqlDb surface as
// the expo-sqlite adapter, a fake ingestion server with switchable failure modes, and a fake clock.
import { DatabaseSync } from "node:sqlite";

import type { Clock, IngestResult, LocationEvent, SqlDb, TransportError } from "./types.ts";

export function nodeDb(path = ":memory:"): SqlDb & { close(): void } {
  const db = new DatabaseSync(path);
  db.exec("PRAGMA journal_mode = WAL;");
  let depth = 0;
  return {
    exec: (sql) => db.exec(sql),
    run: (sql, params = []) => {
      const r = db.prepare(sql).run(...params);
      return { changes: Number(r.changes) };
    },
    all: <T,>(sql: string, params: (string | number | null)[] = []) => db.prepare(sql).all(...params) as T[],
    transaction: <T,>(fn: () => T): T => {
      if (depth > 0) return fn();
      depth += 1;
      db.exec("BEGIN");
      try {
        const out = fn();
        db.exec("COMMIT");
        return out;
      } catch (e) {
        db.exec("ROLLBACK");
        throw e;
      } finally {
        depth -= 1;
      }
    },
    close: () => db.close(),
  };
}

export type Mode = "ok" | "drop" | "lose_response" | "http500" | "http401";

/** Mimics POST /tracking/location/batch: dedupe by (device, event id), ≤ 500 per request. */
export class FakeServer {
  readonly stored = new Map<string, LocationEvent>();
  requests = 0;
  maxBatchSeen = 0;
  mode: Mode = "ok";
  /** Per-request random failure rates for the stress test. */
  dropRate = 0;
  loseRate = 0;
  rejectIds = new Set<string>();
  poisonIds = new Set<string>(); // the whole request is refused with 422 if it contains one

  private readonly random: () => number;

  constructor(random: () => number = Math.random) {
    this.random = random;
  }

  async sendBatch(events: LocationEvent[]): Promise<IngestResult> {
    this.requests += 1;
    if (events.length > 500) throw { kind: "http", status: 422, code: "validation_error" } satisfies TransportError;
    this.maxBatchSeen = Math.max(this.maxBatchSeen, events.length);
    if (this.mode === "drop" || this.random() < this.dropRate) throw { kind: "network", message: "Network request failed" } satisfies TransportError;
    if (this.mode === "http500") throw { kind: "http", status: 500, code: "internal_error" } satisfies TransportError;
    if (this.mode === "http401") throw { kind: "http", status: 401, code: "unauthenticated" } satisfies TransportError;
    if (events.some((e) => this.poisonIds.has(e.event_id))) throw { kind: "http", status: 422, code: "validation_error" } satisfies TransportError;
    const result: IngestResult = { accepted: [], duplicate: [], rejected: [], flagged: {} };
    for (const e of events) {
      const key = `${e.device_id}:${e.event_id}`;
      if (this.rejectIds.has(e.event_id)) result.rejected.push({ event_id: e.event_id, reason: "no_session" });
      else if (this.stored.has(key)) result.duplicate.push(e.event_id);
      else {
        this.stored.set(key, e);
        result.accepted.push(e.event_id);
      }
    }
    // The server committed the batch, but the phone never gets the answer (connection dropped).
    if (this.mode === "lose_response" || this.random() < this.loseRate) throw { kind: "network", message: "socket hang up" } satisfies TransportError;
    return result;
  }
}

export function fakeClock(start = Date.parse("2026-11-21T08:00:00Z")): Clock & { advance(ms: number): void } {
  let t = start;
  return {
    now: () => t,
    sleep: async (ms: number) => {
      t += ms;
    },
    advance: (ms: number) => {
      t += ms;
    },
  };
}

/** Deterministic PRNG so failure patterns are reproducible. */
export function seeded(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let x = s;
    x = Math.imul(x ^ (x >>> 15), x | 1);
    x ^= x + Math.imul(x ^ (x >>> 7), x | 61);
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
  };
}

let counter = 0;
export function makeEvent(i: number, overrides: Partial<LocationEvent> = {}): LocationEvent {
  counter += 1;
  return {
    event_id: `00000000-0000-4000-8000-${String(counter).padStart(12, "0")}`,
    device_id: "device-1",
    trip_id: "trip-1",
    vehicle_id: "vehicle-1",
    sequence_number: i,
    latitude: 11.59 - i * 0.0001,
    longitude: 43.14 - i * 0.0001,
    accuracy_meters: 6,
    speed: 10,
    heading: 240,
    recorded_at: new Date(Date.parse("2026-11-21T06:00:00Z") + i * 1000).toISOString(),
    source: "phone_gps",
    ...overrides,
  };
}
