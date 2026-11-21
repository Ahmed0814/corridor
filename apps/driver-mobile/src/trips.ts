// Driver trip API: the driver's own trips and their lifecycle actions (start/pause/resume/complete).
import * as Crypto from "expo-crypto";

import { refreshSession } from "./api";
import { needsRefresh, type StoredSession } from "./auth/session";
import { loadSession } from "./auth/tokenStore";
import { API_BASE_URL } from "./config";

export type Trip = {
  id: string;
  reference: string;
  status: string;
  origin_label: string;
  destination_label: string;
  shipment_ids: string[];
  assignment: { vehicle_id: string; vehicle_plate: string | null; driver_id: string } | null;
  started_at: string | null;
};

export type TripAction = "start" | "pause" | "resume" | "complete";

export class TripApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string | null,
  ) {
    super(code ?? `HTTP ${status}`);
  }
}

async function session(): Promise<StoredSession> {
  let s = await loadSession();
  if (s && needsRefresh(s, Date.now())) s = await refreshSession(s);
  if (!s) throw new TripApiError(401, "unauthenticated");
  return s;
}

async function call<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const s = await session();
  const headers: Record<string, string> = { Authorization: `Bearer ${s.accessToken}`, Accept: "application/json" };
  if (method === "POST") {
    headers["Content-Type"] = "application/json";
    headers["Idempotency-Key"] = Crypto.randomUUID(); // a retried tap never acts twice
  }
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/v1${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined });
  } catch {
    throw new TripApiError(0, "unreachable");
  }
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new TripApiError(response.status, (data as { error?: { code?: string } } | null)?.error?.code ?? null);
  return data as T;
}

/** Trips assigned to this driver that are not finished, newest first. */
export async function myTrips(): Promise<Trip[]> {
  const page = await call<{ items: Trip[] }>("GET", "/trips?limit=50");
  return page.items.filter((t) => ["assigned", "in_progress", "paused"].includes(t.status));
}

export function tripAction(tripId: string, action: TripAction): Promise<Trip> {
  return call<Trip>("POST", `/trips/${tripId}/${action}`, {});
}

/** Which actions the driver can take from a trip status (mirrors the API state machine). */
export function driverActions(status: string): TripAction[] {
  switch (status) {
    case "assigned":
      return ["start"];
    case "in_progress":
      return ["pause", "complete"];
    case "paused":
      return ["resume", "complete"];
    default:
      return [];
  }
}
