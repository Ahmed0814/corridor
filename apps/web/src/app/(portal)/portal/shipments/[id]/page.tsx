import Link from "next/link";
import { notFound } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";

import { apiGet } from "@/lib/api";
import type { LifecycleEvent, Shipment } from "@/lib/logistics";
import { ShipmentMap } from "@/components/shipment-map";
import { type DocumentInfo, etaView, type PublicPosition } from "@/lib/phase6";

import { formatDate, StatusBadge } from "../../../../(ops)/ops/_components/ui";

const STYLE_URL = process.env.NEXT_PUBLIC_MAP_STYLE_URL ?? "https://demotiles.maplibre.org/style.json";
const ON_THE_ROAD = new Set(["dispatched", "in_transit", "at_border"]);

// Customer-facing milestones only: no actors, reasons or internal events.
const CUSTOMER_EVENTS = new Set([
  "created",
  "confirmed",
  "dispatched",
  "in_transit",
  "border_arrived",
  "border_cleared",
  "delivery_failed",
  "delivery_reattempt",
  "delivered",
  "cancelled",
]);

export default async function PortalShipment({ params }: PageProps<"/portal/shipments/[id]">) {
  const { id } = await params;
  const t = await getTranslations("Portal");
  const locale = await getLocale();
  const sid = encodeURIComponent(id);
  const [shipment, events, documents, position] = await Promise.all([
    apiGet<Shipment>(`/shipments/${sid}`),
    apiGet<LifecycleEvent[]>(`/shipments/${sid}/events`),
    apiGet<DocumentInfo[]>(`/shipments/${sid}/documents`),
    apiGet<{ position: PublicPosition | null }>(`/shipments/${sid}/position`),
  ]);
  if (!shipment.ok) {
    if (shipment.status === 404 || shipment.status === 422) notFound();
    return (
      <p role="alert" className="text-sm">
        {t("error")} <code>{shipment.error.code}</code>
      </p>
    );
  }
  const s = shipment.data;
  const eta = etaView(s);
  const milestones = (events.ok ? events.data : []).filter((e) => CUSTOMER_EVENTS.has(e.type));

  return (
    <section>
      <Link href="/portal" prefetch={false} className="text-sm underline-offset-4 hover:underline">
        ← {t("back")}
      </Link>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">{s.reference}</h1>
        <StatusBadge status={s.status} />
        {s.is_delayed ? <span className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-900">{t("delayed")}</span> : null}
      </div>
      <dl className="mt-4 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-muted-foreground">{t("route")}</dt>
          <dd>
            {s.origin_label} → {s.destination_label}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("eta")}</dt>
          <dd>
            {eta.kind === "estimate" ? (
              <>
                {formatDate(eta.eta, locale)}
                <span className="ms-2 text-xs text-muted-foreground">{t("etaBasis", { at: formatDate(eta.basisRecordedAt, locale) })}</span>
              </>
            ) : (
              "—"
            )}
          </dd>
        </div>
        {s.status === "delivered" ? (
          <div>
            <dt className="text-muted-foreground">{t("delivered")}</dt>
            <dd>
              {formatDate(s.delivered_at, locale)} · {s.recipient_name}
            </dd>
          </div>
        ) : null}
      </dl>

      {ON_THE_ROAD.has(s.status) ? (
        <section className="mt-8 space-y-2">
          <h2 className="text-base font-semibold">{t("whereIs")}</h2>
          <ShipmentMap
            initial={position.ok ? position.data.position : null}
            pollUrl={`/portal/shipments/${s.id}/position`}
            styleUrl={STYLE_URL}
            locale={locale}
            labels={{
              title: t("whereIs"),
              noPosition: t("noPosition"),
              recorded: t("recorded", { at: "{at}" }),
              received: t("received", { at: "{at}" }),
              precision: t("precision"),
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

      <h2 className="mt-8 text-base font-semibold">{t("documents")}</h2>
      {documents.ok && documents.data.length > 0 ? (
        <ul className="mt-2 space-y-1 text-sm">
          {documents.data.map((d) => (
            <li key={d.id}>
              <a href={`/portal/documents/${d.id}`} target="_blank" rel="noreferrer" className="underline-offset-4 hover:underline">
                {t(`documentKind.${d.kind}`)}
              </a>
              <span className="ms-2 text-xs text-muted-foreground">{formatDate(d.created_at, locale)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-muted-foreground">{t("noDocuments")}</p>
      )}

      <h2 className="mt-8 text-base font-semibold">{t("timeline")}</h2>
      <ol className="mt-2 space-y-2 border-s ps-4 text-sm">
        {milestones.map((e) => (
          <li key={e.id}>
            <span className="font-medium">{t(`milestone.${e.type}`)}</span>
            <span className="ms-2 text-xs text-muted-foreground">{formatDate(e.occurred_at, locale)}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
