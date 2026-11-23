import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import { type Me, apiGet } from "@/lib/api";
import type { Container, Page, Shipment } from "@/lib/logistics";

import { createContainer } from "../actions";
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

type ContainerRow = Container & { iso_type: string; owner: string; created_at: string };

export default async function ContainersPage({ searchParams }: PageProps<"/ops/containers">) {
  const sp = await searchParams;
  const t = await getTranslations("Ops");
  const locale = await getLocale();
  const [me, containers] = await Promise.all([
    apiGet<Me>("/me"),
    apiGet<Page<ContainerRow>>("/containers?limit=200"),
  ]);
  const canWrite = me.ok && me.data.permissions.includes("containers.write");
  const find = typeof sp.find === "string" ? sp.find.replace(/\s+/g, "").toUpperCase().slice(0, 13) : "";
  const found = find.length >= 4 ? await apiGet<Shipment[]>(`/shipments/by-container/${encodeURIComponent(find)}`) : null;
  const rows = containers.ok ? containers.data.items : [];

  return (
    <section>
      <OpsNav current="containers" />
      <h1 className="text-xl font-semibold">{t("containers.title")}</h1>
      <ActionError
        code={sp.error as string | undefined}
        requestId={sp.ref as string | undefined}
        fields={sp.fields as string | undefined}
      />
      {!containers.ok ? (
        <ActionError code={containers.error.code} requestId={containers.error.requestId ?? undefined} />
      ) : null}
      <form method="get" className="mt-4 flex flex-wrap items-end gap-2">
        <label className="text-sm">
          <span className="mb-1 block font-medium">{t("containers.find")}</span>
          <input name="find" defaultValue={find} placeholder="MSCU1234566" className={`${inputClass} w-56 font-mono uppercase`} />
        </label>
        <button type="submit" className={buttonClass}>
          {t("containers.search")}
        </button>
      </form>
      {found ? (
        <div className="mt-3 rounded-lg border p-3 text-sm">
          {found.ok && found.data.length > 0 ? (
            <ul className="space-y-1">
              {found.data.map((sh) => (
                <li key={sh.id} className="flex flex-wrap items-center gap-2">
                  <Link href={`/ops/shipments/${sh.id}`} prefetch={false} className="font-medium underline-offset-4 hover:underline">
                    {sh.reference}
                  </Link>
                  <StatusBadge status={sh.status} />
                  <span className="text-muted-foreground">
                    {sh.customer_name} · {sh.origin_label} → {sh.destination_label}
                  </span>
                  {["dispatched", "in_transit", "at_border"].includes(sh.status) ? (
                    <Link href="/ops/map" prefetch={false} className="text-xs underline-offset-4 hover:underline">
                      {t("containers.onMap")}
                    </Link>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-muted-foreground">{t("containers.notFound", { number: find })}</p>
          )}
        </div>
      ) : null}

      <div className="mt-4 overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            <tr>
              <th className="px-3 py-2 text-start font-medium">{t("containers.number")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("containers.size")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("containers.owner")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("containers.condition")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("containers.availability")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("common.created")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} className="border-t">
                <td className="px-3 py-2 font-mono font-medium">{c.number}</td>
                <td className="px-3 py-2">
                  {c.size_ft} ft{c.iso_type ? ` · ${c.iso_type}` : ""}
                </td>
                <td className="px-3 py-2">{c.owner || "—"}</td>
                <td className="px-3 py-2">{t(`containers.conditions.${c.condition}`)}</td>
                <td className="px-3 py-2">
                  <StatusBadge status={c.availability} />
                </td>
                <td className="px-3 py-2 text-muted-foreground">{formatDate(c.created_at, locale)}</td>
              </tr>
            ))}
            {rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-3 text-muted-foreground">
                  {t("common.empty")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {canWrite ? (
        <form action={createContainer} className="mt-6 grid max-w-3xl gap-3 rounded-lg border p-4 sm:grid-cols-2">
          <h2 className="text-base font-semibold sm:col-span-2">{t("containers.new")}</h2>
          <IdempotencyField />
          <Field label={t("containers.number")} hint={t("containers.numberHint")}>
            <input
              name="number"
              required
              minLength={11}
              maxLength={13}
              placeholder="MSCU1234566"
              autoCapitalize="characters"
              className={`${inputClass} font-mono uppercase`}
            />
          </Field>
          <Field label={t("containers.size")}>
            <select name="size_ft" required defaultValue="40" className={inputClass}>
              {[10, 20, 40, 45].map((n) => (
                <option key={n} value={n}>
                  {n} ft
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("containers.isoType")} hint={t("common.optional")}>
            <input name="iso_type" maxLength={4} placeholder="42G1" className={`${inputClass} uppercase`} />
          </Field>
          <Field label={t("containers.owner")} hint={t("common.optional")}>
            <input name="owner" maxLength={200} className={inputClass} />
          </Field>
          <Field label={t("containers.condition")}>
            <select name="condition" defaultValue="good" className={inputClass}>
              {(["good", "damaged", "needs_repair"] as const).map((c) => (
                <option key={c} value={c}>
                  {t(`containers.conditions.${c}`)}
                </option>
              ))}
            </select>
          </Field>
          <div className="sm:col-span-2">
            <button type="submit" className={buttonClass}>
              {t("containers.create")}
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}
