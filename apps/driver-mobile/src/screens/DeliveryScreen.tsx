// Proof of delivery: pick the shipment, photograph the delivery, collect the recipient's signature and
// name, then confirm. Online only: nothing is confirmed until the server accepted the photo, the
// signature and the delivery (each step is idempotent, so "Try again" never duplicates anything).
import * as Crypto from "expo-crypto";
import * as ImagePicker from "expo-image-picker";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Image,
  type LayoutChangeEvent,
  PanResponder,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { addPoint, confirmDelivery, deliverable, deliveryMessage, type FormFactory, type Photo, signaturePayload, type Stroke } from "../delivery";
import { sendWithKey, type ShipmentSummary, type Trip, tripShipments } from "../trips";

const makeForm: FormFactory = (fields, file) => {
  const form = new FormData();
  for (const [k, v] of Object.entries(fields)) form.append(k, v);
  if ("json" in file) {
    form.append("file", new Blob([file.json], { type: "application/json" }), file.name);
  } else {
    // React Native's FormData takes {uri, type, name} for files on disk.
    form.append("file", { uri: file.uri, type: file.type, name: file.name } as unknown as Blob);
  }
  return form;
};

function SignaturePad({ onChange }: { onChange: (strokes: Stroke[], size: { w: number; h: number }) => void }) {
  // Rendering reads state only; the gesture handlers below work on their own copy and publish it.
  const [drawn, setDrawn] = useState<Stroke[]>([]);
  const [size, setSize] = useState({ w: 0, h: 0 });

  const handlers = useMemo(() => {
    const g: { working: Stroke[]; box: { w: number; h: number } } = { working: [], box: { w: 0, h: 0 } };
    const responder = PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      onPanResponderGrant: (e) => {
        g.working = [...g.working, [[e.nativeEvent.locationX, e.nativeEvent.locationY]]];
        setDrawn(g.working);
      },
      onPanResponderMove: (e) => {
        const stroke = g.working[g.working.length - 1];
        if (stroke && addPoint(stroke, [e.nativeEvent.locationX, e.nativeEvent.locationY], 3)) setDrawn([...g.working]);
      },
      onPanResponderRelease: () => onChange(g.working, g.box),
    });
    return {
      pan: responder.panHandlers,
      reset: () => {
        g.working = [];
      },
      setBox: (b: { w: number; h: number }) => {
        g.box = b;
      },
    };
  }, [onChange]);

  function clear() {
    handlers.reset();
    setDrawn([]);
    onChange([], size);
  }

  return (
    <View>
      <View
        style={styles.pad}
        onLayout={(e: LayoutChangeEvent) => {
          const b = { w: e.nativeEvent.layout.width, h: e.nativeEvent.layout.height };
          handlers.setBox(b);
          setSize(b);
        }}
        accessibilityLabel="Signature pad"
        {...handlers.pan}
      >
        {drawn.flatMap((s, i) => s.map(([x, y], j) => <View key={`${i}-${j}`} pointerEvents="none" style={[styles.dot, { left: x - 2, top: y - 2 }]} />))}
        {drawn.length === 0 ? <Text style={styles.padHint}>Recipient signs here</Text> : null}
      </View>
      <Pressable onPress={clear} accessibilityRole="button" style={styles.link}>
        <Text style={styles.linkText}>Clear signature</Text>
      </Pressable>
    </View>
  );
}

