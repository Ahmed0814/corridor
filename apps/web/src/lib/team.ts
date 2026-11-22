// Team management types and pure helpers (unit-tested in team.test.ts).

export const ROLES = ["owner", "admin", "ops_manager", "dispatcher", "fleet_manager", "finance", "driver", "customer"] as const;
export type Role = (typeof ROLES)[number];

export type Member = {
  id: string;
  user_id: string;
  display_name: string;
  email: string | null;
  phone_masked: string | null;
  role: Role;
  status: "invited" | "active" | "suspended" | string;
  created_at: string;
  activated_at: string | null;
  driver_id: string | null;
  customer_id: string | null;
};

/** Roles a user may hand out: only an owner can create or manage owners (the API enforces it too). */
export function assignableRoles(myRole: string | null | undefined): Role[] {
  return myRole === "owner" ? [...ROLES] : ROLES.filter((r) => r !== "owner");
}

/** What a member still needs before they can use the product. */
export function memberNeedsLink(m: Pick<Member, "role" | "driver_id" | "customer_id">): "driver" | "customer" | null {
  if (m.role === "driver" && !m.driver_id) return "driver";
  if (m.role === "customer" && !m.customer_id) return "customer";
  return null;
}

/** Driver profiles that are not linked to any account yet (one account per profile). */
export function unlinkedDrivers<T extends { id: string; membership_id: string | null }>(drivers: T[]): T[] {
  return drivers.filter((d) => !d.membership_id);
}
