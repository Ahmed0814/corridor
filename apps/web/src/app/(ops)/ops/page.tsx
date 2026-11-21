import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import { type Me, apiGet } from "@/lib/api";
import type { Page, Shipment, ShipmentStatus, Trip } from "@/lib/logistics";

import { formatDate, OpsNav, StatusBadge } from "./_components/ui";

const ORDER: ShipmentStatus[] = ["draft", "confirmed", "dispatched", "in_transit", "at_border", "delivery_failed", "delivered"];

export default async function OpsOverview() {
  const t = await getTranslations("Ops");
  const locale = await getLocale();
  const [me, shipments, trips] = await Promise.all([
    apiGet<Me>("/me"),
    apiGet<Page<Shipment>>("/shipments?limit=200"),
    apiGet<Page<Trip>>("/trips?limit=200"),
  ]);
  const items = shipments.ok ? shipments.data.items : [];
  const counts = new Map<string, number>();
  for (const s of items) counts.set(s.status, (counts.get(s.status) ?? 0) + 1);
  const delayed = items.filter((s) => s.is_delayed).length;
  const openTrips = trips.ok
    ? trips.data.items.filter((x) => ["planned", "assigned", "in_progress", "paused"].includes(x.status)).length
    : 0;

  return (
    <section>
      <OpsNav current="overview" />
      <h1 className="text-xl font-semibold">{t("overview.title")}</h1>
      {me.ok ? <p className="mt-1 text-sm text-muted-foreground">{me.data.active_tenant?.tenant_name}</p> : null}

      <div className="mt-6 grid gap-3 sm:grid-cols-4" aria-label={t("overview.byStatus")}>
        {ORDER.map((status) => (
          <Link
            key={status}
            href={`/ops/shipments?status=${status}`}
            prefetch={false}
            className="rounded-lg border p-3 hover:bg-muted/50"
          >
            <StatusBadge status={status} />
            <p className="mt-2 text-2xl font-semibold tabular-nums">{counts.get(status) ?? 0}</p>
          </Link>
        ))}
        <div className="rounded-lg border p-3">
          <p className="text-sm text-muted-foreground">{t("overview.delayed")}</p>
          <p className="mt-2 text-2xl font-semibold tabular-nums">{delayed}</p>
        </div>
        <div className="rounded-lg border p-3">
          <p className="text-sm text-muted-foreground">{t("overview.openTrips")}</p>
          <p className="mt-2 text-2xl font-semibold tabular-nums">{openTrips}</p>
        </div>
      </div>

      <h2 className="mt-8 text-base font-semibold">{t("overview.recent")}</h2>
      {items.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">{t("common.empty")}</p>
      ) : (
        <ul className="mt-2 divide-y rounded-lg border">
          {items.slice(0, 8).map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
              <Link href={`/ops/shipments/${s.id}`} prefetch={false} className="font-medium underline-offset-4 hover:underline">
                {s.reference}
              </Link>
              <StatusBadge status={s.status} />
              <span className="text-muted-foreground">
                {s.origin_label} → {s.destination_label}
              </span>
              <span className="ms-auto text-muted-foreground">{formatDate(s.updated_at, locale)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
