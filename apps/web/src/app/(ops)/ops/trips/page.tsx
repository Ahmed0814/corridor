import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import { apiGet } from "@/lib/api";
import type { Page, Trip } from "@/lib/logistics";

import { ActionError, formatDate, OpsNav, StatusBadge } from "../_components/ui";

export default async function TripsPage({ searchParams }: PageProps<"/ops/trips">) {
  const sp = await searchParams;
  const t = await getTranslations("Ops");
  const locale = await getLocale();
  const trips = await apiGet<Page<Trip>>("/trips?limit=100");
  const rows = trips.ok ? trips.data.items : [];

  return (
    <section>
      <OpsNav current="trips" />
      <h1 className="text-xl font-semibold">{t("trips.title")}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{t("trips.description")}</p>
      <ActionError code={sp.error as string | undefined} requestId={sp.ref as string | undefined} />
      {!trips.ok ? <ActionError code={trips.error.code} requestId={trips.error.requestId ?? undefined} /> : null}
      <div className="mt-4 overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            <tr>
              <th className="px-3 py-2 text-start font-medium">{t("trips.reference")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("common.status")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("shipments.route")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("trips.truck")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("trips.driver")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("trips.started")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((trip) => (
              <tr key={trip.id} className="border-t">
                <td className="px-3 py-2">
                  <Link href={`/ops/trips/${trip.id}`} prefetch={false} className="font-medium underline-offset-4 hover:underline">
                    {trip.reference}
                  </Link>
                </td>
                <td className="px-3 py-2">
                  <StatusBadge status={trip.status} />
                </td>
                <td className="px-3 py-2">
                  {trip.origin_label} → {trip.destination_label}
                </td>
                <td className="px-3 py-2">{trip.assignment?.vehicle_plate ?? "—"}</td>
                <td className="px-3 py-2">{trip.assignment?.driver_name ?? "—"}</td>
                <td className="px-3 py-2 text-muted-foreground">{formatDate(trip.started_at, locale)}</td>
              </tr>
            ))}
            {rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-3 text-muted-foreground">
                  {t("trips.empty")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}
