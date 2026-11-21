// UI languages. English and French ship in the pilot; Arabic (RTL), Amharic, Afar and
// Somali are added by dropping a messages/<locale>.json file and extending this list.
export const locales = ["en", "fr"] as const;
export type Locale = (typeof locales)[number];
export const defaultLocale: Locale = "en";
export const LOCALE_COOKIE = "corridor_locale";

const RTL_LOCALES = new Set(["ar"]);

export function isLocale(value: string | undefined | null): value is Locale {
  return !!value && (locales as readonly string[]).includes(value);
}

export function textDirection(locale: string): "ltr" | "rtl" {
  return RTL_LOCALES.has(locale) ? "rtl" : "ltr";
}

/** Cookie wins; otherwise the first supported language in Accept-Language; else default. */
export function resolveLocale(cookieValue?: string | null, acceptLanguage?: string | null): Locale {
  if (isLocale(cookieValue)) return cookieValue;
  for (const part of (acceptLanguage ?? "").split(",")) {
    const tag = part.split(";")[0]?.trim().toLowerCase().split("-")[0];
    if (isLocale(tag)) return tag;
  }
  return defaultLocale;
}
