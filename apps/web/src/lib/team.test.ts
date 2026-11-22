import { describe, expect, it } from "vitest";

import { assignableRoles, memberNeedsLink, unlinkedDrivers } from "./team";

describe("assignableRoles", () => {
  it("only owners can hand out the owner role", () => {
    expect(assignableRoles("owner")).toContain("owner");
    expect(assignableRoles("admin")).not.toContain("owner");
    expect(assignableRoles("admin")).toContain("driver");
  });
});

describe("memberNeedsLink", () => {
  it("drivers and customers need a profile link", () => {
    expect(memberNeedsLink({ role: "driver", driver_id: null, customer_id: null })).toBe("driver");
    expect(memberNeedsLink({ role: "driver", driver_id: "d", customer_id: null })).toBeNull();
    expect(memberNeedsLink({ role: "customer", driver_id: null, customer_id: null })).toBe("customer");
    expect(memberNeedsLink({ role: "dispatcher", driver_id: null, customer_id: null })).toBeNull();
  });
});

describe("unlinkedDrivers", () => {
  it("offers only driver profiles without an account", () => {
    expect(unlinkedDrivers([{ id: "a", membership_id: null }, { id: "b", membership_id: "m" }]).map((d) => d.id)).toEqual(["a"]);
  });
});
