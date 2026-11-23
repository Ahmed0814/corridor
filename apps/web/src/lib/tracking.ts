// Live map types and pure logic (unit-tested). Freshness comes from the API (computed server-side
// from recorded_at and the tenant's thresholds); the client never upgrades a point to "live".

export type Freshness = "live" | "delayed" | "stale" | "offline";

export type VehicleLocation = {
  vehicle_id: string;
  vehicle_plate: string | null;
  trip_id: string | null;
  driver_id: string | null;
  latitude: number;
  longitude: number;
  accuracy_meters: number | null;
  speed: number | null;
  heading: number | null;
  recorded_at: string;
  received_at: string;
  source: string;
  freshness: Freshness;
  age_seconds: number;
  session_active: boolean;
};

export type FleetSnapshot = {
  vehicles: VehicleLocation[];
  thresholds: Record<string, number>;
  generated_at: string;
};

export const POLL_INTERVAL_MS = 5_000;

// Corridor view: Djibouti port to Addis Ababa (lng/lat bounds).
export const CORRIDOR_BOUNDS: [[number, number], [number, number]] = [
  [38.4, 8.6],
  [43.6, 12.0],
];

export const FRESHNESS_COLOR: Record<Freshness, string> = {
  live: "#16a34a",
  delayed: "#d97706",
  stale: "#6b7280",
  offline: "#111827",
};

/**
 * Freshness as displayed now. The API's state is the authority at generation time; while the
 * client keeps showing an older snapshot (e.g. the API is unreachable), the point only ages, so a
 * "live" point is downgraded as time passes. It is never upgraded.
 */
export function displayedFreshness(
  v: Pick<VehicleLocation, "freshness" | "age_seconds" | "session_active">,
  snapshotAgeSeconds: number,
  thresholds: Record<string, number>,
): Freshness {
  if (!v.session_active || v.freshness === "offline") return "offline";
  const age = v.age_seconds + Math.max(0, snapshotAgeSeconds);
  const live = thresholds.freshness_live_seconds ?? 120;
  const delayed = thresholds.freshness_delayed_seconds ?? 600;
  const stale = thresholds.freshness_stale_seconds ?? 3600;
  const order: Freshness[] = ["live", "delayed", "stale", "offline"];
  const byAge: Freshness = age <= live ? "live" : age <= delayed ? "delayed" : age <= stale ? "stale" : "offline";
  return order[Math.max(order.indexOf(v.freshness), order.indexOf(byAge))];
}

/** Seconds since the snapshot was generated, from the client's clock (never negative). */
export function snapshotAge(generatedAt: string, now: Date): number {
  return Math.max(0, Math.floor((now.getTime() - new Date(generatedAt).getTime()) / 1000));
}

/** The map is "out of date" when the last successful poll is older than two intervals. */
export function isFeedStale(lastSuccess: Date | null, now: Date, intervalMs = POLL_INTERVAL_MS): boolean {
  return lastSuccess === null || now.getTime() - lastSuccess.getTime() > 2 * intervalMs;
}

export function formatAge(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return m ? `${h} h ${m} min` : `${h} h`;
}

/**
 * Street map style. OpenFreeMap (OpenStreetMap data, free, no API key) replaces the low-detail
 * MapLibre demo tiles; NEXT_PUBLIC_MAP_STYLE_URL overrides it (production: self-hosted PMTiles, D-028).
 */
export const DEFAULT_MAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";

/** [[west, south], [east, north]] around the given points, padded; null when there are none. */
export function boundsAround(points: { latitude: number; longitude: number }[]): [[number, number], [number, number]] | null {
  if (points.length === 0) return null;
  const lats = points.map((p) => p.latitude);
  const lngs = points.map((p) => p.longitude);
  const pad = 0.05;
  return [
    [Math.min(...lngs) - pad, Math.min(...lats) - pad],
    [Math.max(...lngs) + pad, Math.max(...lats) + pad],
  ];
}
