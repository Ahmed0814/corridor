// Proof of delivery (Phase 6, DECISIONS D-071): photo + signature uploaded to the shipment, then the
// delivery is confirmed with their ids. Pure helpers are unit-tested (delivery.test.ts); the network
// steps take an injected `send` so tests run without a phone or a server.

export type Point = [number, number];
export type Stroke = Point[];
export type Signature = { width: number; height: number; strokes: Stroke[] };

export type DeliverableShipment = {
  id: string;
  reference: string;
  status: string;
  destination_label: string;
};

/** The API accepts integers inside the pad, 2..5000 points. Null means "nothing signed yet". */
export function signaturePayload(width: number, height: number, strokes: Stroke[]): Signature | null {
  const w = Math.round(width);
  const h = Math.round(height);
  if (w <= 0 || h <= 0 || w > 4000 || h > 4000) return null;
  const clamp = (v: number, max: number) => Math.min(max, Math.max(0, Math.round(v)));
  const clean = strokes.map((s) => s.map(([x, y]): Point => [clamp(x, w), clamp(y, h)])).filter((s) => s.length > 0);
  const points = clean.reduce((n, s) => n + s.length, 0);
  if (points < 2 || points > 5000) return null;
  return { width: w, height: h, strokes: clean };
}

/** Skip points closer than `minDistance` to the previous one (keeps signatures small and smooth). */
export function addPoint(stroke: Stroke, p: Point, minDistance = 2): boolean {
  const last = stroke[stroke.length - 1];
  if (last && Math.hypot(p[0] - last[0], p[1] - last[1]) < minDistance) return false;
  stroke.push(p);
  return true;
}

/** Only in-transit shipments can be delivered (the API enforces the same rule). */
export function deliverable(shipments: DeliverableShipment[]): DeliverableShipment[] {
  return shipments.filter((s) => s.status === "in_transit");
}

export type Photo = { uri: string; mimeType: string; name: string };

export type SendResult = { ok: boolean; status: number; data: unknown };
/** method, path, body (JSON object or FormData), idempotency key */
export type Send = (method: "POST", path: string, body: unknown, idempotencyKey: string) => Promise<SendResult>;

export class DeliveryError extends Error {
  readonly step: "photo" | "signature" | "deliver";
  readonly status: number;
  readonly code: string | null;

  constructor(step: "photo" | "signature" | "deliver", status: number, code: string | null) {
    super(`${step}: ${code ?? status}`);
    this.step = step;
    this.status = status;
    this.code = code;
  }
}

function errorCode(data: unknown): string | null {
  return (data as { error?: { code?: string } } | null)?.error?.code ?? null;
}

export type FormFactory = (fields: Record<string, string>, file: { uri: string; type: string; name: string } | { json: string; name: string }) => unknown;

/**
 * Upload photo, upload signature, confirm delivery. One base key per attempt: each step derives
 * its own Idempotency-Key, so retrying the same attempt after a lost response never uploads or
 * delivers twice.
 */
export async function confirmDelivery(
  send: Send,
  makeForm: FormFactory,
  args: { shipmentId: string; recipientName: string; photo: Photo; signature: Signature; attemptKey: string },
): Promise<unknown> {
  const { shipmentId, recipientName, photo, signature, attemptKey } = args;
  const docs = `/shipments/${shipmentId}/documents`;

  const p = await send("POST", docs, makeForm({ kind: "delivery_photo" }, { uri: photo.uri, type: photo.mimeType, name: photo.name }), `${attemptKey}:photo`);
  if (!p.ok) throw new DeliveryError("photo", p.status, errorCode(p.data));
  const s = await send("POST", docs, makeForm({ kind: "delivery_signature" }, { json: JSON.stringify(signature), name: "signature.json" }), `${attemptKey}:signature`);
  if (!s.ok) throw new DeliveryError("signature", s.status, errorCode(s.data));

  const body = {
    recipient_name: recipientName.trim(),
    photo_ids: [(p.data as { id: string }).id],
    signature_id: (s.data as { id: string }).id,
  };
  const d = await send("POST", `/shipments/${shipmentId}/deliver`, body, `${attemptKey}:deliver`);
  if (!d.ok) throw new DeliveryError("deliver", d.status, errorCode(d.data));
  return d.data;
}

/** A message the driver can act on. */
export function deliveryMessage(e: unknown): string {
  if (!(e instanceof DeliveryError)) return "Something went wrong. Try again.";
  if (e.status === 0) return "No network. Nothing was confirmed; try again when you have signal.";
  if (e.code === "invalid_file") return "The photo could not be used. Take it again.";
  if (e.code === "invalid_signature") return "The signature could not be used. Ask the recipient to sign again.";
  if (e.code === "invalid_transition") return "This shipment can no longer be delivered (check its status).";
  if (e.status === 401 || e.status === 403) return "Sign in again to confirm deliveries.";
  return `Could not confirm the delivery (${e.code ?? e.status}).`;
}
