import { cookies } from "next/headers";

import { COOKIES } from "@/lib/auth/config";

/** Response of GET /api/v1/me. Roles and companies come from the API, never from the token. */
export type Membership = {
  tenant_id: string;
  tenant_slug: string;
  tenant_name: string;
  tenant_status: string;
  role: string;
  status: string;
};

export type Me = {
  user_id: string;
  display_name: string;
  email: string | null;
  is_platform_admin: boolean;
  mfa_verified: boolean;
  client: string;
  active_tenant: Membership | null;
  permissions: string[];
  mfa_required: boolean;
  memberships: Membership[];
};

export type ApiError = { code: string; message: string; requestId: string | null };
export type ApiResult<T> = { ok: true; data: T } | { ok: false; status: number; error: ApiError };

function apiBase(): string {
  const base = process.env.API_INTERNAL_URL;
  if (!base) throw new Error("API_INTERNAL_URL is not configured");
  return base;
}

/** Server-side call to /api/v1 with the user's access token and chosen company. */
export async function apiGet<T>(path: string): Promise<ApiResult<T>> {
  const store = await cookies();
  const token = store.get(COOKIES.access)?.value;
  if (!token) return { ok: false, status: 401, error: { code: "unauthenticated", message: "", requestId: null } };
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  const tenant = store.get(COOKIES.tenant)?.value;
  if (tenant) headers["X-Tenant"] = tenant;
  try {
    const response = await fetch(`${apiBase()}/api/v1${path}`, {
      headers,
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    const body: unknown = await response.json().catch(() => null);
    if (response.ok) return { ok: true, data: body as T };
    const error = (body as { error?: { code?: string; message?: string; request_id?: string } } | null)?.error;
    return {
      ok: false,
      status: response.status,
      error: {
        code: error?.code ?? "error",
        message: error?.message ?? "",
        requestId: error?.request_id ?? response.headers.get("x-request-id"),
      },
    };
  } catch {
    return { ok: false, status: 0, error: { code: "unreachable", message: "", requestId: null } };
  }
}
