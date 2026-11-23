import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";

import { DEFAULT_MAP_STYLE } from "@/lib/tracking";

import { LookupForm } from "./lookup-form";

// Public "Track a container" page (D-075): container number AND shipment reference.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Track a container",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

const STYLE_URL = process.env.NEXT_PUBLIC_MAP_STYLE_URL ?? DEFAULT_MAP_STYLE;

export default async function TrackLookupPage() {
  const t = await getTranslations("Track");
  const locale = await getLocale();
  return (
    <main className="mx-auto max-w-2xl space-y-4 p-6">
      <h1 className="text-2xl font-semibold">{t("lookup.title")}</h1>
      <p className="text-sm text-muted-foreground">{t("lookup.intro")}</p>
      <LookupForm locale={locale} styleUrl={STYLE_URL} />
      <footer className="text-xs text-muted-foreground">{t("footer")}</footer>
    </main>
  );
}
