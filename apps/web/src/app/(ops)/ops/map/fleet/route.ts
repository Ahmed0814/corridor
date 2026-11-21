import { NextResponse } from "next/server";

import { apiGet } from "@/lib/api";
import type { FleetSnapshot } from "@/lib/tracking";

// Same-origin JSON for the live map's polling. The access token stays in the HttpOnly cookie and is
// used server-side only; the browser never sees it (security-model.md §2).
export const dynamic = "force-dynamic";

export async function GET() {
  const result = await apiGet<FleetSnapshot>("/tracking/fleet");
  if (!result.ok) {
    return NextResponse.json(
      { error: { code: result.error.code, request_id: result.error.requestId } },
      { status: result.status || 502, headers: { "Cache-Control": "no-store" } },
    );
  }
  return NextResponse.json(result.data, { headers: { "Cache-Control": "no-store" } });
}
