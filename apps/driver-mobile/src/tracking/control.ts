// Start/stop background tracking for the driver's active trip, and report the TRUE tracking state.
// Never pretend background GPS is running when the OS has stopped it (MASTER_PROMPT §4.2): the status
// always comes from Location.hasStartedLocationUpdatesAsync, not from what the app last asked for.
import * as Crypto from "expo-crypto";
import * as IntentLauncher from "expo-intent-launcher";
import * as Location from "expo-location";
import { Platform } from "react-native";

import { TRACKING } from "../offline/policy";
import { getQueue } from "./runtime";
import { LOCATION_TASK } from "./task";

export type PermissionState = "granted" | "foreground_only" | "denied";

export function deviceId(): string {
  const q = getQueue();
  let id = q.getMeta("device_id");
  if (!id) {
    id = Crypto.randomUUID(); // one install = one device id (bound to the session server-side)
    q.setMeta("device_id", id);
  }
  return id;
}

export async function permissionState(): Promise<PermissionState> {
  const fg = await Location.getForegroundPermissionsAsync();
  if (!fg.granted) return "denied";
  const bg = await Location.getBackgroundPermissionsAsync();
  return bg.granted ? "granted" : "foreground_only";
}

/** Foreground first, then background (Android 11+ opens Settings: the UI explains why beforehand). */
export async function requestPermissions(): Promise<PermissionState> {
  const fg = await Location.requestForegroundPermissionsAsync();
  if (!fg.granted) return "denied";
  const bg = await Location.requestBackgroundPermissionsAsync();
  return bg.granted ? "granted" : "foreground_only";
}

export async function isTrackingRunning(): Promise<boolean> {
  try {
    return await Location.hasStartedLocationUpdatesAsync(LOCATION_TASK);
  } catch {
    return false;
  }
}

export async function startTracking(trip: { tripId: string; vehicleId: string }): Promise<boolean> {
  const q = getQueue();
  q.setMeta("active_trip_id", trip.tripId);
  q.setMeta("active_vehicle_id", trip.vehicleId);
  deviceId();
  await Location.startLocationUpdatesAsync(LOCATION_TASK, {
    accuracy: Location.Accuracy.High,
    timeInterval: TRACKING.timeIntervalMs,
    distanceInterval: 0, // the policy thins stationary fixes; the OS keeps the moving rate
    pausesUpdatesAutomatically: false,
    showsBackgroundLocationIndicator: true,
    activityType: Location.ActivityType.AutomotiveNavigation,
    foregroundService: {
      notificationTitle: "Corridor Driver: trip tracking on",
      notificationBody: "Your location is shared with your company only while this trip is active.",
      notificationColor: "#1f2937",
      killServiceOnDestroy: false,
    },
  });
  return isTrackingRunning();
}

export async function stopTracking(): Promise<void> {
  if (await isTrackingRunning()) await Location.stopLocationUpdatesAsync(LOCATION_TASK);
  const q = getQueue();
  q.setMeta("active_trip_id", null);
  q.setMeta("active_vehicle_id", null);
  q.setMeta("last_kept_fix", null);
}

/** Opens Android's battery-optimisation settings list (the driver exempts the app there). */
export async function openBatterySettings(): Promise<void> {
  if (Platform.OS !== "android") return;
  await IntentLauncher.startActivityAsync(IntentLauncher.ActivityAction.IGNORE_BATTERY_OPTIMIZATION_SETTINGS);
}
