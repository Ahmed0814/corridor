import type { NextRequest } from "next/server";

import { downloadDocument } from "@/lib/document-download";

export const dynamic = "force-dynamic";

export async function GET(_req: NextRequest, ctx: RouteContext<"/ops/documents/[id]">) {
  const { id } = await ctx.params;
  return downloadDocument(id);
}
