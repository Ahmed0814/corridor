// HTTP transport for GPS batches: POST /api/v1/tracking/location/batch with the driver's token.
// Errors are mapped to TransportError so the sync engine knows whether to retry, isolate or stop.
import { refreshSession } from "../api";
import { loadSession } from "../auth/tokenStore";
import { needsRefresh } from "../auth/session";
import { API_BASE_URL } from "../config";
import type { IngestResult, LocationEvent, Transport, TransportError } from "../offline/types";

const TIMEOUT_MS = 20_000;

async function accessToken(): Promise<string | null> {
  let session = await loadSession();
  if (!session) return null;
  if (needsRefresh(session, Date.now())) session = await refreshSession(session);
  return session?.accessToken ?? null;
}

export const httpTransport: Transport = {
  async sendBatch(events: LocationEvent[]): Promise<IngestResult> {
    const token = await accessToken();
    if (!token) throw { kind: "http", status: 401, code: "unauthenticated" } satisfies TransportError;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}/api/v1/tracking/location/batch`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ events }),
        signal: controller.signal,
      });
    } catch (e) {
      // Offline, DNS failure, timeout, connection reset: the batch may or may not have been stored.
      // Retrying is safe because the server deduplicates by device + event id.
      throw { kind: "network", message: e instanceof Error ? e.message : "network error" } satisfies TransportError;
    } finally {
      clearTimeout(timer);
    }
    const body: unknown = await response.json().catch(() => null);
    if (response.ok) return body as IngestResult;
    const code = (body as { error?: { code?: string } } | null)?.error?.code ?? null;
    throw { kind: "http", status: response.status, code } satisfies TransportError;
  },
};
