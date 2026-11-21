// Pure tracking policy (unit-tested): which GPS fixes to keep, how to turn a fix into an event, and
// battery-optimisation guidance per phone maker. MASTER_PROMPT §4.2.
import type { LocationEvent } from "./types";

/** A GPS fix as produced by expo-location (subset of LocationObject). */
export type Fix = {
  latitude: number;
  longitude: number;
  accuracy: number | null;
  speed: number | null;
  heading: number | null;
  timestamp: number; // ms since epoch (GPS fix time)
  mocked?: boolean;
};

export const TRACKING = {
  /** Requested OS update interval while tracking (moving rate). */
  timeIntervalMs: 20_000,
  /** Keep a fix when the truck moved at least this far since the last kept fix… */
  minDistanceM: 25,
  /** …or when this long passed (stationary heartbeat, 1–3 min per the brief). */
  stationaryIntervalMs: 120_000,
  /** Treat as moving above this speed (m/s ≈ 7 km/h). */
  movingSpeedMps: 2,
} as const;

export function distanceM(a: { latitude: number; longitude: number }, b: { latitude: number; longitude: number }): number {
  const r = 6_371_000;
  const p1 = (a.latitude * Math.PI) / 180;
  const p2 = (b.latitude * Math.PI) / 180;
  const dp = p2 - p1;
  const dl = ((b.longitude - a.longitude) * Math.PI) / 180;
  const h = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * r * Math.asin(Math.sqrt(h));
}

export type Decision = { keep: boolean; reason: "first" | "moving" | "moved" | "heartbeat" | "too_soon" | "mocked" | "older" };

/**
 * Moving: keep every fix the OS delivers (~every 20 s). Stationary: keep one fix every 2 minutes.
 * Fixes from mock-location apps are never recorded (they could fake a truck's position).
 */
export function shouldKeep(last: Fix | null, fix: Fix): Decision {
  if (fix.mocked) return { keep: false, reason: "mocked" };
  if (last === null) return { keep: true, reason: "first" };
  if (fix.timestamp <= last.timestamp) return { keep: false, reason: "older" };
  if ((fix.speed ?? 0) >= TRACKING.movingSpeedMps) return { keep: true, reason: "moving" };
  if (distanceM(last, fix) >= TRACKING.minDistanceM) return { keep: true, reason: "moved" };
  if (fix.timestamp - last.timestamp >= TRACKING.stationaryIntervalMs) return { keep: true, reason: "heartbeat" };
  return { keep: false, reason: "too_soon" };
}

export type TripContext = { tripId: string; vehicleId: string; deviceId: string };

/** Build the API event from a fix. The recorded time is the GPS fix time, not the upload time. */
export function toEvent(fix: Fix, ctx: TripContext, sequence: number, eventId: string): LocationEvent {
  return {
    event_id: eventId,
    device_id: ctx.deviceId,
    trip_id: ctx.tripId,
    vehicle_id: ctx.vehicleId,
    sequence_number: sequence,
    latitude: fix.latitude,
    longitude: fix.longitude,
    accuracy_meters: fix.accuracy,
    speed: fix.speed !== null && fix.speed >= 0 ? fix.speed : null,
    heading: fix.heading !== null && fix.heading >= 0 ? fix.heading : null,
    recorded_at: new Date(fix.timestamp).toISOString(),
    source: "phone_gps",
  };
}

/**
 * What the driver must change so the OS does not kill tracking. Generic Android steps always apply;
 * some makers add their own aggressive killers (see dontkillmyapp.com).
 */
export function batteryAdvice(manufacturer: string | null): { maker: string; steps: string[] } {
  const generic = [
    "Settings → Apps → Corridor Driver → Battery → Unrestricted (or 'Don't optimise').",
    "Keep the Corridor notification visible while on a trip; do not swipe the app away.",
  ];
  const m = (manufacturer ?? "").toLowerCase();
  if (/(tecno|infinix|itel|transsion)/.test(m))
    return { maker: "Tecno/Infinix/itel", steps: [...generic, "Phone Master → App auto-start: allow Corridor Driver.", "Phone Master → Power saving: exclude Corridor Driver."] };
  if (/samsung/.test(m))
    return { maker: "Samsung", steps: [...generic, "Settings → Battery → Background usage limits: remove Corridor Driver from 'Sleeping apps' and 'Deep sleeping apps'."] };
  if (/(xiaomi|redmi|poco)/.test(m))
    return { maker: "Xiaomi", steps: [...generic, "Settings → Apps → Corridor Driver → Autostart: on.", "Battery saver → No restrictions."] };
  if (/(huawei|honor)/.test(m))
    return { maker: "Huawei/Honor", steps: [...generic, "Battery → App launch → Corridor Driver: Manage manually, allow all three switches."] };
  if (/(oppo|realme|oneplus)/.test(m))
    return { maker: "Oppo/Realme/OnePlus", steps: [...generic, "Battery → Allow background activity / auto-launch for Corridor Driver."] };
  return { maker: manufacturer ?? "Android", steps: generic };
}
