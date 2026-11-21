import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import { LOCALE_COOKIE, resolveLocale } from "./config";

export default getRequestConfig(async () => {
  const cookieStore = await cookies();
  const headerStore = await headers();
  const locale = resolveLocale(cookieStore.get(LOCALE_COOKIE)?.value, headerStore.get("accept-language"));
  return {
    locale,
    // Store UTC, display East Africa Time by default (DECISIONS D-020).
    timeZone: "Africa/Djibouti",
    messages: (await import(`../../messages/${locale}.json`)).default,
  };
});
