import { getLocale, getTranslations } from "next-intl/server";

import { apiGet } from "@/lib/api";
import { DEFAULT_MAP_STYLE, type FleetSnapshot } from "@/lib/tracking";

import { ActionError, OpsNav } from "../_components/ui";
import { LiveMap, type LiveMapLabels } from "./live-map";

// Default: OpenFreeMap street style (OpenStreetMap data, D-060). Production points this at the
// self-hosted PMTiles style (DECISIONS D-028); OpenStreetMap's own tile servers are not used.
const STYLE_URL = process.env.NEXT_PUBLIC_MAP_STYLE_URL ?? DEFAULT_MAP_STYLE;

export default async function MapPage() {
  const t = await getTranslations("Ops.map");
  const locale = await getLocale();
  const snapshot = await apiGet<FleetSnapshot>("/tracking/fleet");
  const keys = [
    "live", "delayed", "stale", "offline", "vehicle", "freshness", "recorded", "received", "accuracy", "age", "none",
    "feedStale", "updated", "basemap",
  ] as const;
  const labels = Object.fromEntries(keys.map((k) => [k, t.raw(k) as string])) as LiveMapLabels;

  return (
    <section>
      <OpsNav current="map" />
      <h1 className="text-xl font-semibold">{t("title")}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{t("intro")}</p>
      {snapshot.ok ? null : <ActionError code={snapshot.error.code} requestId={snapshot.error.requestId ?? undefined} />}
      <div className="mt-4">
        <LiveMap initial={snapshot.ok ? snapshot.data : null} styleUrl={STYLE_URL} locale={locale} labels={labels} />
      </div>
    </section>
  );
}
