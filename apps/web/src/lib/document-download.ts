import { NextResponse } from "next/server";

import { apiFetchRaw } from "@/lib/api-files";

/**
 * Stream a document from the API to the browser. The API checks who may see it (tenant, scope,
 * customer visibility); this only forwards the bytes with safe headers.
 */
export async function downloadDocument(id: string): Promise<Response> {
  if (!/^[0-9a-f-]{36}$/i.test(id)) return new NextResponse(null, { status: 404 });
  const upstream = await apiFetchRaw(`/documents/${id}/content`);
  if (!upstream) return new NextResponse(null, { status: 401 });
  if (!upstream.ok) return new NextResponse(null, { status: upstream.status === 404 ? 404 : upstream.status });
  const type = upstream.headers.get("content-type") ?? "application/octet-stream";
  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": type,
      "Content-Disposition": upstream.headers.get("content-disposition") ?? "attachment",
      "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy": "default-src 'none'; img-src 'self'; sandbox",
    },
  });
}
