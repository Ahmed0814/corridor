import { describe, expect, it } from "vitest";

import { errorQuery, invalidFields, normalizePhone } from "./forms";

describe("normalizePhone", () => {
  it("removes spaces and punctuation and turns 00 into +", () => {
    expect(normalizePhone("+253 77 12 34 56")).toBe("+25377123456");
    expect(normalizePhone("00253-77-12-34-56")).toBe("+25377123456");
    expect(normalizePhone("(+251) 911.234.567")).toBe("+251911234567");
    expect(normalizePhone("  ")).toBe("");
  });

  it("leaves local numbers for the API to reject with a field error", () => {
    expect(normalizePhone("77 12 34 56")).toBe("77123456");
  });
});

describe("invalidFields", () => {
  it("extracts field names from Pydantic errors", () => {
    const details = [
      { loc: ["body", "payload", "phone_e164"], msg: "String should match pattern" },
      { loc: ["body", "payload", "email"], msg: "x" },
      { loc: ["body", "payload", "phone_e164"], msg: "dup" },
    ];
    expect(invalidFields(details)).toEqual(["phone_e164", "email"]);
    expect(invalidFields(null)).toEqual([]);
    expect(invalidFields([{ loc: ["body", "<script>"] }])).toEqual([]);
  });
});

describe("errorQuery", () => {
  it("carries code, reference and fields", () => {
    expect(errorQuery({ code: "validation_error", message: "", requestId: "r1", fields: ["phone_e164"] })).toBe(
      "error=validation_error&ref=r1&fields=phone_e164",
    );
  });
});
