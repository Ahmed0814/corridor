import { describe, expect, it } from "vitest";

import { groupSecret, mfaMode, otpauthUri, validCode } from "./mfa";

describe("mfaMode", () => {
  it("detects a Cognito hosted domain and its region", () => {
    expect(mfaMode("https://corridor-test-0438.auth.ca-central-1.amazoncognito.com/oauth2/token")).toEqual({
      kind: "cognito",
      region: "ca-central-1",
    });
  });

  it("treats anything else as the local issuer", () => {
    expect(mfaMode("http://127.0.0.1:8000/dev-auth/token")).toEqual({ kind: "local" });
    expect(mfaMode(undefined)).toEqual({ kind: "local" });
    expect(mfaMode("https://evil.example/x.auth.us-east-1.amazoncognito.com/")).toEqual({ kind: "local" });
  });
});

describe("otpauthUri", () => {
  it("builds a standard TOTP URI", () => {
    expect(otpauthUri("ABCD2345", "owner@demo.test")).toBe(
      "otpauth://totp/Corridor%3Aowner%40demo.test?secret=ABCD2345&issuer=Corridor",
    );
  });
});

describe("helpers", () => {
  it("groups the secret and validates codes", () => {
    expect(groupSecret("ABCDEFGHIJ")).toBe("ABCD EFGH IJ");
    expect(validCode("123456")).toBe(true);
    expect(validCode("12345")).toBe(false);
    expect(validCode("12a456")).toBe(false);
  });
});
