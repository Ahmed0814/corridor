import { type Area, areaForPath, clientForArea, type ClientKind } from "./config";

export type GateInput = {
  pathname: string;
  search: string;
  hasAccess: boolean;
  hasRefresh: boolean;
  client: string | undefined;
};

export type GateDecision = { action: "allow" } | { action: "redirect"; location: string };

/**
 * Optimistic, cookie-only check run by proxy.ts before protected pages render. It only decides
 * whether to send the user to sign in; real authorization happens in the API on every request
 * (tenant membership, role, MFA, client kind).
 */
export function gate({ pathname, search, hasAccess, hasRefresh, client }: GateInput): GateDecision {
  const area: Area | null = areaForPath(pathname);
  if (area === null) return { action: "allow" };
  const next = encodeURIComponent(`${pathname}${search}`);
  const wanted: ClientKind = clientForArea(area);
  // A portal session cannot open staff areas and vice versa: sign in with the right client.
  if (client !== undefined && client !== wanted) {
    return { action: "redirect", location: `/auth/login?area=${area}&next=${next}` };
  }
  if (hasAccess && client === wanted) return { action: "allow" };
  if (hasRefresh && client === wanted) return { action: "redirect", location: `/auth/refresh?next=${next}` };
  return { action: "redirect", location: `/auth/login?area=${area}&next=${next}` };
}
