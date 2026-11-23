// Server-side API calls for Phase 6: multipart uploads, public (unauthenticated) reads and raw
// downloads. Same rules as lib/api.ts: the token and company come from httpOnly cookies.

import { cookies, headers } from "next/headers";

import type { ApiResult } from "@/lib/api";
import { COOKIES } from "@/lib/auth/config";
import { invalidFields } from "@/lib/forms";

function apiBase(): string {
  const base = process.env.API_INTERNAL_URL;
  if (!base) throw new Error("API_INTERNAL_URL is not configured");
  return base;
}

function toError(status: number, data: unknown, response: Response): ApiResult<never> {
  const error = (data as { error?: { code?: string; message?: string; request_id?: string; details?: unknown } } | null)?.error;
  return {
    ok: false,
    status,
    error: {
      code: error?.code ?? "error",
      message: error?.message ?? "",
      requestId: error?.request_id ?? response.headers.get("x-request-id"),
      fields: invalidFields(error?.details),
    },
  };
}

async function authHeaders(): Promise<Record<string, string> | null> {
  const store = await cookies();
  const token = store.get(COOKIES.access)?.value;
  if (!token) return null;
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  const tenant = store.get(COOKIES.tenant)?.value;
  if (tenant) headers["X-Tenant"] = tenant;
  return headers;
}

const UNAUTHENTICATED: ApiResult<never> = {
  ok: false,
  status: 401,
  error: { code: "unauthenticated", message: "", requestId: null },
};
const UNREACHABLE: ApiResult<never> = { ok: false, status: 0, error: { code: "unreachable", message: "", requestId: null } };

/** Multipart upload (documents) with the user's token, company and an Idempotency-Key. */
export async function apiUpload<T>(path: string, form: FormData, idempotencyKey: string): Promise<ApiResult<T>> {
  const headers = await authHeaders();
  if (!headers) return UNAUTHENTICATED;
  try {
    const response = await fetch(`${apiBase()}/api/v1${path}`, {
      method: "POST",
      headers: { ...headers, "Idempotency-Key": idempotencyKey },
      body: form,
      cache: "no-store",
      signal: AbortSignal.timeout(60_000),
    });
    const data: unknown = await response.json().catch(() => null);
    return response.ok ? { ok: true, data: data as T } : toError(response.status, data, response);
  } catch {
    return UNREACHABLE;
  }
}

/** The visitor's address, so per-visitor rate limits in the API see the visitor, not this server. */
async function visitorHeaders(): Promise<Record<string, string>> {
  const h = await headers();
  const forwarded = h.get("x-forwarded-for");
  return forwarded ? { "X-Forwarded-For": forwarded } : {};
}

/** Public, unauthenticated GET (tracking links). Never sends the user's cookies or token. */
export async function apiPublicGet<T>(path: string): Promise<ApiResult<T>> {
  try {
    const response = await fetch(`${apiBase()}/api/v1${path}`, {
      headers: await visitorHeaders(),
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    const data: unknown = await response.json().catch(() => null);
    return response.ok ? { ok: true, data: data as T } : toError(response.status, data, response);
  } catch {
    return UNREACHABLE;
  }
}

/** Authenticated GET returning the raw response (document downloads streamed through Next). */
export async function apiFetchRaw(path: string): Promise<Response | null> {
  const headers = await authHeaders();
  if (!headers) return null;
  try {
    return await fetch(`${apiBase()}/api/v1${path}`, {
      headers,
      cache: "no-store",
      signal: AbortSignal.timeout(30_000),
    });
  } catch {
    return null;
  }
}

/** Public, unauthenticated JSON POST (container lookup). Never sends the user's cookies or token. */
export async function apiPublicPost<T>(path: string, body: unknown): Promise<ApiResult<T>> {
  try {
    const response = await fetch(`${apiBase()}/api/v1${path}`, {
      method: "POST",
      headers: { ...(await visitorHeaders()), "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    const data: unknown = await response.json().catch(() => null);
    return response.ok ? { ok: true, data: data as T } : toError(response.status, data, response);
  } catch {
    return UNREACHABLE;
  }
}
