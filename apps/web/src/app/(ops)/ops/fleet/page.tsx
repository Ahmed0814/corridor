import { getTranslations } from "next-intl/server";

import { type Me, apiGet } from "@/lib/api";
import type { Driver, Page, Vehicle } from "@/lib/logistics";

import { createDriver, createVehicle, setVehicleStatus } from "../actions";
import {
  ActionError,
  buttonClass,
  Field,
  IdempotencyField,
  inputClass,
  OpsNav,
  StatusBadge,
  subtleButtonClass,
} from "../_components/ui";

export default async function FleetPage({ searchParams }: PageProps<"/ops/fleet">) {
  const sp = await searchParams;
  const t = await getTranslations("Ops");
  const [me, vehicles, drivers] = await Promise.all([
    apiGet<Me>("/me"),
    apiGet<Page<Vehicle>>("/vehicles?limit=200"),
    apiGet<Page<Driver>>("/drivers?limit=200"),
  ]);
  const perms = me.ok ? me.data.permissions : [];
  const canFleet = perms.includes("fleet.write");
  const canDrivers = perms.includes("drivers.write");

  return (
    <section>
      <OpsNav current="fleet" />
      <h1 className="text-xl font-semibold">{t("fleet.title")}</h1>
      <ActionError
        code={sp.error as string | undefined}
        requestId={sp.ref as string | undefined}
        fields={sp.fields as string | undefined}
      />

      <h2 className="mt-6 text-base font-semibold">{t("fleet.vehicles")}</h2>
      <div className="mt-2 overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            <tr>
              <th className="px-3 py-2 text-start font-medium">{t("fleet.plate")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("fleet.kind")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("common.status")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("fleet.assigned")}</th>
              {canFleet ? <th className="px-3 py-2" /> : null}
            </tr>
          </thead>
          <tbody>
            {(vehicles.ok ? vehicles.data.items : []).map((v) => (
              <tr key={v.id} className="border-t">
                <td className="px-3 py-2 font-medium">{v.plate}</td>
                <td className="px-3 py-2">{v.kind}</td>
                <td className="px-3 py-2">
                  <StatusBadge status={v.status} />
                </td>
                <td className="px-3 py-2">{v.assigned_trip_id ? t("fleet.yes") : t("fleet.no")}</td>
                {canFleet ? (
                  <td className="px-3 py-2 text-end">
                    {v.status !== "retired" && v.assigned_trip_id === null ? (
                      <form action={setVehicleStatus}>
                        <IdempotencyField />
                        <input type="hidden" name="vehicle_id" value={v.id} />
                        <input
                          type="hidden"
                          name="status"
                          value={v.status === "available" ? "maintenance" : "available"}
                        />
                        <button type="submit" className={subtleButtonClass}>
                          {v.status === "available" ? t("fleet.maintenance") : t("fleet.available")}
                        </button>
                      </form>
                    ) : null}
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {canFleet ? (
        <form action={createVehicle} className="mt-3 flex flex-wrap items-end gap-2">
          <IdempotencyField />
          <Field label={t("fleet.plate")}>
            <input name="plate" required className={inputClass} />
          </Field>
          <Field label={t("fleet.kind")}>
            <select name="kind" className={inputClass}>
              <option value="tractor">tractor</option>
              <option value="rigid">rigid</option>
            </select>
          </Field>
          <button type="submit" className={buttonClass}>
            {t("fleet.newVehicle")}
          </button>
        </form>
      ) : null}

      <h2 className="mt-8 text-base font-semibold">{t("fleet.drivers")}</h2>
      <div className="mt-2 overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            <tr>
              <th className="px-3 py-2 text-start font-medium">{t("fleet.fullName")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("fleet.employment")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("fleet.licenseExpiry")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("fleet.linked")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("fleet.consent")}</th>
            </tr>
          </thead>
          <tbody>
            {(drivers.ok ? drivers.data.items : []).map((d) => (
              <tr key={d.id} className="border-t">
                <td className="px-3 py-2 font-medium">{d.full_name}</td>
                <td className="px-3 py-2">{d.employment_status}</td>
                <td className="px-3 py-2">{d.license_expiry ?? "—"}</td>
                <td className="px-3 py-2">{d.membership_id ? t("fleet.yes") : t("fleet.no")}</td>
                <td className="px-3 py-2">{d.tracking_consent ? t("fleet.yes") : t("fleet.no")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {canDrivers ? (
        <form action={createDriver} className="mt-3 grid max-w-2xl gap-2 sm:grid-cols-4">
          <IdempotencyField />
          <Field label={t("fleet.fullName")}>
            <input name="full_name" required className={inputClass} />
          </Field>
          <Field label={t("fleet.phone")}>
            <input name="phone_e164" placeholder="+25377123456" className={inputClass} />
          </Field>
          <Field label={t("fleet.license")}>
            <input name="license_number" className={inputClass} autoComplete="off" />
          </Field>
          <Field label={t("fleet.licenseExpiry")}>
            <input name="license_expiry" type="date" className={inputClass} />
          </Field>
          <div className="sm:col-span-4">
            <button type="submit" className={buttonClass}>
              {t("fleet.newDriver")}
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}
