import { type NextRequest, NextResponse } from "next/server";

import { authConfig, COOKIES, isSameOrigin, safeNext } from "@/lib/auth/config";

const SLUG = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;

/**
 * Choose which of the user's companies to act for. Only a preference: the API checks that the
 * user is a member (404 otherwise) and records the switch in the company's audit log.
 */
export async function POST(request: NextRequest) {
  const config = authConfig();
  if (!isSameOrigin(request.headers.get("origin"), config)) {
    return new NextResponse("Forbidden", { status: 403 });
  }
  const form = await request.formData();
  const slug = String(form.get("tenant") ?? "");
  const next = safeNext(String(form.get("next") ?? ""), "/ops");
  const response = NextResponse.redirect(new URL(next, config.appBaseUrl), 303);
  if (SLUG.test(slug)) {
    response.cookies.set(COOKIES.tenant, slug, {
      httpOnly: true,
      secure: config.secureCookies,
      sameSite: "lax",
      path: "/",
      maxAge: 30 * 24 * 3600,
    });
  }
  return response;
}
