"use server";

// Phase 6 server actions: proof of delivery, tracking links, geofences/checkpoints, notifications.
// Same rules as actions.ts: the API decides everything; errors come back as ?error=<code>.

import { revalidatePath } from "next/cache";
import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { type ApiResult, apiSend } from "@/lib/api";
import { apiUpload } from "@/lib/api-files";
import { type DocumentInfo, LINK_FIELDS, type TrackingLinkCreated, trackingUrl } from "@/lib/phase6";

const UUID = /^[0-9a-f-]{36}$/i;

function text(form: FormData, name: string): string {
  const v = form.get(name);
  return typeof v === "string" ? v.trim() : "";
}

function key(form: FormData): string {
  const k = text(form, "idempotency_key");
  return /^[A-Za-z0-9._:-]{8,100}$/.test(k) ? k : crypto.randomUUID();
}

function fail(back: string, result: { error: { code: string; requestId: string | null } }): never {
  const q = new URLSearchParams({ error: result.error.code });
  if (result.error.requestId) q.set("ref", result.error.requestId);
  redirect(`${back}?${q.toString()}`);
}

function finish<T>(result: ApiResult<T>, back: string): never {
  if (!result.ok) fail(back, result);
  revalidatePath("/ops", "layout");
  redirect(back);
}

// --------------------------------------------------------------------------- proof of delivery

/**
 * Upload the delivery photo and the signature, then confirm the delivery. Each step has its own
 * idempotency key derived from the form's key, so a resubmitted form replays instead of
 * uploading twice.
 */
export async function deliverWithEvidence(form: FormData): Promise<void> {
  const id = text(form, "shipment_id");
  const back = UUID.test(id) ? `/ops/shipments/${id}` : "/ops/shipments";
  if (!UUID.test(id)) redirect(`${back}?error=bad_request`);
  const photo = form.get("photo");
  const signature = text(form, "signature");
  const recipient = text(form, "recipient");
  if (!(photo instanceof File) || photo.size === 0) redirect(`${back}?error=photo_required`);
  if (!signature) redirect(`${back}?error=signature_required`);
  const base = key(form);

  const photoForm = new FormData();
  photoForm.set("kind", "delivery_photo");
  photoForm.set("file", photo, photo.name || "delivery-photo");
  const uploadedPhoto = await apiUpload<DocumentInfo>(`/shipments/${id}/documents`, photoForm, `${base}:photo`);
  if (!uploadedPhoto.ok) fail(back, uploadedPhoto);

  const sigForm = new FormData();
  sigForm.set("kind", "delivery_signature");
  sigForm.set("file", new Blob([signature], { type: "application/json" }), "signature.json");
  const uploadedSig = await apiUpload<DocumentInfo>(`/shipments/${id}/documents`, sigForm, `${base}:signature`);
  if (!uploadedSig.ok) fail(back, uploadedSig);

  const body = { recipient_name: recipient, photo_ids: [uploadedPhoto.data.id], signature_id: uploadedSig.data.id };
  finish(await apiSend("POST", `/shipments/${id}/deliver`, body, `${base}:deliver`), back);
}

// --------------------------------------------------------------------------- tracking links

export type CreateLinkState = { url?: string; error?: string; requestId?: string | null };

/** Returns the URL to the client once; it is never put in a redirect or a log. */
export async function createTrackingLink(_prev: CreateLinkState, form: FormData): Promise<CreateLinkState> {
  const id = text(form, "shipment_id");
  if (!UUID.test(id)) return { error: "bad_request" };
  const fields = form.getAll("fields").filter((f): f is string => typeof f === "string" && LINK_FIELDS.includes(f as never));
  const days = Number(text(form, "expires_in_days") || "30");
  const body = {
    label: text(form, "label"),
    expires_in_days: Number.isFinite(days) ? days : 30,
    allowed_fields: fields.length ? fields : null,
  };
  const result = await apiSend<TrackingLinkCreated>("POST", `/shipments/${id}/tracking-links`, body, key(form));
  if (!result.ok) return { error: result.error.code, requestId: result.error.requestId };
  const h = await headers();
  const host = h.get("x-forwarded-host") ?? h.get("host") ?? "localhost:3000";
  const proto = h.get("x-forwarded-proto") ?? (host.startsWith("localhost") ? "http" : "https");
  revalidatePath(`/ops/shipments/${id}`);
  return { url: trackingUrl(process.env.PUBLIC_WEB_URL ?? `${proto}://${host}`, result.data.token) };
}

export async function revokeTrackingLink(form: FormData): Promise<void> {
  const id = text(form, "shipment_id");
  const linkId = text(form, "link_id");
  const back = UUID.test(id) ? `/ops/shipments/${id}` : "/ops/shipments";
  if (!UUID.test(linkId)) redirect(`${back}?error=bad_request`);
  finish(await apiSend("POST", `/tracking-links/${linkId}/revoke`, { reason: text(form, "reason") }, key(form)), back);
}

// --------------------------------------------------------------------------- geofences

export async function createGeofence(form: FormData): Promise<void> {
  const body = {
    name: text(form, "name"),
    kind: text(form, "kind"),
    center: { lat: Number(text(form, "lat")), lng: Number(text(form, "lng")) },
    radius_m: Number(text(form, "radius_m")),
    source_note: text(form, "source_note"),
  };
  finish(await apiSend("POST", "/geofences", body, key(form)), "/ops/geofences");
}

export async function geofenceAction(form: FormData): Promise<void> {
  const id = text(form, "geofence_id");
  const action = text(form, "action");
  if (!UUID.test(id) || !["verify", "activate", "deactivate"].includes(action)) redirect("/ops/geofences?error=bad_request");
  finish(await apiSend("POST", `/geofences/${id}/${action}`, {}, key(form)), "/ops/geofences");
}

export async function createCheckpoint(form: FormData): Promise<void> {
  const body = {
    geofence_id: text(form, "geofence_id"),
    name: text(form, "name"),
    is_border: form.get("is_border") === "on",
  };
  finish(await apiSend("POST", "/checkpoints", body, key(form)), "/ops/geofences");
}

export async function deactivateCheckpoint(form: FormData): Promise<void> {
  const id = text(form, "checkpoint_id");
  if (!UUID.test(id)) redirect("/ops/geofences?error=bad_request");
  finish(await apiSend("POST", `/checkpoints/${id}/deactivate`, {}, key(form)), "/ops/geofences");
}

// --------------------------------------------------------------------------- notifications

export async function markNotificationRead(form: FormData): Promise<void> {
  const id = text(form, "notification_id");
  if (!UUID.test(id)) redirect("/ops/notifications?error=bad_request");
  finish(await apiSend("POST", `/notifications/${id}/read`, {}, key(form)), "/ops/notifications");
}

export async function markAllNotificationsRead(form: FormData): Promise<void> {
  finish(await apiSend("POST", "/notifications/read-all", {}, key(form)), "/ops/notifications");
}
