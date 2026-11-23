// What the driver sees about tracking (MASTER_PROMPT §4.2): tracking active/stopped (from the OS, not
// from what the app asked for), online/offline, synchronising, last successful sync, pending events.
import NetInfo from "@react-native-community/netinfo";
import * as Device from "expo-device";
import * as Location from "expo-location";
import { useCallback, useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { batteryAdvice } from "../offline/policy";
import type { SyncState } from "../offline/sync";
import { isTrackingRunning, openBatterySettings, type PermissionState, permissionState } from "../tracking/control";
import { getEngine, getQueue, onSyncState, syncIfDue } from "../tracking/runtime";
import { handleLocations } from "../tracking/task";

function fmt(ms: number | null): string {
  if (!ms) return "never";
  return new Date(ms).toLocaleString();
}

export function TrackingStatus({ tripActive }: { tripActive: boolean }) {
  const [running, setRunning] = useState(false);
  const [online, setOnline] = useState<boolean | null>(null);
  const [sync, setSync] = useState<SyncState>(() => getEngine().getState());
  const [perm, setPerm] = useState<PermissionState | null>(null);
  const [showBattery, setShowBattery] = useState(false);
  const [providers, setProviders] = useState<Location.LocationProviderStatus | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);

  // While the app is open during a trip, also ask for positions directly. Some phones (Samsung,
  // Tecno, Infinix) delay or stop background updates; this keeps tracking alive on screen.
  useEffect(() => {
    if (!tripActive) return;
    let sub: Location.LocationSubscription | null = null;
    let cancelled = false;
    void Location.watchPositionAsync(
      { accuracy: Location.Accuracy.High, timeInterval: 20_000, distanceInterval: 0 },
      (loc) => {
        if (handleLocations({ locations: [loc] }) > 0) void syncIfDue();
      },
    ).then(
      (s) => {
        if (cancelled) s.remove();
        else sub = s;
      },
      (e: unknown) => getQueue().setMeta("last_task_error", `watch: ${e instanceof Error ? e.message : String(e)}`),
    );
    return () => {
      cancelled = true;
      sub?.remove();
    };
  }, [tripActive]);

  /** One position now, saved and uploaded immediately, with a plain result for the driver. */
  async function sendPositionNow() {
    setTesting(true);
    setTestResult("Getting your position…");
    try {
      const loc = await Promise.race([
        Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High }),
        new Promise<never>((_, reject) => setTimeout(() => reject(new Error("no GPS position within 45 s")), 45_000)),
      ]);
      const kept = handleLocations({ locations: [loc] });
      if (kept === 0) {
        setTestResult(
          getQueue().getMeta("active_trip_id") ? "Position found but not saved (too close in time to the last one)." : "No active trip on this phone: start the trip first.",
        );
        return;
      }
      setTestResult(`Position found (±${Math.round(loc.coords.accuracy ?? 0)} m). Sending…`);
      await syncIfDue(true);
      const st = getEngine().getState();
      setTestResult(
        st.pending === 0 && st.lastError === null
          ? "Sent to the server."
          : `Not sent yet (${st.status}${st.lastError ? `: ${st.lastError}` : ""}). It stays on the phone and is retried.`,
      );
    } catch (e) {
      setTestResult(`Could not get a position: ${e instanceof Error ? e.message : String(e)}. Check that Location is on and try outside.`);
    } finally {
      setTesting(false); // the card refreshes itself every 5 s
    }
  }

  const refresh = useCallback(() => {
    void Promise.all([isTrackingRunning(), permissionState(), Location.getProviderStatusAsync().catch(() => null)]).then(
      ([isRunning, p, prov]) => {
        setRunning(isRunning);
        setPerm(p);
        setProviders(prov);
        setSync(getEngine().getState());
      },
    );
  }, []);

  useEffect(() => {
    const unsubscribeSync = onSyncState(setSync);
    const unsubscribeNet = NetInfo.addEventListener((s) => {
      const isOnline = Boolean(s.isConnected && s.isInternetReachable !== false);
      setOnline(isOnline);
      if (isOnline) void syncIfDue(true); // reconnected: upload the queue now, no backoff wait
    });
    const timer = setInterval(() => {
      refresh();
      void syncIfDue();
    }, 5_000);
    const first = setTimeout(refresh, 0);
    return () => {
      unsubscribeSync();
      unsubscribeNet();
      clearInterval(timer);
      clearTimeout(first);
    };
  }, [refresh]);

  const lastFix = Number(getQueue().getMeta("last_fix_received_at") ?? 0) || null;
  const taskError = getQueue().getMeta("last_task_error");
  const mocked = Number(getQueue().getMeta("mock_location_detected_at") ?? 0) || null;
  const advice = batteryAdvice(Device.manufacturer);
  const stoppedUnexpectedly = tripActive && !running;

  return (
    <View style={styles.card} accessibilityLabel="Tracking status">
      <Row label="Tracking" value={running ? "Active" : "Stopped"} tone={running ? "ok" : tripActive ? "bad" : "muted"} />
      {stoppedUnexpectedly ? (
        <Text style={styles.alert} accessibilityRole="alert">
          Your trip is active but location tracking is not running. Restart tracking below.
        </Text>
      ) : null}
      <Row label="Network" value={online === null ? "…" : online ? "Online" : "Offline"} tone={online ? "ok" : "warn"} />
      <Row label="Upload" value={labelFor(sync.status)} tone={sync.status === "idle" ? "ok" : sync.status === "syncing" ? "muted" : "warn"} />
      <Row label="Last successful sync" value={fmt(sync.lastSuccessAt)} />
      <Row label="Waiting to upload" value={String(sync.pending)} tone={sync.pending > 0 ? "warn" : "muted"} />
      {sync.rejected > 0 ? <Row label="Refused by server" value={String(sync.rejected)} tone="bad" /> : null}
      <Row label="Last GPS fix" value={fmt(lastFix)} tone={tripActive && !lastFix ? "warn" : "muted"} />
      {providers ? (
        <Row
          label="Phone location"
          value={!providers.locationServicesEnabled ? "Off" : providers.gpsAvailable ? "GPS on" : "GPS off (network only)"}
          tone={!providers.locationServicesEnabled ? "bad" : providers.gpsAvailable ? "ok" : "warn"}
        />
      ) : null}
      {taskError ? <Text style={styles.alert}>Location service error: {taskError}</Text> : null}
      {sync.lastError ? <Row label="Last upload error" value={sync.lastError} tone="warn" /> : null}
      {tripActive ? (
        <Pressable onPress={() => void sendPositionNow()} disabled={testing} accessibilityRole="button" style={[styles.testButton, testing && styles.dim]}>
          <Text style={styles.testButtonText}>Send my position now</Text>
        </Pressable>
      ) : null}
      {testResult ? <Text style={styles.result}>{testResult}</Text> : null}
      {perm === "foreground_only" ? (
        <Text style={styles.alert}>Background location is not allowed: tracking stops when the screen is off. Allow “All the time”.</Text>
      ) : null}
      {perm === "denied" ? <Text style={styles.alert}>Location permission is off. Tracking cannot run.</Text> : null}
      {mocked ? <Text style={styles.alert}>A mock-location app was detected. Those positions are not recorded.</Text> : null}
      {sync.status === "auth_required" ? <Text style={styles.alert}>Sign in again to resume uploads. Your locations are kept on the phone.</Text> : null}
      <Pressable onPress={() => setShowBattery((v) => !v)} accessibilityRole="button" style={styles.link}>
        <Text style={styles.linkText}>Keep tracking alive on this phone ({advice.maker})</Text>
      </Pressable>
      {showBattery ? (
        <View>
          {advice.steps.map((s) => (
            <Text key={s} style={styles.step}>
              • {s}
            </Text>
          ))}
          <Pressable onPress={() => void openBatterySettings()} accessibilityRole="button" style={styles.link}>
            <Text style={styles.linkText}>Open battery settings</Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );
}

function labelFor(s: SyncState["status"]): string {
  return { idle: "Up to date", syncing: "Synchronising…", offline: "Waiting for network", auth_required: "Sign-in needed", error: "Retrying" }[s];
}

function Row({ label, value, tone = "muted" }: { label: string; value: string; tone?: "ok" | "warn" | "bad" | "muted" }) {
  return (
    <View style={styles.row}>
      <Text style={styles.label}>{label}</Text>
      <Text style={[styles.value, styles[tone]]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { width: "100%", borderWidth: 1, borderColor: "#ddd", borderRadius: 8, padding: 12, gap: 6 },
  testButton: { backgroundColor: "#1f4fd1", paddingVertical: 10, borderRadius: 8, alignItems: "center", marginTop: 4 },
  testButtonText: { color: "#fff", fontWeight: "600" },
  result: { fontSize: 13, color: "#1f2937" },
  dim: { opacity: 0.5 },
  row: { flexDirection: "row", justifyContent: "space-between", gap: 8 },
  label: { fontSize: 14, color: "#444" },
  value: { fontSize: 14, fontWeight: "600" },
  ok: { color: "#15803d" },
  warn: { color: "#b45309" },
  bad: { color: "#b00020" },
  muted: { color: "#333" },
  alert: { fontSize: 14, color: "#b00020" },
  link: { paddingVertical: 6 },
  linkText: { color: "#1f4fd1", textDecorationLine: "underline", fontSize: 14 },
  step: { fontSize: 13, color: "#333", marginVertical: 2 },
});
