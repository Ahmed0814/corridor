import { type NextRequest, NextResponse } from "next/server";

import { apiGet } from "@/lib/api";
import type { PublicPosition } from "@/lib/phase6";

// Same-origin polling endpoint for the portal map. The API decides whether this customer may see
// the shipment; the token stays in the HttpOnly cookie.
export const dynamic = "force-dynamic";

export async function GET(_req: NextRequest, ctx: RouteContext<"/portal/shipments/[id]/position">) {
  const { id } = await ctx.params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) return new NextResponse(null, { status: 404 });
  const result = await apiGet<{ position: PublicPosition | null }>(`/shipments/${id}/position`);
  if (!result.ok) return new NextResponse(null, { status: result.status || 502 });
  return NextResponse.json(result.data, { headers: { "Cache-Control": "no-store" } });
}
