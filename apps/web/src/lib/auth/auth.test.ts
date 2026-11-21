import { describe, expect, it } from "vitest";

import { sessionState } from "@/components/area-layout";
import type { Me } from "@/lib/api";

import { areaForPath, authConfig, clientForArea, isSameOrigin, safeNext } from "./config";
import { gate } from "./gate";
import { codeChallenge, randomToken, safeEqual } from "./pkce";

describe("PKCE", () => {
  it("matches the RFC 7636 appendix B test vector", async () => {
    expect(await codeChallenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")).toBe(
      "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
    );
  });

  it("generates url-safe random values of the requested strength", () => {
    const token = randomToken(32);
    expect(token).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(randomToken(32)).not.toBe(token);
  });

  it("compares state values", () => {
    expect(safeEqual("abc", "abc")).toBe(true);
    expect(safeEqual("abc", "abd")).toBe(false);
    expect(safeEqual("abc", "abcd")).toBe(false);
  });
});

describe("safeNext (no open redirects)", () => {
  it.each([
    ["/ops", "/ops"],
    ["/ops/shipments?status=active", "/ops/shipments?status=active"],
    ["//evil.example/path", "/fallback"],
    ["https://evil.example", "/fallback"],
    ["/\\evil.example", "/fallback"],
    ["javascript:alert(1)", "/fallback"],
    ["", "/fallback"],
    [null, "/fallback"],
  ])("%s -> %s", (input, expected) => {
    expect(safeNext(input, "/fallback")).toBe(expected);
  });
});

describe("areas and clients", () => {
  it("maps paths to areas and areas to Cognito clients", () => {
    expect(areaForPath("/ops/fleet")).toBe("ops");
    expect(areaForPath("/portal")).toBe("portal");
    expect(areaForPath("/status")).toBeNull();
    expect(clientForArea("portal")).toBe("portal");
    expect(clientForArea("ops")).toBe("office");
    expect(clientForArea("admin")).toBe("office");
  });

  it("requires every auth setting", () => {
    expect(() => authConfig({ NODE_ENV: "test" })).toThrow(/APP_BASE_URL/);
  });

  it("checks the Origin of POSTs", () => {
    const config = authConfig({
      NODE_ENV: "test",
      APP_BASE_URL: "https://app.example",
      AUTH_AUTHORIZE_URL: "x",
      AUTH_TOKEN_URL: "x",
      AUTH_LOGOUT_URL: "x",
      AUTH_CLIENT_ID_OFFICE: "o",
      AUTH_CLIENT_ID_PORTAL: "p",
    });
    expect(config.secureCookies).toBe(true);
    expect(isSameOrigin("https://app.example", config)).toBe(true);
    expect(isSameOrigin("https://evil.example", config)).toBe(false);
    expect(isSameOrigin(null, config)).toBe(false);
  });
});

describe("gate (proxy decision)", () => {
  const base = { search: "", hasAccess: false, hasRefresh: false, client: undefined };

  it("leaves public pages alone", () => {
    expect(gate({ ...base, pathname: "/" })).toEqual({ action: "allow" });
    expect(gate({ ...base, pathname: "/status" })).toEqual({ action: "allow" });
  });

  it("sends anonymous users to sign in with the right area", () => {
    expect(gate({ ...base, pathname: "/portal", search: "?x=1" })).toEqual({
      action: "redirect",
      location: "/auth/login?area=portal&next=%2Fportal%3Fx%3D1",
    });
  });

  it("allows a matching session and refreshes an expired one", () => {
    expect(gate({ ...base, pathname: "/ops", hasAccess: true, client: "office" })).toEqual({ action: "allow" });
    expect(gate({ ...base, pathname: "/ops", hasRefresh: true, client: "office" })).toEqual({
      action: "redirect",
      location: "/auth/refresh?next=%2Fops",
    });
  });

  it("never lets a portal session into staff areas (or the reverse)", () => {
    expect(gate({ ...base, pathname: "/admin", hasAccess: true, client: "portal" }).action).toBe("redirect");
    expect(gate({ ...base, pathname: "/portal", hasAccess: true, client: "office" }).action).toBe("redirect");
  });
});

describe("sessionState", () => {
  const me: Me = {
    user_id: "u",
    display_name: "TEST user",
    email: "u@x.test",
    is_platform_admin: false,
    mfa_verified: false,
    client: "web-office",
    active_tenant: {
      tenant_id: "t",
      tenant_slug: "alpha",
      tenant_name: "Alpha",
      tenant_status: "active",
      role: "dispatcher",
      status: "active",
    },
    permissions: ["tenant.read"],
    mfa_required: false,
    memberships: [],
  };

  it("shows API problems instead of redirecting", () => {
    const rejected = sessionState({ ok: false, status: 401, error: { code: "unauthenticated", message: "", requestId: "r1" } }, "ops");
    expect(rejected).toEqual({ kind: "problem", code: "session_rejected", requestId: "r1" });
    const suspended = sessionState(
      { ok: false, status: 403, error: { code: "tenant_suspended", message: "", requestId: null } },
      "ops",
    );
    expect(suspended).toEqual({ kind: "problem", code: "tenant_suspended", requestId: null });
  });

  it("requires the platform admin flag for /admin and a company elsewhere", () => {
    expect(sessionState({ ok: true, data: me }, "admin")).toMatchObject({ code: "not_platform_admin" });
    expect(sessionState({ ok: true, data: { ...me, active_tenant: null } }, "ops")).toMatchObject({ code: "no_membership" });
    expect(sessionState({ ok: true, data: me }, "ops")).toEqual({ kind: "ready", me });
  });
});
