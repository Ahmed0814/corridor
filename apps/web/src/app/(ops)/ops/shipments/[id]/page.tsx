import Link from "next/link";
import { notFound } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";

import { type Me, apiGet } from "@/lib/api";
import { ACTION_FIELDS, type LifecycleEvent, type Shipment, shipmentActions } from "@/lib/logistics";

import { shipmentAction } from "../../actions";
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

export default async function ShipmentDetail({ params, searchParams }: PageProps<"/ops/shipments/[id]">) {
  const { id } = await params;
  const sp = await searchParams;
  const t = await getTranslations("Ops");
  const locale = await getLocale();
  const [me, shipment, events] = await Promise.all([
    apiGet<Me>("/me"),
    apiGet<Shipment>(`/shipments/${encodeURIComponent(id)}`),
    apiGet<LifecycleEvent[]>(`/shipments/${encodeURIComponent(id)}/events`),
  ]);
  if (!shipment.ok) {
    if (shipment.status === 404 || shipment.status === 422) notFound();
    return <ActionError code={shipment.error.code} requestId={shipment.error.requestId ?? undefined} />;
  }
  const s = shipment.data;
  const actions = shipmentActions(s.status, me.ok ? me.data.permissions : []);

  return (
    <section>
      <OpsNav current="shipments" />
      <Link href="/ops/shipments" prefetch={false} className="text-sm underline-offset-4 hover:underline">
        ← {t("common.back")}
      </Link>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">
          {t("shipments.detail")} {s.reference}
        </h1>
        <StatusBadge status={s.status} />
        {s.is_delayed ? (
          <span className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-900">
            {t("shipments.delayed")}: {s.delay_reason}
          </span>
        ) : null}
      </div>
      <ActionError code={sp.error as string | undefined} requestId={sp.ref as string | undefined} />

      <dl className="mt-4 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-muted-foreground">{t("shipments.customer")}</dt>
          <dd>{s.customer_name}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("shipments.route")}</dt>
          <dd>
            {s.origin_label} → {s.destination_label}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("shipments.weight")}</dt>
          <dd>{s.weight_kg ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("shipments.containers")}</dt>
          <dd>{s.containers.length ? s.containers.map((c) => c.number).join(", ") : t("common.none")}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-muted-foreground">{t("shipments.cargo")}</dt>
          <dd>{s.cargo_description || "—"}</dd>
        </div>
        {s.status === "delivered" ? (
          <div>
            <dt className="text-muted-foreground">{t("shipments.recipient")}</dt>
            <dd>
              {s.recipient_name} · {formatDate(s.delivered_at, locale)}
            </dd>
          </div>
        ) : null}
      </dl>

      {actions.length > 0 ? (
        <div className="mt-6 flex flex-wrap items-start gap-3">
          {actions.map((action) => {
            const field = ACTION_FIELDS[action];
            return (
              <form key={action} action={shipmentAction} className="flex flex-wrap items-end gap-2 rounded-lg border p-3">
                <IdempotencyField />
                <input type="hidden" name="shipment_id" value={s.id} />
                <input type="hidden" name="action" value={action} />
                {field === "reason" ? (
                  <input name="reason" required placeholder={t("common.reason")} className={inputClass} />
                ) : null}
                {field === "border" ? (
                  <input name="border" required placeholder={t("actions.border")} className={inputClass} />
                ) : null}
                {field === "recipient" ? (
                  <input name="recipient" required placeholder={t("shipments.recipient")} className={inputClass} />
                ) : null}
                <button type="submit" className={action === "cancel" ? subtleButtonClass : buttonClass}>
                  {t(`actions.${action}`)}
                </button>
                {action === "border-clearance" ? (
                  <p className="w-full max-w-sm text-xs text-muted-foreground">{t("actions.clearanceNote")}</p>
                ) : null}
              </form>
            );
          })}
        </div>
      ) : null}

      <h2 className="mt-8 text-base font-semibold">{t("shipments.timeline")}</h2>
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
