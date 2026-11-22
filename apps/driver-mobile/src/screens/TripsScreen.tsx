// The driver's trips and trip actions. Starting a trip starts background tracking; completing it stops
// tracking only after the server accepted the completion (the queue keeps uploading meanwhile).
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { requestPermissions, startTracking, stopTracking } from "../tracking/control";
import { syncIfDue } from "../tracking/runtime";
import { driverActions, myTrips, type Trip, type TripAction, tripAction, TripApiError } from "../trips";
import { DeliveryScreen } from "./DeliveryScreen";
import { TrackingStatus } from "./TrackingStatus";

const ACTION_LABEL = { start: "Start trip", pause: "Pause", resume: "Resume", complete: "Complete trip" } as const;

export function TripsScreen() {
  const [trips, setTrips] = useState<Trip[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [delivering, setDelivering] = useState<Trip | null>(null);

  const load = useCallback(async () => {
    try {
      setTrips(await myTrips());
      setMessage(null);
    } catch (e) {
      setMessage(e instanceof TripApiError && e.code === "unreachable" ? "Offline: showing nothing new until the network is back." : "Could not load trips.");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    myTrips().then(
      (list) => {
        if (!cancelled) setTrips(list);
      },
      () => {
        if (!cancelled) setMessage("Could not load trips.");
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  async function act(trip: Trip, action: TripAction) {
    setBusy(true);
    try {
      if (action === "start") {
        const perm = await requestPermissions();
        if (perm === "denied") {
          Alert.alert("Location needed", "Allow location access to start the trip. Your location is shared only during trips.");
          return;
        }
      }
      const updated = await tripAction(trip.id, action);
      if (action === "start" || action === "resume") {
        const vehicleId = updated.assignment?.vehicle_id ?? trip.assignment?.vehicle_id;
        if (vehicleId) {
          const ok = await startTracking({ tripId: trip.id, vehicleId });
          if (!ok) setMessage("The trip started but the phone did not start location tracking. Check permissions.");
        }
      }
      if (action === "complete") {
        await syncIfDue(true); // upload what is queued before stopping
        await stopTracking();
      }
      await load();
    } catch (e) {
      const code = e instanceof TripApiError ? e.code : null;
      setMessage(code === "unreachable" ? "No network: trip actions need a connection. Tracking continues offline." : `Action refused (${code ?? "error"}).`);
    } finally {
      setBusy(false);
    }
  }

  const active = trips?.some((t) => t.status === "in_progress" || t.status === "paused") ?? false;


  if (delivering) {
    return (
      <DeliveryScreen
        trip={delivering}
        onDone={(done) => {
          setDelivering(null);
          if (done) setMessage(done);
          void load();
        }}
      />
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <TrackingStatus tripActive={active} />
      {message ? (
        <Text style={styles.message} accessibilityRole="alert">
          {message}
        </Text>
      ) : null}
      {trips === null ? <ActivityIndicator /> : null}
      {trips?.length === 0 ? <Text style={styles.muted}>No trips assigned to you.</Text> : null}
      {trips?.map((trip) => (
        <View key={trip.id} style={styles.trip}>
          <Text style={styles.ref}>{trip.reference}</Text>
          <Text>
            {trip.origin_label} → {trip.destination_label}
          </Text>
          <Text style={styles.muted}>
            {trip.status} · {trip.assignment?.vehicle_plate ?? ""}
          </Text>
          <View style={styles.actions}>
            {driverActions(trip.status).map((a) => (
              <Pressable key={a} disabled={busy} onPress={() => void act(trip, a)} accessibilityRole="button" style={[styles.button, busy && styles.dim]}>
                <Text style={styles.buttonText}>{ACTION_LABEL[a]}</Text>
              </Pressable>
            ))}
            {trip.status === "in_progress" || trip.status === "paused" ? (
              <Pressable disabled={busy} onPress={() => setDelivering(trip)} accessibilityRole="button" style={[styles.button, busy && styles.dim]}>
                <Text style={styles.buttonText}>Confirm delivery</Text>
              </Pressable>
            ) : null}
          </View>
        </View>
      ))}
      <Pressable onPress={() => void load()} accessibilityRole="button" style={styles.link}>
        <Text style={styles.linkText}>Refresh trips</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16, gap: 12, alignItems: "stretch" },
  trip: { borderWidth: 1, borderColor: "#ddd", borderRadius: 8, padding: 12, gap: 4 },
  ref: { fontSize: 16, fontWeight: "600" },
  muted: { color: "#555" },
  actions: { flexDirection: "row", gap: 8, marginTop: 8, flexWrap: "wrap" },
  button: { backgroundColor: "#1f2937", paddingVertical: 10, paddingHorizontal: 14, borderRadius: 8 },
  buttonText: { color: "#fff", fontWeight: "600" },
  dim: { opacity: 0.5 },
  message: { color: "#b00020" },
  link: { padding: 8, alignSelf: "center" },
  linkText: { color: "#1f4fd1", textDecorationLine: "underline" },
});
