import { type NextRequest, NextResponse } from "next/server";

import { authConfig, type ClientKind, COOKIES, safeNext } from "@/lib/auth/config";
import { safeEqual } from "@/lib/auth/pkce";
import { codeGrant, exchange, setSession } from "@/lib/auth/session";

type Pending = { state: string; verifier: string; client: ClientKind; next: string };

function parsePending(raw: string | undefined): Pending | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<Pending>;
    if (
      typeof value.state === "string" &&
      typeof value.verifier === "string" &&
      (value.client === "office" || value.client === "portal") &&
      typeof value.next === "string"
    ) {
      return value as Pending;
    }
  } catch {
    /* fall through */
  }
  return null;
}

function failed(config: ReturnType<typeof authConfig>, reason: string) {
  const response = NextResponse.redirect(new URL(`/auth/error?reason=${reason}`, config.appBaseUrl));
  response.cookies.set(COOKIES.oauth, "", { path: "/auth", maxAge: 0 });
  return response;
}

/** Finish sign-in: verify state, exchange the code server-side, store tokens in HttpOnly cookies. */
export async function GET(request: NextRequest) {
  const config = authConfig();
  const pending = parsePending(request.cookies.get(COOKIES.oauth)?.value);
  const state = request.nextUrl.searchParams.get("state") ?? "";
  const code = request.nextUrl.searchParams.get("code");
  if (!pending || !code || !safeEqual(state, pending.state)) return failed(config, "state");

  const tokens = await exchange(config, codeGrant(config, pending.client, code, pending.verifier));
  if (!tokens) return failed(config, "exchange");

  const response = NextResponse.redirect(new URL(safeNext(pending.next, "/"), config.appBaseUrl));
  setSession(response, config, pending.client, tokens);
  response.cookies.set(COOKIES.oauth, "", { path: "/auth", maxAge: 0 });
  return response;
}
