import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";

import { apiPublicGet } from "@/lib/api-files";
import { ShipmentMap } from "@/components/shipment-map";
import { type PublicTracking, plausibleToken } from "@/lib/phase6";
import { DEFAULT_MAP_STYLE } from "@/lib/tracking";

// Public tracking page (security-model.md §6): no sign-in, only the fields the link allows,
// coarse position with its recorded and received times. Never indexed, never leaks the URL.
export const dynamic = "force-dynamic";

const STYLE_URL = process.env.NEXT_PUBLIC_MAP_STYLE_URL ?? DEFAULT_MAP_STYLE;

export const metadata: Metadata = {
  title: "Shipment tracking",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

function when(iso: string | null | undefined, locale: string): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short", timeZone: "Africa/Djibouti" }).format(
    new Date(iso),
  );
}

export default async function TrackPage({ params }: PageProps<"/track/[token]">) {
  const { token } = await params;
  if (!plausibleToken(token)) notFound();
  const t = await getTranslations("Track");
  const locale = await getLocale();
  const result = await apiPublicGet<PublicTracking>(`/public/tracking/${encodeURIComponent(token)}`);
  if (!result.ok) {
    if (result.status === 404) notFound();
    return (
      <main className="mx-auto max-w-xl p-6">
        <p role="alert">{result.status === 429 ? t("rateLimited") : t("unavailable")}</p>
      </main>
    );
  }
  const v = result.data;
  const statusLabel = v.status && t.has(`status.${v.status}`) ? t(`status.${v.status}`) : v.status;

  return (
    <main className="mx-auto max-w-xl space-y-6 p-6">
      <header>
        <p className="text-sm text-muted-foreground">{t("heading")}</p>
        <h1 className="text-2xl font-semibold">{v.reference}</h1>
        {statusLabel ? (
          <p className="mt-1 text-lg">
            {statusLabel}
            {v.is_delayed ? <span className="ms-2 rounded bg-amber-100 px-2 py-0.5 text-sm text-amber-900">{t("delayed")}</span> : null}
          </p>
        ) : null}
      </header>

      {v.origin_label ? (
        <p>
          {v.origin_label} → {v.destination_label}
        </p>
      ) : null}

      {v.eta ? (
        <section>
          <h2 className="text-sm font-medium text-muted-foreground">{t("eta")}</h2>
          <p>{when(v.eta, locale)}</p>
          <p className="text-xs text-muted-foreground">{t("etaNote")}</p>
        </section>
      ) : null}

      {v.delivered_at ? (
        <section>
          <h2 className="text-sm font-medium text-muted-foreground">{t("delivered")}</h2>
          <p>{when(v.delivered_at, locale)}</p>
        </section>
      ) : null}

      {"position" in v ? (
        <section className="space-y-2">
          <h2 className="text-sm font-medium text-muted-foreground">{t("position")}</h2>
          <ShipmentMap
            initial={v.position ?? null}
            pollUrl={`/track/${encodeURIComponent(token)}/position`}
            styleUrl={STYLE_URL}
            locale={locale}
            labels={{
              title: t("position"),
              noPosition: t("noPosition"),
              recorded: t("recorded", { at: "{at}" }),
              received: t("received", { at: "{at}" }),
              precision: t("precision", { km: 1 }),
              freshness: {
                live: t("freshness.live"),
                delayed: t("freshness.delayed"),
                stale: t("freshness.stale"),
                offline: t("freshness.offline"),
              },
              basemap: t("basemap"),
            }}
          />
        </section>
      ) : null}

      {v.timeline && v.timeline.length > 0 ? (
        <section>
          <h2 className="text-sm font-medium text-muted-foreground">{t("timeline")}</h2>
          <ol className="mt-2 space-y-1 border-s ps-4 text-sm">
            {v.timeline.map((item, i) => (
              <li key={`${item.at}-${i}`}>
                {item.label} <span className="text-xs text-muted-foreground">{when(item.at, locale)}</span>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      <footer className="text-xs text-muted-foreground">{t("footer")}</footer>
    </main>
  );
}
