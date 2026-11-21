import { describe, expect, it } from "vitest";

import { defaultLocale, resolveLocale, textDirection } from "./config";

describe("resolveLocale", () => {
  it("prefers a supported cookie value", () => {
    expect(resolveLocale("fr", "en-US,en;q=0.9")).toBe("fr");
  });

  it("ignores an unsupported cookie and falls back to Accept-Language", () => {
    expect(resolveLocale("xx", "fr-DJ,fr;q=0.9,en;q=0.8")).toBe("fr");
  });

  it("skips unsupported languages in Accept-Language order", () => {
    expect(resolveLocale(undefined, "am-ET,so;q=0.9,en;q=0.5")).toBe("en");
  });

  it("falls back to the default locale", () => {
    expect(resolveLocale(null, null)).toBe(defaultLocale);
    expect(resolveLocale(undefined, "")).toBe(defaultLocale);
  });
});

describe("textDirection", () => {
  it("is ltr for pilot languages and rtl for Arabic", () => {
    expect(textDirection("en")).toBe("ltr");
    expect(textDirection("fr")).toBe("ltr");
    expect(textDirection("ar")).toBe("rtl");
  });
});

describe("message catalogues", () => {
  it("have identical keys in every language", async () => {
    const flatten = (obj: Record<string, unknown>, prefix = ""): string[] =>
      Object.entries(obj).flatMap(([k, v]) =>
        v && typeof v === "object" ? flatten(v as Record<string, unknown>, `${prefix}${k}.`) : [`${prefix}${k}`],
      );
    const en = flatten((await import("../../messages/en.json")).default);
    const fr = flatten((await import("../../messages/fr.json")).default);
    expect(fr.sort()).toEqual(en.sort());
  });
});
