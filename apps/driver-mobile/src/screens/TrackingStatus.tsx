// What the driver sees about tracking (MASTER_PROMPT §4.2): tracking active/stopped (from the OS, not
// from what the app asked for), online/offline, synchronising, last successful sync, pending events.
import NetInfo from "@react-native-community/netinfo";
import * as Device from "expo-device";
import { useCallback, useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { batteryAdvice } from "../offline/policy";
import type { SyncState } from "../offline/sync";
import { isTrackingRunning, openBatterySettings, type PermissionState, permissionState } from "../tracking/control";
import { getEngine, getQueue, onSyncState, syncIfDue } from "../tracking/runtime";

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

  const refresh = useCallback(() => {
    void Promise.all([isTrackingRunning(), permissionState()]).then(([isRunning, p]) => {
      setRunning(isRunning);
      setPerm(p);
      setSync(getEngine().getState());
    });
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
      <Row label="Last GPS fix" value={fmt(lastFix)} />
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
