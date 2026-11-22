// Pure session logic (no React Native imports) so it can be unit-tested with `node --test`.

export type StoredSession = {
  accessToken: string;
  refreshToken: string | null;
  /** Epoch milliseconds when the access token expires. */
  expiresAt: number;
};

/** Refresh this long before the access token actually expires (clock skew, slow networks). */
export const REFRESH_MARGIN_MS = 60_000;

export type TokenResponseLike = {
  accessToken: string;
  refreshToken?: string | null;
  expiresIn?: number | null;
};

export function toStoredSession(
  token: TokenResponseLike,
  now: number,
  previousRefreshToken: string | null = null,
): StoredSession {
  if (!token.accessToken) throw new Error('Token response has no access token');
  const expiresInSeconds = token.expiresIn && token.expiresIn > 0 ? token.expiresIn : 300;
  return {
    accessToken: token.accessToken,
    // A refresh response may omit the refresh token; keep the one we had.
    refreshToken: token.refreshToken ?? previousRefreshToken,
    expiresAt: now + expiresInSeconds * 1000,
  };
}

export function needsRefresh(session: StoredSession, now: number): boolean {
  return now >= session.expiresAt - REFRESH_MARGIN_MS;
}

/** Parse what secure storage returned; anything malformed counts as "signed out". */
export function parseStoredSession(raw: string | null): StoredSession | null {
  if (!raw) return null;
  try {
    const value: unknown = JSON.parse(raw);
    if (
      value !== null &&
      typeof value === 'object' &&
      typeof (value as StoredSession).accessToken === 'string' &&
      typeof (value as StoredSession).expiresAt === 'number' &&
      ((value as StoredSession).refreshToken === null || typeof (value as StoredSession).refreshToken === 'string')
    ) {
      return value as StoredSession;
    }
  } catch {
    // fall through
  }
  return null;
}

export type MembershipSummary = {
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
  client: string;
  active_tenant: MembershipSummary | null;
  permissions: string[];
  memberships: MembershipSummary[];
};

/** The API's error envelope code, if the body is one (docs: MASTER_PROMPT §5). */
export function errorCode(body: unknown): string | null {
  const code = (body as { error?: { code?: unknown } } | null)?.error?.code;
  return typeof code === 'string' ? code : null;
}

/** Driver-facing explanation for an API error code. Unknown codes get a generic message. */
export function describeError(code: string | null): string {
  switch (code) {
    case 'no_membership':
      return 'This account is not registered as a driver yet. Ask your company to invite you.';
    case 'membership_suspended':
      return 'Your access is suspended. Contact your dispatcher.';
    case 'tenant_suspended':
      return 'Your company account is suspended.';
    case 'no_access':
      return 'This account has no access to Corridor.';
    case 'wrong_client':
      return 'This account cannot use the driver app.';
    case 'unauthenticated':
      return 'Your session has expired. Sign in again.';
    default:
      return 'Something went wrong. Try again.';
  }
}
