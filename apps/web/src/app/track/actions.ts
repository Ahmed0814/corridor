"use server";

import { apiPublicPost } from "@/lib/api-files";
import type { PublicTracking } from "@/lib/phase6";

export type LookupState = {
  view?: PublicTracking;
  query?: { container_number: string; reference: string };
  error?: "not_found" | "rate_limited" | "invalid" | "unavailable";
};

/** Public lookup: container number AND shipment reference (D-075). Results never go into a URL. */
export async function lookupContainer(_prev: LookupState, form: FormData): Promise<LookupState> {
  const container = String(form.get("container_number") ?? "").replace(/\s+/g, "").toUpperCase();
  const reference = String(form.get("reference") ?? "").replace(/\s+/g, "").toUpperCase();
  if (container.length < 11 || container.length > 13 || reference.length < 3) return { error: "invalid" };
  const query = { container_number: container, reference };
  const result = await apiPublicPost<PublicTracking>("/public/track", query);
  if (result.ok) return { view: result.data, query };
  if (result.status === 404) return { error: "not_found" };
  if (result.status === 429) return { error: "rate_limited" };
  if (result.status === 422) return { error: "invalid" };
  return { error: "unavailable" };
}
