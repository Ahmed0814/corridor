import { type NextRequest, NextResponse } from "next/server";

import { areaForPath, authConfig, COOKIES, safeNext } from "@/lib/auth/config";
import { clearSession, exchange, refreshGrant, setSession } from "@/lib/auth/session";

/** Renew the access token with the refresh token (sent only to /auth paths). */
export async function GET(request: NextRequest) {
  const config = authConfig();
  const next = safeNext(request.nextUrl.searchParams.get("next"), "/");
  const refresh = request.cookies.get(COOKIES.refresh)?.value;
  const client = request.cookies.get(COOKIES.client)?.value;
  const area = areaForPath(next) ?? "ops";
  const login = new URL(`/auth/login?area=${area}&next=${encodeURIComponent(next)}`, config.appBaseUrl);

  if (!refresh || (client !== "office" && client !== "portal")) {
    const response = NextResponse.redirect(login);
    clearSession(response);
    return response;
  }
  const tokens = await exchange(config, refreshGrant(config, client, refresh));
  if (!tokens) {
    const response = NextResponse.redirect(login);
    clearSession(response);
    return response;
  }
  const response = NextResponse.redirect(new URL(next, config.appBaseUrl));
  setSession(response, config, client, { ...tokens, refresh_token: tokens.refresh_token ?? refresh });
  return response;
}
