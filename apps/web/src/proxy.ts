import { type NextRequest, NextResponse } from "next/server";

import { COOKIES } from "@/lib/auth/config";
import { gate } from "@/lib/auth/gate";

/**
 * Auth scope per area (DECISIONS D-039): /ops and /admin need an office session, /portal a
 * customer portal session. Optimistic cookie check only; the API authorizes every request.
 */
export function proxy(request: NextRequest) {
  const decision = gate({
    pathname: request.nextUrl.pathname,
    search: request.nextUrl.search,
    hasAccess: request.cookies.has(COOKIES.access),
    hasRefresh: request.cookies.has(COOKIES.refresh),
    client: request.cookies.get(COOKIES.client)?.value,
  });
  if (decision.action === "redirect") {
    return NextResponse.redirect(new URL(decision.location, request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/ops/:path*", "/portal/:path*", "/admin/:path*"],
};
