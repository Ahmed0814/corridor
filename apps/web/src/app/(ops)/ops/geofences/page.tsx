import { getLocale, getTranslations } from "next-intl/server";

import { type Me, apiGet } from "@/lib/api";
import { type Checkpoint, GEOFENCE_KINDS, type Geofence } from "@/lib/phase6";

import { createCheckpoint, createGeofence, deactivateCheckpoint, geofenceAction } from "../phase6-actions";
import {
  ActionError,
  buttonClass,
  Field,
  formatDate,
  IdempotencyField,
  inputClass,
  OpsNav,
  subtleButtonClass,
} from "../_components/ui";

export default async function Geofences({ searchParams }: PageProps<"/ops/geofences">) {
  const sp = await searchParams;
  const t = await getTranslations("Ops.geofences");
  const locale = await getLocale();
  const [me, fences, checkpoints] = await Promise.all([
    apiGet<Me>("/me"),
    apiGet<Geofence[]>("/geofences"),
    apiGet<Checkpoint[]>("/checkpoints"),
  ]);
  const canWrite = me.ok && me.data.permissions.includes("geofences.write");
  const list = fences.ok ? fences.data : [];

  return (
    <section>
      <OpsNav current="geofences" />
      <h1 className="text-xl font-semibold">{t("title")}</h1>
      <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{t("description")}</p>
      <ActionError
        code={sp.error as string | undefined}
        requestId={sp.ref as string | undefined}
        fields={sp.fields as string | undefined}
      />
      {!fences.ok ? <ActionError code={fences.error.code} requestId={fences.error.requestId ?? undefined} /> : null}

      <table className="mt-4 w-full text-sm">
        <thead className="text-left text-muted-foreground">
          <tr>
            <th className="py-1">{t("name")}</th>
            <th>{t("kind")}</th>
            <th>{t("verified")}</th>
            <th>{t("active")}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {list.map((g) => (
            <tr key={g.id} className="border-t align-top">
              <td className="py-2">
                <span className="font-medium">{g.name}</span>
                {g.source_note ? <p className="text-xs text-muted-foreground">{g.source_note}</p> : null}
              </td>
              <td>{t(`kinds.${g.kind}`)}</td>
              <td>
                {g.verified ? (
                  formatDate(g.verified_at, locale)
                ) : (
                  <span className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-900">{t("unverified")}</span>
                )}
              </td>
              <td>{g.is_active ? t("yes") : t("no")}</td>
              <td className="space-x-1 text-right">
                {canWrite && !g.verified ? (
                  <form action={geofenceAction} className="inline">
                    <IdempotencyField />
                    <input type="hidden" name="geofence_id" value={g.id} />
                    <input type="hidden" name="action" value="verify" />
                    <button type="submit" className={subtleButtonClass}>
                      {t("verify")}
                    </button>
                  </form>
                ) : null}
                {canWrite ? (
                  <form action={geofenceAction} className="inline">
                    <IdempotencyField />
                    <input type="hidden" name="geofence_id" value={g.id} />
                    <input type="hidden" name="action" value={g.is_active ? "deactivate" : "activate"} />
                    <button type="submit" className={subtleButtonClass}>
                      {g.is_active ? t("deactivate") : t("activate")}
                    </button>
                  </form>
                ) : null}
              </td>
            </tr>
          ))}
          {list.length === 0 ? (
            <tr>
              <td colSpan={5} className="py-3 text-muted-foreground">
                {t("empty")}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-muted-foreground">{t("verifyNote")}</p>

      <h2 className="mt-8 text-base font-semibold">{t("checkpoints")}</h2>
      <ul className="mt-2 space-y-1 text-sm">
        {(checkpoints.ok ? checkpoints.data : []).map((c) => (
          <li key={c.id} className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{c.name}</span>
            <span className="text-muted-foreground">({c.geofence_name})</span>
            {c.is_border ? <span className="rounded bg-muted px-2 py-0.5 text-xs">{t("border")}</span> : null}
            {!c.verified ? <span className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-900">{t("unverified")}</span> : null}
            {!c.is_active ? <span className="text-xs text-muted-foreground">{t("inactive")}</span> : null}
            {canWrite && c.is_active ? (
              <form action={deactivateCheckpoint} className="inline">
                <IdempotencyField />
                <input type="hidden" name="checkpoint_id" value={c.id} />
                <button type="submit" className="text-xs underline-offset-4 hover:underline">
                  {t("stopWatching")}
                </button>
              </form>
            ) : null}
          </li>
        ))}
      </ul>

      {canWrite ? (
        <div className="mt-8 grid gap-6 lg:grid-cols-2">
          <form action={createGeofence} className="grid gap-3 rounded-lg border p-4">
            <h2 className="text-base font-semibold">{t("new")}</h2>
            <IdempotencyField />
            <Field label={t("name")}>
              <input name="name" required maxLength={120} className={inputClass} />
            </Field>
            <Field label={t("kind")}>
              <select name="kind" className={inputClass} defaultValue="border">
                {GEOFENCE_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {t(`kinds.${k}`)}
                  </option>
                ))}
              </select>
            </Field>
            <div className="grid grid-cols-3 gap-2">
              <Field label={t("lat")}>
                <input name="lat" type="number" step="any" min={-90} max={90} required className={inputClass} />
              </Field>
              <Field label={t("lng")}>
                <input name="lng" type="number" step="any" min={-180} max={180} required className={inputClass} />
              </Field>
              <Field label={t("radius")}>
                <input name="radius_m" type="number" min={50} max={20000} defaultValue={1000} required className={inputClass} />
              </Field>
            </div>
            <Field label={t("source")} hint={t("sourceHint")}>
              <input name="source_note" maxLength={300} className={inputClass} />
            </Field>
            <div>
              <button type="submit" className={buttonClass}>
                {t("create")}
              </button>
            </div>
          </form>

          <form action={createCheckpoint} className="grid content-start gap-3 rounded-lg border p-4">
            <h2 className="text-base font-semibold">{t("newCheckpoint")}</h2>
            <IdempotencyField />
            <Field label={t("geofence")}>
              <select name="geofence_id" required className={inputClass}>
                {list
                  .filter((g) => g.is_active)
                  .map((g) => (
                    <option key={g.id} value={g.id}>
                      {g.name}
                    </option>
                  ))}
              </select>
            </Field>
            <Field label={t("name")}>
              <input name="name" required maxLength={120} className={inputClass} />
            </Field>
            <label className="inline-flex items-center gap-2 text-sm">
              <input type="checkbox" name="is_border" /> {t("isBorder")}
            </label>
            <p className="text-xs text-muted-foreground">{t("borderNote")}</p>
            <div>
              <button type="submit" className={buttonClass} disabled={list.length === 0}>
                {t("createCheckpoint")}
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </section>
  );
}
