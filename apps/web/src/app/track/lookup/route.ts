import { type NextRequest, NextResponse } from "next/server";

import { apiPublicPost } from "@/lib/api-files";
import type { PublicTracking } from "@/lib/phase6";

// Map refresh for the public container lookup: POST {container_number, reference} (never in a URL).
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => null)) as { container_number?: unknown; reference?: unknown } | null;
  const container_number = typeof body?.container_number === "string" ? body.container_number.slice(0, 20) : "";
  const reference = typeof body?.reference === "string" ? body.reference.slice(0, 60) : "";
  if (!container_number || !reference) return new NextResponse(null, { status: 400 });
  const result = await apiPublicPost<PublicTracking>("/public/track", { container_number, reference });
  if (!result.ok) return new NextResponse(null, { status: result.status === 404 ? 404 : result.status || 502 });
  return NextResponse.json(
    { position: result.data.position ?? null },
    { headers: { "Cache-Control": "no-store", "Referrer-Policy": "no-referrer" } },
  );
}
