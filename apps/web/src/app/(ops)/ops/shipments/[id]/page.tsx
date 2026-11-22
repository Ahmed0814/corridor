import Link from "next/link";
import { notFound } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";

import { type Me, apiGet } from "@/lib/api";
import { ACTION_FIELDS, type LifecycleEvent, type Shipment, shipmentActions } from "@/lib/logistics";
import { type DocumentInfo, etaView, type TrackingLink } from "@/lib/phase6";

import { shipmentAction } from "../../actions";
import { revokeTrackingLink } from "../../phase6-actions";
import { CreateLinkForm, DeliverForm } from "../../_components/phase6-client";
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
  const sid = encodeURIComponent(id);
  const [me, shipment, events, links, documents] = await Promise.all([
    apiGet<Me>("/me"),
    apiGet<Shipment>(`/shipments/${sid}`),
    apiGet<LifecycleEvent[]>(`/shipments/${sid}/events`),
    apiGet<TrackingLink[]>(`/shipments/${sid}/tracking-links`),
    apiGet<DocumentInfo[]>(`/shipments/${sid}/documents`),
  ]);
  if (!shipment.ok) {
    if (shipment.status === 404 || shipment.status === 422) notFound();
    return <ActionError code={shipment.error.code} requestId={shipment.error.requestId ?? undefined} />;
  }
  const s = shipment.data;
  const permissions = me.ok ? me.data.permissions : [];
  const actions = shipmentActions(s.status, permissions);
  const eta = etaView(s);
  const canLink = permissions.includes("tracking_links.create");
  const canRevoke = permissions.includes("tracking_links.revoke");

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
      <ActionError
        code={sp.error as string | undefined}
        requestId={sp.ref as string | undefined}
        fields={sp.fields as string | undefined}
      />

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
        <div className="sm:col-span-2">
          <dt className="text-muted-foreground">{t("eta.title")}</dt>
          <dd>
            {eta.kind === "estimate" ? (
              <>
                {formatDate(eta.eta, locale)}
                <span className="ms-2 text-xs text-muted-foreground">
                  {t("eta.basis", {
                    km: eta.remainingKm ?? "—",
                    at: formatDate(eta.basisRecordedAt, locale),
                  })}
                </span>
              </>
            ) : eta.kind === "no_destination" ? (
              <span className="text-muted-foreground">{t("eta.noDestination")}</span>
            ) : (
              <span className="text-muted-foreground">{t("eta.none")}</span>
            )}
          </dd>
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
            if (action === "deliver") {
              return <DeliverForm key={action} shipmentId={s.id} idempotencyKey={crypto.randomUUID()} />;
            }
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

      <h2 className="mt-8 text-base font-semibold">{t("documents.title")}</h2>
      {documents.ok && documents.data.length > 0 ? (
        <ul className="mt-2 space-y-1 text-sm">
          {documents.data.map((d) => (
            <li key={d.id}>
              <a href={`/ops/documents/${d.id}`} className="underline-offset-4 hover:underline" target="_blank" rel="noreferrer">
                {t(`documents.kind.${d.kind}`)}
              </a>
              <span className="ms-2 text-xs text-muted-foreground">
                {Math.ceil(d.size_bytes / 1024)} KB · {t(`documents.visibility.${d.visibility}`)} · {formatDate(d.created_at, locale)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-muted-foreground">{t("common.none")}</p>
      )}

      <h2 className="mt-8 text-base font-semibold">{t("links.title")}</h2>
      <p className="mt-1 text-xs text-muted-foreground">{t("links.description")}</p>
      {links.ok && links.data.length > 0 ? (
        <ul className="mt-2 space-y-2 text-sm">
          {links.data.map((l) => (
            <li key={l.id} className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{l.label || t("links.unnamed")}</span>
              <StatusBadge status={`link_${l.state}`} />
              <span className="text-xs text-muted-foreground">
                {t("links.expiresAt", { at: formatDate(l.expires_at, locale) })} · {l.allowed_fields.join(", ")}
              </span>
              {l.state === "active" && canRevoke ? (
                <form action={revokeTrackingLink} className="flex items-center gap-1">
                  <IdempotencyField />
                  <input type="hidden" name="shipment_id" value={s.id} />
                  <input type="hidden" name="link_id" value={l.id} />
                  <input name="reason" required placeholder={t("common.reason")} className={`${inputClass} h-8 w-40`} />
                  <button type="submit" className={subtleButtonClass}>
                    {t("links.revoke")}
                  </button>
                </form>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {canLink && s.status !== "cancelled" ? (
        <div className="mt-3">
          <CreateLinkForm shipmentId={s.id} idempotencyKey={crypto.randomUUID()} />
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
