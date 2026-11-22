// Phase 6 types mirroring /api/v1 (tracking links, public tracking, documents, notifications,
// geofences) plus pure helpers (unit-tested in phase6.test.ts).

import type { Freshness } from "@/lib/tracking";

export type LinkField = "status" | "eta" | "route" | "timeline" | "position" | "delivery";
export const LINK_FIELDS: readonly LinkField[] = ["status", "eta", "route", "timeline", "position", "delivery"];

export type TrackingLink = {
  id: string;
  shipment_id: string;
  label: string;
  allowed_fields: LinkField[];
  expires_at: string;
  revoked_at: string | null;
  state: "active" | "expired" | "revoked";
  created_at: string;
};
export type TrackingLinkCreated = TrackingLink & { token: string };

export type PublicPosition = {
  latitude: number;
  longitude: number;
  precision_km: number;
  recorded_at: string;
  received_at: string;
  freshness: Freshness;
};

export type PublicTracking = {
  reference: string;
  status?: string;
  is_delayed?: boolean;
  origin_label?: string;
  destination_label?: string;
  eta?: string | null;
  eta_method?: string | null;
  delivered_at?: string | null;
  timeline?: { label: string; at: string }[];
  position?: PublicPosition | null;
};

export type DocumentInfo = {
  id: string;
  shipment_id: string;
  kind: "delivery_photo" | "delivery_signature" | "paperwork";
  content_type: string;
  size_bytes: number;
  sha256: string;
  original_name: string;
  visibility: "internal" | "customer";
  created_at: string;
};

export type NotificationItem = {
  id: string;
  kind: string;
  title: string;
  body: string;
  link: string;
  read_at: string | null;
  created_at: string;
};
export type NotificationPage = { items: NotificationItem[]; unread: number };

export type Geofence = {
  id: string;
  name: string;
  kind: string;
  shape: string;
  polygon: [number, number][];
  source_note: string;
  verified: boolean;
  verified_at: string | null;
  is_active: boolean;
  created_at: string;
};

export type Checkpoint = {
  id: string;
  geofence_id: string;
  geofence_name: string;
  name: string;
  is_border: boolean;
  verified: boolean;
  is_active: boolean;
  created_at: string;
};

export const GEOFENCE_KINDS = ["port", "border", "city", "depot", "customer_site", "checkpoint"] as const;

/** The shareable URL for a token. The token goes in the path, never in a query string. */
export function trackingUrl(origin: string, token: string): string {
  return `${origin.replace(/\/+$/, "")}/track/${encodeURIComponent(token)}`;
}

/** Tokens are url-safe base64 (secrets.token_urlsafe(32) = 43 chars); anything else is rejected early. */
export function plausibleToken(token: string): boolean {
  return /^[A-Za-z0-9_-]{20,128}$/.test(token);
}

export type EtaView =
  | { kind: "estimate"; eta: string; remainingKm: number | null; basisRecordedAt: string | null }
  | { kind: "no_destination" }
  | { kind: "none" };

/** How to present a shipment's ETA: never invent one, always say what it is based on. */
export function etaView(s: {
  eta: string | null;
  eta_method?: string;
  eta_remaining_km?: number | null;
  eta_basis_recorded_at?: string | null;
}): EtaView {
  if (s.eta_method === "unavailable_no_destination") return { kind: "no_destination" };
  if (!s.eta) return { kind: "none" };
  return {
    kind: "estimate",
    eta: s.eta,
    remainingKm: s.eta_remaining_km ?? null,
    basisRecordedAt: s.eta_basis_recorded_at ?? null,
  };
}

export type Stroke = [number, number][];
export type Signature = { width: number; height: number; strokes: Stroke[] };

/**
 * Signature as the API accepts it: integers inside the pad, at least two points in total and at
 * most 5000. Returns null when there is nothing usable (an empty pad).
 */
export function signaturePayload(width: number, height: number, strokes: Stroke[]): Signature | null {
  const w = Math.round(width);
  const h = Math.round(height);
  if (w <= 0 || h <= 0 || w > 4000 || h > 4000) return null;
  const clamp = (v: number, max: number) => Math.min(max, Math.max(0, Math.round(v)));
  const clean = strokes
    .map((s) => s.map(([x, y]) => [clamp(x, w), clamp(y, h)] as [number, number]))
    .filter((s) => s.length > 0);
  const points = clean.reduce((n, s) => n + s.length, 0);
  if (points < 2 || points > 5000) return null;
  return { width: w, height: h, strokes: clean };
}

const NOTIFICATION_LINK = /^\/ops\/shipments\/[0-9a-f-]{36}$/i;

/** Only internal shipment links are rendered as links (the text comes from server data). */
export function safeNotificationLink(link: string): string | null {
  return NOTIFICATION_LINK.test(link) ? link : null;
}

/** Circle radius bounds the API accepts (metres). */
export function validRadius(value: number): boolean {
  return Number.isFinite(value) && value >= 50 && value <= 20_000;
}
