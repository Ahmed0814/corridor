import { type NextRequest, NextResponse } from "next/server";

import { apiPublicGet } from "@/lib/api-files";
import { plausibleToken, type PublicTracking } from "@/lib/phase6";

// Same-origin polling endpoint for the public tracking map: only the (already allowlisted,
// rounded) position of that link. Invalid, expired and revoked links answer 404.
export const dynamic = "force-dynamic";

export async function GET(_req: NextRequest, ctx: RouteContext<"/track/[token]/position">) {
  const { token } = await ctx.params;
  if (!plausibleToken(token)) return new NextResponse(null, { status: 404 });
  const result = await apiPublicGet<PublicTracking>(`/public/tracking/${encodeURIComponent(token)}`);
  if (!result.ok) return new NextResponse(null, { status: result.status === 404 ? 404 : 502 });
  return NextResponse.json(
    { position: result.data.position ?? null },
    { headers: { "Cache-Control": "no-store", "Referrer-Policy": "no-referrer" } },
  );
}
