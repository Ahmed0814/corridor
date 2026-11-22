import { getTranslations } from "next-intl/server";

import { type Me, apiGet } from "@/lib/api";
import type { Driver, Page, Shipment, Trip, Vehicle } from "@/lib/logistics";

import { dispatchPlan } from "../actions";
import { ActionError, buttonClass, Field, IdempotencyField, inputClass, OpsNav, StatusBadge } from "../_components/ui";

export default async function DispatchPage({ searchParams }: PageProps<"/ops/dispatch">) {
  const sp = await searchParams;
  const t = await getTranslations("Ops");
  const [me, ready, vehicles, drivers, trips] = await Promise.all([
    apiGet<Me>("/me"),
    apiGet<Page<Shipment>>("/shipments?status=confirmed&limit=200"),
    apiGet<Page<Vehicle>>("/vehicles?status=available&limit=200"),
    apiGet<Page<Driver>>("/drivers?limit=200"),
    apiGet<Page<Trip>>("/trips?limit=50"),
  ]);
  const perms = me.ok ? me.data.permissions : [];
  const canDispatch = perms.includes("shipments.dispatch") && perms.includes("trips.assign");
  const shipments = ready.ok ? ready.data.items : [];
  const freeVehicles = vehicles.ok ? vehicles.data.items.filter((v) => v.assigned_trip_id === null) : [];
  const activeDrivers = drivers.ok ? drivers.data.items.filter((d) => d.employment_status === "active") : [];

  return (
    <section>
      <OpsNav current="dispatch" />
      <h1 className="text-xl font-semibold">{t("dispatch.title")}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{t("dispatch.intro")}</p>
      <ActionError
        code={sp.error as string | undefined}
        requestId={sp.ref as string | undefined}
        fields={sp.fields as string | undefined}
      />

      {canDispatch ? (
        shipments.length === 0 ? (
          <p className="mt-6 text-sm text-muted-foreground">{t("dispatch.noneReady")}</p>
        ) : (
          <form action={dispatchPlan} className="mt-6 grid max-w-2xl gap-3 rounded-lg border p-4 sm:grid-cols-2">
            <IdempotencyField />
            <fieldset className="sm:col-span-2">
              <legend className="mb-1 text-sm font-medium">{t("dispatch.shipments")}</legend>
              <div className="space-y-1">
                {shipments.map((s) => (
                  <label key={s.id} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" name="shipment_ids" value={s.id} />
                    <span className="font-medium">{s.reference}</span>
                    <span className="text-muted-foreground">
                      {s.customer_name} · {s.origin_label} → {s.destination_label}
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
            <Field label={t("dispatch.vehicle")}>
              <select name="vehicle_id" required className={inputClass}>
                {freeVehicles.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.plate}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("dispatch.driver")}>
              <select name="driver_id" required className={inputClass}>
                {activeDrivers.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.full_name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("shipments.origin")}>
              <input name="origin_label" required defaultValue="Port of Djibouti" className={inputClass} />
            </Field>
            <Field label={t("shipments.destination")}>
              <input name="destination_label" required className={inputClass} />
            </Field>
            <div className="sm:col-span-2">
              <button type="submit" className={buttonClass}>
                {t("dispatch.submit")}
              </button>
            </div>
          </form>
        )
      ) : null}

      <h2 className="mt-8 text-base font-semibold">{t("dispatch.trips")}</h2>
      <ul className="mt-2 divide-y rounded-lg border">
        {(trips.ok ? trips.data.items : []).map((trip) => (
          <li key={trip.id} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
            <span className="font-medium">{trip.reference}</span>
            <StatusBadge status={trip.status} />
            <span className="text-muted-foreground">
              {trip.origin_label} → {trip.destination_label}
            </span>
            {trip.assignment ? (
              <span className="ms-auto text-muted-foreground">
                {t("dispatch.assignedTo")}: {trip.assignment.vehicle_plate} · {trip.assignment.driver_name}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
