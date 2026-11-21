import { type NextRequest, NextResponse } from "next/server";

import { type Area, AREAS, authConfig, clientForArea, COOKIES, redirectUri, safeNext } from "@/lib/auth/config";
import { codeChallenge, randomToken } from "@/lib/auth/pkce";

/** Start sign-in: remember state + PKCE verifier in a short-lived HttpOnly cookie, then go to
 * the identity provider's authorize endpoint. */
export async function GET(request: NextRequest) {
  const config = authConfig();
  const areaParam = request.nextUrl.searchParams.get("area");
  const area: Area = (AREAS as readonly string[]).includes(areaParam ?? "") ? (areaParam as Area) : "ops";
  const client = clientForArea(area);
  const next = safeNext(request.nextUrl.searchParams.get("next"), `/${area}`);
  const state = randomToken();
  const verifier = randomToken(48);

  const authorize = new URL(config.authorizeUrl);
  authorize.search = new URLSearchParams({
    response_type: "code",
    client_id: config.clientIds[client],
    redirect_uri: redirectUri(config),
    scope: "openid email phone",
    state,
    code_challenge: await codeChallenge(verifier),
    code_challenge_method: "S256",
  }).toString();

  const response = NextResponse.redirect(authorize);
  response.cookies.set(COOKIES.oauth, JSON.stringify({ state, verifier, client, next }), {
    httpOnly: true,
    secure: config.secureCookies,
    sameSite: "lax", // sent on the top-level redirect back from the identity provider
    path: "/auth",
    maxAge: 600,
  });
  return response;
}
