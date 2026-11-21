// Shared types for the offline queue and sync engine (MASTER_PROMPT §4.2). No React Native imports:
// these modules run unchanged on the phone (expo-sqlite) and in Node tests (node:sqlite).

/** One GPS point as the API expects it (POST /api/v1/tracking/location/batch). */
export type LocationEvent = {
  event_id: string;
  device_id: string;
  trip_id: string;
  vehicle_id: string;
  sequence_number: number;
  latitude: number;
  longitude: number;
  accuracy_meters: number | null;
  speed: number | null;
  heading: number | null;
  recorded_at: string; // ISO 8601 with timezone, from the GPS fix time
  source: "phone_gps" | "phone_network";
};

/** The server's acknowledgement: delete accepted + duplicate, keep rejected for review. */
export type IngestResult = {
  accepted: string[];
  duplicate: string[];
  rejected: { event_id: string; reason: string }[];
  flagged: Record<string, string[]>;
};

/** Minimal synchronous SQL surface implemented by expo-sqlite (phone) and node:sqlite (tests). */
export interface SqlDb {
  exec(sql: string): void;
  run(sql: string, params?: (string | number | null)[]): { changes: number };
  all<T>(sql: string, params?: (string | number | null)[]): T[];
  transaction<T>(fn: () => T): T;
}

/** A transport error the sync engine can act on (duck-typed so modules need no runtime imports). */
export type TransportError =
  | { kind: "network"; message: string } // offline, timeout, DNS, connection reset, lost response
  | { kind: "http"; status: number; code: string | null };

export interface Transport {
  sendBatch(events: LocationEvent[]): Promise<IngestResult>;
}

export type Clock = { now(): number; sleep(ms: number): Promise<void> };
