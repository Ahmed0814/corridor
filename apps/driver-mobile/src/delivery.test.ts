/// <reference types="node" />
import assert from "node:assert/strict";
import { test } from "node:test";

import { addPoint, confirmDelivery, DeliveryError, deliverable, deliveryMessage, type Send, signaturePayload, type Stroke } from "./delivery.ts";

const photo = { uri: "file:///photo.jpg", mimeType: "image/jpeg", name: "photo.jpg" };
const signature = { width: 300, height: 120, strokes: [[[1, 1], [20, 30]]] as Stroke[] };
const makeForm = (fields: Record<string, string>, file: unknown) => ({ fields, file });

test("signature payload is clamped integers and refuses an empty pad", () => {
  assert.deepEqual(signaturePayload(300.2, 120, [[[-3, 5.6], [999, 60]]]), { width: 300, height: 120, strokes: [[[0, 6], [300, 60]]] });
  assert.equal(signaturePayload(300, 120, []), null);
  assert.equal(signaturePayload(300, 120, [[[5, 5]]]), null);
});

test("addPoint skips jitter", () => {
  const s: Stroke = [[0, 0]];
  assert.equal(addPoint(s, [1, 1]), false);
  assert.equal(addPoint(s, [5, 0]), true);
  assert.equal(s.length, 2);
});

test("only in-transit shipments are offered", () => {
  const list = deliverable([
    { id: "a", reference: "A", status: "in_transit", destination_label: "x" },
    { id: "b", reference: "B", status: "at_border", destination_label: "x" },
  ]);
  assert.deepEqual(list.map((s) => s.id), ["a"]);
});

test("uploads photo, then signature, then delivers with derived idempotency keys", async () => {
  const calls: { path: string; key: string; body: unknown }[] = [];
  const send: Send = async (_m, path, body, key) => {
    calls.push({ path, key, body });
    if (key.endsWith(":photo")) return { ok: true, status: 201, data: { id: "photo-1" } };
    if (key.endsWith(":signature")) return { ok: true, status: 201, data: { id: "sig-1" } };
    return { ok: true, status: 200, data: { status: "delivered" } };
  };
  const out = await confirmDelivery(send, makeForm, { shipmentId: "s1", recipientName: " Amina ", photo, signature, attemptKey: "attempt-123" });
  assert.deepEqual(out, { status: "delivered" });
  assert.deepEqual(calls.map((c) => c.key), ["attempt-123:photo", "attempt-123:signature", "attempt-123:deliver"]);
  assert.deepEqual(calls[2].body, { recipient_name: "Amina", photo_ids: ["photo-1"], signature_id: "sig-1" });
  assert.equal(calls[2].path, "/shipments/s1/deliver");
});

test("stops at the failing step and never confirms without evidence", async () => {
  const keys: string[] = [];
  const send: Send = async (_m, _p, _b, key) => {
    keys.push(key);
    return key.endsWith(":photo") ? { ok: true, status: 201, data: { id: "p" } } : { ok: false, status: 422, data: { error: { code: "invalid_signature" } } };
  };
  await assert.rejects(
    confirmDelivery(send, makeForm, { shipmentId: "s1", recipientName: "x", photo, signature, attemptKey: "k-000001" }),
    (e: unknown) => e instanceof DeliveryError && e.step === "signature" && e.code === "invalid_signature",
  );
  assert.equal(keys.some((k) => k.endsWith(":deliver")), false);
});

test("messages are actionable", () => {
  assert.match(deliveryMessage(new DeliveryError("photo", 0, "unreachable")), /No network/);
  assert.match(deliveryMessage(new DeliveryError("deliver", 409, "invalid_transition")), /no longer be delivered/);
  assert.match(deliveryMessage(new Error("x")), /Try again/);
});
