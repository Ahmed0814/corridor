import { type NextRequest, NextResponse } from "next/server";

import { authConfig, COOKIES, isSameOrigin } from "@/lib/auth/config";
import { clearSession } from "@/lib/auth/session";

/** Sign out: drop local cookies, then end the identity provider session (Cognito /logout).
 * POST only, so a third-party page cannot sign users out with an image tag. */
export async function POST(request: NextRequest) {
  const config = authConfig();
  if (!isSameOrigin(request.headers.get("origin"), config)) {
    return new NextResponse("Forbidden", { status: 403 });
  }
  const client = request.cookies.get(COOKIES.client)?.value === "portal" ? "portal" : "office";
  const logout = new URL(config.logoutUrl);
  logout.search = new URLSearchParams({
    client_id: config.clientIds[client],
    logout_uri: `${config.appBaseUrl}/`,
  }).toString();
  const response = NextResponse.redirect(logout, 303);
  clearSession(response);
  return response;
}
