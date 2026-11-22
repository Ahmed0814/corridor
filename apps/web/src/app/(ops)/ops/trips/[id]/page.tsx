import Link from "next/link";
import { notFound } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";

import { type Me, apiGet } from "@/lib/api";
import type { Shipment, Trip } from "@/lib/logistics";
import { officeTripActions, type TripEvent } from "@/lib/trips";

import { tripAction } from "../../trip-actions";
import {
  ActionError,
  buttonClass,
  formatDate,
  IdempotencyField,
  inputClass,
  OpsNav,
  StatusBadge,
  subtleButtonClass,
} from "../../_components/ui";

const DANGER = new Set(["cancel", "abort", "unassign"]);

export default async function TripDetail({ params, searchParams }: PageProps<"/ops/trips/[id]">) {
  const { id } = await params;
  const sp = await searchParams;
  const t = await getTranslations("Ops");
  const locale = await getLocale();
  const tid = encodeURIComponent(id);
  const [me, trip, events] = await Promise.all([
    apiGet<Me>("/me"),
    apiGet<Trip>(`/trips/${tid}`),
    apiGet<TripEvent[]>(`/trips/${tid}/events`),
  ]);
  if (!trip.ok) {
    if (trip.status === 404 || trip.status === 422) notFound();
    return <ActionError code={trip.error.code} requestId={trip.error.requestId ?? undefined} />;
  }
  const tr = trip.data;
  const shipments = await Promise.all(tr.shipment_ids.map((sid) => apiGet<Shipment>(`/shipments/${encodeURIComponent(sid)}`)));
  const actions = officeTripActions(tr.status, me.ok ? me.data.permissions : []);

  return (
    <section>
      <OpsNav current="trips" />
      <Link href="/ops/trips" prefetch={false} className="text-sm underline-offset-4 hover:underline">
        ← {t("common.back")}
      </Link>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">
          {t("trips.detail")} {tr.reference}
        </h1>
        <StatusBadge status={tr.status} />
      </div>
      <ActionError code={sp.error as string | undefined} requestId={sp.ref as string | undefined} />

      <dl className="mt-4 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-muted-foreground">{t("shipments.route")}</dt>
          <dd>
            {tr.origin_label} → {tr.destination_label}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("trips.truckDriver")}</dt>
          <dd>
            {tr.assignment ? `${tr.assignment.vehicle_plate ?? "—"} · ${tr.assignment.driver_name ?? "—"}` : t("trips.notAssigned")}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("trips.started")}</dt>
          <dd>{formatDate(tr.started_at, locale)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("trips.completed")}</dt>
          <dd>{formatDate(tr.completed_at, locale)}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-muted-foreground">{t("trips.shipments")}</dt>
          <dd className="flex flex-wrap gap-3">
            {shipments.map((s, i) =>
              s.ok ? (
                <Link key={s.data.id} href={`/ops/shipments/${s.data.id}`} prefetch={false} className="underline-offset-4 hover:underline">
                  {s.data.reference} <span className="text-muted-foreground">({t(`status.${s.data.status}`)})</span>
                </Link>
              ) : (
                <span key={tr.shipment_ids[i]}>—</span>
              ),
            )}
          </dd>
        </div>
      </dl>

      {actions.length > 0 ? (
        <div className="mt-6 space-y-2">
          <p className="max-w-2xl text-xs text-muted-foreground">{t("trips.onBehalfNote")}</p>
          <div className="flex flex-wrap items-start gap-3">
            {actions.map((action) => (
              <form key={action} action={tripAction} className="flex flex-wrap items-end gap-2 rounded-lg border p-3">
                <IdempotencyField />
                <input type="hidden" name="trip_id" value={tr.id} />
                <input type="hidden" name="action" value={action} />
                <input name="reason" required maxLength={1000} placeholder={t("trips.reason")} className={`${inputClass} w-56`} />
                <button type="submit" className={DANGER.has(action) ? subtleButtonClass : buttonClass}>
                  {t(`trips.actions.${action}`)}
                </button>
              </form>
            ))}
          </div>
        </div>
      ) : null}

      <h2 className="mt-8 text-base font-semibold">{t("trips.history")}</h2>
      <ol className="mt-2 space-y-2 border-s ps-4">
        {(events.ok ? events.data : []).map((e) => (
          <li key={e.id} className="text-sm">
            <span className="font-medium">{e.type}</span>
            {e.to_status ? (
              <span className="ms-2 text-muted-foreground">
                {e.from_status ? `${e.from_status} → ` : ""}
                {e.to_status}
              </span>
            ) : null}
            <span className="ms-2 text-xs text-muted-foreground">
              {formatDate(e.occurred_at, locale)} · {e.actor_kind}
            </span>
            {e.reason ? <p className="text-muted-foreground">{e.reason}</p> : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
