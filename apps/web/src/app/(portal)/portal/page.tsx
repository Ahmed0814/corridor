import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import { apiGet } from "@/lib/api";
import type { Page, Shipment } from "@/lib/logistics";
import { etaView } from "@/lib/phase6";

import { formatDate, StatusBadge } from "../../(ops)/ops/_components/ui";

// Customer portal: the API returns only this customer's shipments (scope rule, D-016).
export default async function PortalHome() {
  const t = await getTranslations("Portal");
  const locale = await getLocale();
  const shipments = await apiGet<Page<Shipment>>("/shipments?limit=100");

  return (
    <section>
      <h1 className="text-xl font-semibold">{t("title")}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{t("description")}</p>
      {!shipments.ok ? (
        <p role="alert" className="mt-4 text-sm">
          {t("error")} <code>{shipments.error.code}</code>
        </p>
      ) : shipments.data.items.length === 0 ? (
        <p className="mt-4 text-sm text-muted-foreground">{t("empty")}</p>
      ) : (
        <table className="mt-4 w-full text-sm">
          <thead className="text-left text-muted-foreground">
            <tr>
              <th className="py-1">{t("reference")}</th>
              <th>{t("route")}</th>
              <th>{t("status")}</th>
              <th>{t("eta")}</th>
            </tr>
          </thead>
          <tbody>
            {shipments.data.items.map((s) => {
              const eta = etaView(s);
              return (
                <tr key={s.id} className="border-t">
                  <td className="py-2">
                    <Link href={`/portal/shipments/${s.id}`} prefetch={false} className="font-medium underline-offset-4 hover:underline">
                      {s.reference}
                    </Link>
                  </td>
                  <td>
                    {s.origin_label} → {s.destination_label}
                  </td>
                  <td>
                    <StatusBadge status={s.status} />
                    {s.is_delayed ? <span className="ms-2 text-xs text-amber-700">{t("delayed")}</span> : null}
                  </td>
                  <td>{eta.kind === "estimate" ? formatDate(eta.eta, locale) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