export function DeliveryScreen({ trip, onDone }: { trip: Trip; onDone: (message: string | null) => void }) {
  const [shipments, setShipments] = useState<ShipmentSummary[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [photo, setPhoto] = useState<Photo | null>(null);
  const [signature, setSignature] = useState<ReturnType<typeof signaturePayload>>(null);
  const [recipient, setRecipient] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // One key per attempt; kept across "Try again" so a lost response is replayed, not repeated.
  const attemptKey = useRef(Crypto.randomUUID());

  const onSigned = useCallback((strokes: Stroke[], size: { w: number; h: number }) => {
    setSignature(signaturePayload(size.w, size.h, strokes));
    attemptKey.current = Crypto.randomUUID();
  }, []);

  useEffect(() => {
    let cancelled = false;
    tripShipments(trip).then(
      (list) => {
        if (cancelled) return;
        const open = deliverable(list);
        setShipments(open);
        if (open.length === 1) setSelected(open[0].id);
      },
      () => {
        if (!cancelled) setError("Could not load the shipments of this trip.");
      },
    );
    return () => {
      cancelled = true;
    };
  }, [trip]);

  async function takePhoto() {
    const permission = await ImagePicker.requestCameraPermissionsAsync();
    if (!permission.granted) {
      setError("Camera permission is needed for the delivery photo.");
      return;
    }
    const result = await ImagePicker.launchCameraAsync({ mediaTypes: ["images"], quality: 0.6, exif: false });
    if (result.canceled || !result.assets[0]) return;
    const a = result.assets[0];
    setPhoto({ uri: a.uri, mimeType: a.mimeType ?? "image/jpeg", name: a.fileName ?? "delivery.jpg" });
    attemptKey.current = Crypto.randomUUID(); // new evidence = new attempt
  }

  async function submit() {
    if (!selected || !photo || !signature || !recipient.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await confirmDelivery(sendWithKey, makeForm, { shipmentId: selected, recipientName: recipient, photo, signature, attemptKey: attemptKey.current });
      onDone("Delivery confirmed.");
    } catch (e) {
      setError(deliveryMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const ready = Boolean(selected && photo && signature && recipient.trim());

  return (
    <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
      <Text style={styles.title}>Confirm delivery · {trip.reference}</Text>
      {shipments === null && !error ? <ActivityIndicator /> : null}
      {shipments?.length === 0 ? <Text style={styles.muted}>No shipment on this trip is ready for delivery.</Text> : null}
      {shipments?.map((s) => (
        <Pressable
          key={s.id}
          onPress={() => {
            setSelected(s.id);
            attemptKey.current = Crypto.randomUUID();
          }}
          accessibilityRole="radio"
          accessibilityState={{ selected: selected === s.id }}
          style={[styles.option, selected === s.id && styles.optionSelected]}
        >
          <Text style={styles.ref}>{s.reference}</Text>
          <Text style={styles.muted}>{s.destination_label}</Text>
        </Pressable>
      ))}

      {selected ? (
        <>
          <Text style={styles.label}>1. Delivery photo</Text>
          {photo ? <Image source={{ uri: photo.uri }} style={styles.photo} accessibilityLabel="Delivery photo" /> : null}
          <Pressable onPress={() => void takePhoto()} accessibilityRole="button" style={styles.secondary}>
            <Text>{photo ? "Retake photo" : "Take photo"}</Text>
          </Pressable>

          <Text style={styles.label}>2. Recipient signature</Text>
          <SignaturePad onChange={onSigned} />

          <Text style={styles.label}>3. Recipient name</Text>
          <TextInput value={recipient} onChangeText={setRecipient} placeholder="Full name" maxLength={200} style={styles.input} />

          {error ? (
            <Text style={styles.error} accessibilityLiveRegion="polite">
              {error}
            </Text>
          ) : null}
          <Pressable onPress={() => void submit()} disabled={!ready || busy} accessibilityRole="button" style={[styles.button, (!ready || busy) && styles.dim]}>
            {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>{error ? "Try again" : "Confirm delivery"}</Text>}
          </Pressable>
          <Text style={styles.muted}>Needs network. Nothing is confirmed until the server accepts it.</Text>
        </>
      ) : error ? (
        <Text style={styles.error}>{error}</Text>
      ) : null}

      <Pressable onPress={() => onDone(null)} accessibilityRole="button" style={styles.link}>
        <Text style={styles.linkText}>Back to trips</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16, gap: 10 },
  title: { fontSize: 18, fontWeight: "600" },
  label: { fontWeight: "600", marginTop: 8 },
  ref: { fontWeight: "600" },
  muted: { color: "#555" },
  option: { borderWidth: 1, borderColor: "#ddd", borderRadius: 8, padding: 10 },
  optionSelected: { borderColor: "#1f2937", borderWidth: 2 },
  photo: { width: "100%", height: 200, borderRadius: 8, backgroundColor: "#eee" },
  pad: { height: 160, borderWidth: 1, borderColor: "#999", borderRadius: 8, backgroundColor: "#fff", overflow: "hidden", justifyContent: "center", alignItems: "center" },
  padHint: { color: "#aaa" },
  dot: { position: "absolute", width: 4, height: 4, borderRadius: 2, backgroundColor: "#111" },
  input: { borderWidth: 1, borderColor: "#ccc", borderRadius: 8, padding: 10 },
  button: { backgroundColor: "#1f2937", paddingVertical: 12, borderRadius: 8, alignItems: "center" },
  buttonText: { color: "#fff", fontWeight: "600" },
  secondary: { borderWidth: 1, borderColor: "#999", paddingVertical: 10, borderRadius: 8, alignItems: "center" },
  dim: { opacity: 0.5 },
  error: { color: "#b00020" },
  link: { padding: 8, alignSelf: "center" },
  linkText: { color: "#1f4fd1", textDecorationLine: "underline" },
});
