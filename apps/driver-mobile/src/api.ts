import * as AuthSession from 'expo-auth-session';

import { API_BASE_URL, AUTH } from './config';
import { errorCode, needsRefresh, toStoredSession, type Me, type StoredSession } from './auth/session';
import { clearSession, saveSession } from './auth/tokenStore';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string | null,
  ) {
    super(code ?? `HTTP ${status}`);
  }
}

const discovery = { tokenEndpoint: AUTH.tokenEndpoint };

/** Exchange a refresh token for a new session. Returns null (and signs out) if it was rejected. */
export async function refreshSession(session: StoredSession): Promise<StoredSession | null> {
  if (!session.refreshToken) {
    await clearSession();
    return null;
  }
  try {
    const token = await AuthSession.refreshAsync(
      { clientId: AUTH.clientId, refreshToken: session.refreshToken },
      discovery,
    );
    const next = toStoredSession(token, Date.now(), session.refreshToken);
    await saveSession(next);
    return next;
  } catch {
    await clearSession();
    return null;
  }
}

async function getJson(path: string, accessToken: string): Promise<{ status: number; body: unknown }> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Authorization: `Bearer ${accessToken}`, Accept: 'application/json' },
  });
  const body: unknown = await response.json().catch(() => null);
  return { status: response.status, body };
}

/**
 * GET /api/v1/me. Refreshes the access token first if it is about to expire, and once more if the
 * server says 401. Returns the (possibly refreshed) session alongside the profile.
 */
export async function fetchMe(session: StoredSession): Promise<{ me: Me; session: StoredSession }> {
  let current = session;
  if (needsRefresh(current, Date.now())) {
    const refreshed = await refreshSession(current);
    if (!refreshed) throw new ApiError(401, 'unauthenticated');
    current = refreshed;
  }
  let result = await getJson('/api/v1/me', current.accessToken);
  if (result.status === 401) {
    const refreshed = await refreshSession(current);
    if (!refreshed) throw new ApiError(401, 'unauthenticated');
    current = refreshed;
    result = await getJson('/api/v1/me', current.accessToken);
  }
  if (result.status !== 200) throw new ApiError(result.status, errorCode(result.body));
  return { me: result.body as Me, session: current };
}
