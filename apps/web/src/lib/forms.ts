// Form helpers shared by server actions (pure, unit-tested in forms.test.ts).

import type { ApiError } from "@/lib/api";

/**
 * Phone numbers as the API expects them (E.164): "+25377 12 34 56", "00253-77-12-34-56" and
 * "(+253) 77123456" all become "+25377123456". Empty stays empty. Anything else is passed through
 * unchanged so the API can reject it with a clear field error.
 */
export function normalizePhone(raw: string): string {
  const compact = raw.trim().replace(/[\s().-]/g, "");
  if (compact === "") return "";
  if (compact.startsWith("00")) return `+${compact.slice(2)}`;
  return compact;
}

/** Field names from a validation error's details (Pydantic `loc`, last element). */
export function invalidFields(details: unknown): string[] {
  if (!Array.isArray(details)) return [];
  const names = details
    .map((d) => (d && typeof d === "object" && Array.isArray((d as { loc?: unknown }).loc) ? (d as { loc: unknown[] }).loc : []))
    .map((loc) => loc[loc.length - 1])
    .filter((n): n is string => typeof n === "string" && /^[a-z_][a-z0-9_]*$/i.test(n));
  return [...new Set(names)].slice(0, 5);
}

/** ?error=<code>&ref=<request id>&fields=<a,b> for redirect-based form errors. */
export function errorQuery(error: ApiError): string {
  const q = new URLSearchParams({ error: error.code });
  if (error.requestId) q.set("ref", error.requestId);
  if (error.fields?.length) q.set("fields", error.fields.join(","));
  return q.toString();
}
