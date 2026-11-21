// Background location task (expo-task-manager). Must be defined at module load, so index.ts imports
// this file before registering the app: when the OS wakes the app for a location update, no React
// component mounts, only this module runs.
import * as Crypto from "expo-crypto";
import * as TaskManager from "expo-task-manager";

import { type Fix, shouldKeep, toEvent } from "../offline/policy";
import { getQueue, syncIfDue } from "./runtime";

export const LOCATION_TASK = "corridor-location-task";

type LocationPayload = {
  locations?: {
    coords: { latitude: number; longitude: number; accuracy: number | null; speed: number | null; heading: number | null };
    timestamp: number;
    mocked?: boolean;
  }[];
};

/** Save each kept fix locally FIRST, then try to upload (MASTER_PROMPT §4.2). */
export function handleLocations(payload: LocationPayload): number {
  const queue = getQueue();
  const tripId = queue.getMeta("active_trip_id");
  const vehicleId = queue.getMeta("active_vehicle_id");
  const deviceId = queue.getMeta("device_id");
  if (!tripId || !vehicleId || !deviceId) return 0; // no active trip: never record
  const lastRaw = queue.getMeta("last_kept_fix");
  let last: Fix | null = lastRaw ? (JSON.parse(lastRaw) as Fix) : null;
  let kept = 0;
  for (const l of payload.locations ?? []) {
    const fix: Fix = { ...l.coords, timestamp: l.timestamp, mocked: l.mocked };
    const decision = shouldKeep(last, fix);
    if (decision.reason === "mocked") queue.setMeta("mock_location_detected_at", String(Date.now()));
    if (!decision.keep) continue;
    queue.enqueue(toEvent(fix, { tripId, vehicleId, deviceId }, queue.nextSequence(), Crypto.randomUUID()));
    last = fix;
    kept += 1;
  }
  if (last) queue.setMeta("last_kept_fix", JSON.stringify(last));
  queue.setMeta("last_fix_received_at", String(Date.now()));
  return kept;
}

TaskManager.defineTask<LocationPayload>(LOCATION_TASK, async ({ data, error }) => {
  const queue = getQueue();
  if (error) {
    queue.setMeta("last_task_error", error.message);
    return;
  }
  if (handleLocations(data) > 0) await syncIfDue();
});
