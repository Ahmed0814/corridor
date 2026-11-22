import { describe, expect, it } from "vitest";

import { etaView, plausibleToken, safeNotificationLink, signaturePayload, trackingUrl, validRadius } from "./phase6";

describe("tracking links", () => {
  it("puts the token in the path", () => {
    expect(trackingUrl("https://corridor.example/", "abc_DEF-123")).toBe("https://corridor.example/track/abc_DEF-123");
  });

  it("rejects implausible tokens before calling the API", () => {
    expect(plausibleToken("a".repeat(43))).toBe(true);
    expect(plausibleToken("short")).toBe(false);
    expect(plausibleToken("../../etc/passwd-aaaaaaaaaaaaaaaa")).toBe(false);
    expect(plausibleToken("a".repeat(200))).toBe(false);
  });
});

describe("etaView", () => {
  it("never invents an ETA", () => {
    expect(etaView({ eta: null, eta_method: "" })).toEqual({ kind: "none" });
    expect(etaView({ eta: null, eta_method: "unavailable_no_destination" })).toEqual({ kind: "no_destination" });
  });

  it("shows the basis of an estimate", () => {
    expect(
      etaView({
        eta: "2026-11-22T10:00:00Z",
        eta_method: "deterministic_v1",
        eta_remaining_km: 120.5,
        eta_basis_recorded_at: "2026-11-22T07:00:00Z",
      }),
    ).toEqual({ kind: "estimate", eta: "2026-11-22T10:00:00Z", remainingKm: 120.5, basisRecordedAt: "2026-11-22T07:00:00Z" });
  });
});

describe("signaturePayload", () => {
  it("rounds and clamps points inside the pad", () => {
    expect(
      signaturePayload(300.4, 100, [
        [
          [-5, 10.6],
          [400, 50],
        ],
      ]),
    ).toEqual({
      width: 300,
      height: 100,
      strokes: [
        [
          [0, 11],
          [300, 50],
        ],
      ],
    });
  });

  it("refuses an empty or single-point signature", () => {
    expect(signaturePayload(300, 100, [])).toBeNull();
    expect(signaturePayload(300, 100, [[[1, 1]]])).toBeNull();
    expect(
      signaturePayload(0, 100, [
        [
          [1, 1],
          [2, 2],
        ],
      ]),
    ).toBeNull();
  });
});

describe("notification links", () => {
  it("only allows internal shipment links", () => {
    expect(safeNotificationLink("/ops/shipments/123e4567-e89b-12d3-a456-426614174000")).not.toBeNull();
    expect(safeNotificationLink("https://evil.example")).toBeNull();
    expect(safeNotificationLink("javascript:alert(1)")).toBeNull();
    expect(safeNotificationLink("//evil.example/ops/shipments/x")).toBeNull();
  });
});

describe("validRadius", () => {
  it("matches the API bounds", () => {
    expect(validRadius(50)).toBe(true);
    expect(validRadius(20_000)).toBe(true);
    expect(validRadius(49)).toBe(false);
    expect(validRadius(Number.NaN)).toBe(false);
  });
});
