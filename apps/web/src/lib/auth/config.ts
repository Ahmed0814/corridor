/**
 * Web sign-in: OAuth 2.0 authorization code + PKCE against Amazon Cognito's hosted UI
 * (DECISIONS D-006). Locally the backend's development issuer stands in for Cognito.
 *
 * The browser never sees tokens: the Next.js server exchanges the code and keeps tokens in
 * HttpOnly cookies (security-model.md §2). Roles and companies come from the API
 * (/api/v1/me), never from the token.
 */

export type Area = "ops" | "portal" | "admin";
/** Cognito app client used by each area. Customers use the portal client; staff the office one. */
export type ClientKind = "office" | "portal";

export const AREAS: readonly Area[] = ["ops", "portal", "admin"];

export function clientForArea(area: Area): ClientKind {
  return area === "portal" ? "portal" : "office";
}

export function areaForPath(pathname: string): Area | null {
  const first = pathname.split("/")[1];
  return (AREAS as readonly string[]).includes(first ?? "") ? (first as Area) : null;
}

export const COOKIES = {
  access: "corridor_access",
  refresh: "corridor_refresh",
  client: "corridor_client",
  tenant: "corridor_tenant",
  oauth: "corridor_oauth",
} as const;

export type AuthConfig = {
  authorizeUrl: string;
  tokenUrl: string;
  logoutUrl: string;
  clientIds: Record<ClientKind, string>;
  appBaseUrl: string;
  secureCookies: boolean;
};

/** Reads server-side configuration. Throws when a value is missing (no silent defaults). */
export function authConfig(env: NodeJS.ProcessEnv = process.env): AuthConfig {
  const need = (name: string): string => {
    const value = env[name];
    if (!value) throw new Error(`${name} is not configured`);
    return value;
  };
  const appBaseUrl = need("APP_BASE_URL");
  return {
    authorizeUrl: need("AUTH_AUTHORIZE_URL"),
    tokenUrl: need("AUTH_TOKEN_URL"),
    logoutUrl: need("AUTH_LOGOUT_URL"),
    clientIds: { office: need("AUTH_CLIENT_ID_OFFICE"), portal: need("AUTH_CLIENT_ID_PORTAL") },
    appBaseUrl,
    secureCookies: appBaseUrl.startsWith("https://"),
  };
}

export function redirectUri(config: AuthConfig): string {
  return `${config.appBaseUrl}/auth/callback`;
}

/**
 * Only same-site relative paths are accepted as post-login destinations (no open redirect):
 * must start with a single "/", no backslashes, no scheme-relative "//".
 */
export function safeNext(next: string | null | undefined, fallback: string): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return fallback;
  try {
    const url = new URL(next, "http://placeholder.invalid");
    if (url.host !== "placeholder.invalid") return fallback;
    return `${url.pathname}${url.search}`;
  } catch {
    return fallback;
  }
}

/** POST routes accept only same-origin form submissions (CSRF defence in depth on top of
 * SameSite=Lax cookies). Browsers always send Origin on POST. */
export function isSameOrigin(originHeader: string | null, config: AuthConfig): boolean {
  if (!originHeader) return false;
  try {
    return new URL(originHeader).origin === new URL(config.appBaseUrl).origin;
  } catch {
    return false;
  }
}
