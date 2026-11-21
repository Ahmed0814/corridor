/** Server-side only: used by the /auth route handlers. */
import type { NextResponse } from "next/server";

import { type AuthConfig, type ClientKind, COOKIES, redirectUri } from "./config";

export type TokenResponse = { access_token: string; refresh_token?: string; expires_in: number };

const REFRESH_MAX_AGE = 30 * 24 * 3600;

/** Server-to-server call to the token endpoint (Cognito /oauth2/token or the local issuer). */
export async function exchange(config: AuthConfig, body: Record<string, string>): Promise<TokenResponse | null> {
  const response = await fetch(config.tokenUrl, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(body).toString(),
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) return null;
  const data = (await response.json()) as Partial<TokenResponse>;
  if (typeof data.access_token !== "string" || typeof data.expires_in !== "number") return null;
  return data as TokenResponse;
}

export function codeGrant(config: AuthConfig, client: ClientKind, code: string, verifier: string) {
  return {
    grant_type: "authorization_code",
    client_id: config.clientIds[client],
    code,
    code_verifier: verifier,
    redirect_uri: redirectUri(config),
  };
}

export function refreshGrant(config: AuthConfig, client: ClientKind, refreshToken: string) {
  return { grant_type: "refresh_token", client_id: config.clientIds[client], refresh_token: refreshToken };
}

export function setSession(response: NextResponse, config: AuthConfig, client: ClientKind, tokens: TokenResponse) {
  const base = { httpOnly: true, secure: config.secureCookies, sameSite: "lax" as const, path: "/" };
  // Expire the cookie a little before the token so the proxy refreshes instead of the API refusing.
  response.cookies.set(COOKIES.access, tokens.access_token, { ...base, maxAge: Math.max(tokens.expires_in - 30, 30) });
  if (tokens.refresh_token) {
    // Only the /auth routes ever need the refresh token.
    response.cookies.set(COOKIES.refresh, tokens.refresh_token, { ...base, path: "/auth", maxAge: REFRESH_MAX_AGE });
  }
  response.cookies.set(COOKIES.client, client, { ...base, maxAge: REFRESH_MAX_AGE });
}

export function clearSession(response: NextResponse) {
  response.cookies.delete(COOKIES.access);
  response.cookies.set(COOKIES.refresh, "", { path: "/auth", maxAge: 0 });
  response.cookies.delete(COOKIES.client);
  response.cookies.delete(COOKIES.tenant);
}
