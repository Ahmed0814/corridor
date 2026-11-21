import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import { type Me, apiGet } from "@/lib/api";
import type { Container, Customer, Page, Shipment } from "@/lib/logistics";

import { createShipment } from "../actions";
import {
  ActionError,
  buttonClass,
  Field,
  formatDate,
  IdempotencyField,
  inputClass,
  OpsNav,
  StatusBadge,
} from "../_components/ui";

export default async function ShipmentsPage({ searchParams }: PageProps<"/ops/shipments">) {
  const sp = await searchParams;
  const status = typeof sp.status === "string" ? sp.status : "";
  const q = typeof sp.q === "string" ? sp.q : "";
  const t = await getTranslations("Ops");
  const locale = await getLocale();
  const query = new URLSearchParams({ limit: "100" });
  if (status) query.set("status", status);
  if (q) query.set("q", q);
  const [me, shipments, customers, containers] = await Promise.all([
    apiGet<Me>("/me"),
    apiGet<Page<Shipment>>(`/shipments?${query.toString()}`),
    apiGet<Page<Customer>>("/customers?limit=200"),
    apiGet<Page<Container>>("/containers?availability=available&limit=200"),
  ]);
  const canWrite = me.ok && me.data.permissions.includes("shipments.write");
  const rows = shipments.ok ? shipments.data.items : [];
  const customerList = customers.ok ? customers.data.items.filter((c) => c.status === "active") : [];

  return (
    <section>
      <OpsNav current="shipments" />
      <h1 className="text-xl font-semibold">{t("shipments.title")}</h1>
      <ActionError code={sp.error as string | undefined} requestId={sp.ref as string | undefined} />

      <form className="mt-4 flex flex-wrap items-end gap-2" role="search">
        <Field label={t("shipments.reference")}>
          <input name="q" defaultValue={q} className={inputClass} />
        </Field>
        <Field label={t("common.status")}>
          <select name="status" defaultValue={status} className={inputClass}>
            <option value="">—</option>
            {["draft", "confirmed", "dispatched", "in_transit", "at_border", "delivery_failed", "delivered", "cancelled"].map(
              (s) => (
                <option key={s} value={s}>
                  {t(`status.${s}`)}
                </option>
              ),
            )}
          </select>
        </Field>
        <button type="submit" className="rounded-md border px-3 py-2 text-sm hover:bg-muted">
          OK
        </button>
      </form>

      <div className="mt-4 overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-start">
            <tr>
              <th className="px-3 py-2 text-start font-medium">{t("shipments.reference")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("shipments.customer")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("common.status")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("shipments.route")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("common.created")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center text-muted-foreground">
                  {t("common.empty")}
                </td>
              </tr>
            ) : (
              rows.map((s) => (
                <tr key={s.id} className="border-t">
                  <td className="px-3 py-2">
                    <Link href={`/ops/shipments/${s.id}`} prefetch={false} className="font-medium hover:underline">
                      {s.reference}
                    </Link>
                  </td>
                  <td className="px-3 py-2">{s.customer_name ?? "—"}</td>
                  <td className="px-3 py-2">
                    <span className="inline-flex items-center gap-2">
                      <StatusBadge status={s.status} />
                      {s.is_delayed ? <span className="text-xs text-amber-700">{t("shipments.delayed")}</span> : null}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {s.origin_label} → {s.destination_label}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">{formatDate(s.created_at, locale)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {canWrite ? (
        <form action={createShipment} className="mt-8 grid max-w-2xl gap-3 rounded-lg border p-4 sm:grid-cols-2">
          <h2 className="text-base font-semibold sm:col-span-2">{t("shipments.new")}</h2>
          <IdempotencyField />
          {customerList.length === 0 ? (
            <p className="text-sm text-muted-foreground sm:col-span-2">{t("shipments.noCustomers")}</p>
          ) : null}
          <Field label={t("shipments.customer")}>
            <select name="customer_id" required className={inputClass}>
              {customerList.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("shipments.weight")}>
            <input name="weight_kg" type="number" min="0" step="0.1" className={inputClass} />
          </Field>
          <Field label={t("shipments.origin")}>
            <input name="origin_label" required defaultValue="Port of Djibouti" className={inputClass} />
          </Field>
          <Field label={t("shipments.destination")}>
            <input name="destination_label" required className={inputClass} />
          </Field>
          <div className="sm:col-span-2">
            <Field label={t("shipments.cargo")}>
              <textarea name="cargo_description" rows={2} className={inputClass} />
            </Field>
          </div>
          <div className="sm:col-span-2">
            <Field label={t("shipments.containers")} hint={t("shipments.containerHint")}>
              <select name="container_ids" multiple size={4} className={inputClass}>
                {(containers.ok ? containers.data.items : []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.number} · {c.size_ft} ft
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <div className="sm:col-span-2">
            <button type="submit" className={buttonClass} disabled={customerList.length === 0}>
              {t("common.create")}
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}
