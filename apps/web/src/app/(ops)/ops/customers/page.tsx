import { getLocale, getTranslations } from "next-intl/server";

import { type Me, apiGet } from "@/lib/api";
import type { Customer, Page } from "@/lib/logistics";

import { createCustomer } from "../actions";
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

export default async function CustomersPage({ searchParams }: PageProps<"/ops/customers">) {
  const sp = await searchParams;
  const t = await getTranslations("Ops");
  const locale = await getLocale();
  const [me, customers] = await Promise.all([apiGet<Me>("/me"), apiGet<Page<Customer>>("/customers?limit=200")]);
  const canWrite = me.ok && me.data.permissions.includes("customers.write");

  return (
    <section>
      <OpsNav current="customers" />
      <h1 className="text-xl font-semibold">{t("customers.title")}</h1>
      <ActionError code={sp.error as string | undefined} requestId={sp.ref as string | undefined} />
      <div className="mt-4 overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            <tr>
              <th className="px-3 py-2 text-start font-medium">{t("customers.name")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("customers.email")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("common.status")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("common.created")}</th>
            </tr>
          </thead>
          <tbody>
            {(customers.ok ? customers.data.items : []).map((c) => (
              <tr key={c.id} className="border-t">
                <td className="px-3 py-2 font-medium">{c.name}</td>
                <td className="px-3 py-2">{c.email || "—"}</td>
                <td className="px-3 py-2">
                  <StatusBadge status={c.status} />
                </td>
                <td className="px-3 py-2 text-muted-foreground">{formatDate(c.created_at, locale)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {canWrite ? (
        <form action={createCustomer} className="mt-4 flex flex-wrap items-end gap-2">
          <IdempotencyField />
          <Field label={t("customers.name")}>
            <input name="name" required className={inputClass} />
          </Field>
          <Field label={t("customers.email")}>
            <input name="email" type="email" className={inputClass} />
          </Field>
          <Field label={t("customers.phone")}>
            <input name="phone_e164" placeholder="+253…" className={inputClass} />
          </Field>
          <button type="submit" className={buttonClass}>
            {t("customers.new")}
          </button>
        </form>
      ) : null}
    </section>
  );
}
