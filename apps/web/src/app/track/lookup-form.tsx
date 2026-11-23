"use client";

import { useTranslations } from "next-intl";
import { useActionState, useMemo } from "react";

import { ShipmentMap } from "@/components/shipment-map";

import { type LookupState, lookupContainer } from "./actions";

function when(iso: string | null | undefined, locale: string): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short", timeZone: "Africa/Djibouti" }).format(
    new Date(iso),
  );
}

const input =
  "w-full rounded-md border bg-background px-3 py-2 font-mono uppercase focus-visible:outline-2 focus-visible:outline-ring";

export function LookupForm({ locale, styleUrl }: { locale: string; styleUrl: string }) {
  const t = useTranslations("Track");
  const [state, action, pending] = useActionState<LookupState, FormData>(lookupContainer, {});
  const v = state.view;
  const pollBody = useMemo(
    () => (state.query ? { container_number: state.query.container_number, reference: state.query.reference } : undefined),
    [state.query],
  );

  return (
    <div className="space-y-6">
      <form action={action} className="grid gap-3 rounded-lg border p-4 sm:grid-cols-2">
        <label className="text-sm">
          <span className="mb-1 block font-medium">{t("lookup.container")}</span>
          <input name="container_number" required minLength={11} maxLength={15} placeholder="MSCU1234566" className={input} />
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium">{t("lookup.reference")}</span>
          <input name="reference" required minLength={3} maxLength={60} placeholder="SHP-261123-B2D411" className={input} />
        </label>
        <p className="text-xs text-muted-foreground sm:col-span-2">{t("lookup.why")}</p>
        <div className="sm:col-span-2">
          <button
            type="submit"
            disabled={pending}
            className="inline-flex items-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {t("lookup.submit")}
          </button>
        </div>
        {state.error ? (
          <p role="alert" className="text-sm text-destructive sm:col-span-2">
            {t(`lookup.errors.${state.error}`)}
          </p>
        ) : null}
      </form>

      {v ? (
        <section className="space-y-4">
          <header>
            <p className="text-sm text-muted-foreground">{t("heading")}</p>
            <h2 className="text-2xl font-semibold">{v.reference}</h2>
            {v.status ? (
              <p className="mt-1 text-lg">
                {t.has(`status.${v.status}`) ? t(`status.${v.status}`) : v.status}
                {v.is_delayed ? (
                  <span className="ms-2 rounded bg-amber-100 px-2 py-0.5 text-sm text-amber-900">{t("delayed")}</span>
                ) : null}
              </p>
            ) : null}
          </header>
          {v.origin_label ? (
            <p>
              {v.origin_label} → {v.destination_label}
            </p>
          ) : null}
          {v.eta ? (
            <p>
              <span className="text-sm text-muted-foreground">{t("eta")}: </span>
              {when(v.eta, locale)}
            </p>
          ) : null}
          {v.delivered_at ? (
            <p>
              <span className="text-sm text-muted-foreground">{t("delivered")}: </span>
              {when(v.delivered_at, locale)}
            </p>
          ) : null}
          {"position" in v && pollBody ? (
            <ShipmentMap
              initial={v.position ?? null}
              pollUrl="/track/lookup"
              pollBody={pollBody}
              styleUrl={styleUrl}
              locale={locale}
              labels={{
                title: t("position"),
                noPosition: t("noPosition"),
                recorded: t("recorded", { at: "{at}" }),
                received: t("received", { at: "{at}" }),
                precision: t("precision", { km: 1 }),
                freshness: {
                  live: t("freshness.live"),
                  delayed: t("freshness.delayed"),
                  stale: t("freshness.stale"),
                  offline: t("freshness.offline"),
                },
                basemap: t("basemap"),
              }}
            />
          ) : null}
          {v.timeline && v.timeline.length > 0 ? (
            <ol className="space-y-1 border-s ps-4 text-sm">
              {v.timeline.map((item, i) => (
                <li key={`${item.at}-${i}`}>
                  {item.label} <span className="text-xs text-muted-foreground">{when(item.at, locale)}</span>
                </li>
              ))}
            </ol>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
