import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { statusTone, type Tone } from "@/lib/logistics";

const TONE_CLASS: Record<Tone, string> = {
  neutral: "bg-muted text-foreground",
  info: "bg-blue-100 text-blue-900 dark:bg-blue-950 dark:text-blue-100",
  progress: "bg-indigo-100 text-indigo-900 dark:bg-indigo-950 dark:text-indigo-100",
  warning: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-100",
  success: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100",
  danger: "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-100",
};

export async function StatusBadge({ status }: { status: string }) {
  const t = await getTranslations("Ops.status");
  const label = t.has(status) ? t(status) : status;
  return (
    <Badge variant="secondary" className={TONE_CLASS[statusTone(status)]} data-status={status}>
      {label}
    </Badge>
  );
}

const NAV = [
  { href: "/ops", key: "overview" },
  { href: "/ops/shipments", key: "shipments" },
  { href: "/ops/dispatch", key: "dispatch" },
  { href: "/ops/trips", key: "trips" },
  { href: "/ops/map", key: "map" },
  { href: "/ops/containers", key: "containers" },
  { href: "/ops/fleet", key: "fleet" },
  { href: "/ops/customers", key: "customers" },
  { href: "/ops/geofences", key: "geofences" },
  { href: "/ops/notifications", key: "notifications" },
  { href: "/ops/team", key: "team" },
] as const;

export async function OpsNav({ current }: { current: (typeof NAV)[number]["key"] }) {
  const t = await getTranslations("Ops.nav");
  return (
    <nav aria-label="Operations" className="mb-6 flex flex-wrap gap-1 border-b pb-2">
      {NAV.map(({ href, key }) => (
        <Link
          key={key}
          href={href}
          prefetch={false}
          aria-current={key === current ? "page" : undefined}
          className={`rounded-md px-3 py-1.5 text-sm ${key === current ? "bg-muted font-medium" : "hover:bg-muted/60"}`}
        >
          {t(key)}
        </Link>
      ))}
    </nav>
  );
}

/** Error from a server action, passed back as ?error=<code>&ref=<request id>. */
export async function ActionError({
  code,
  requestId,
  fields,
}: {
  code?: string;
  requestId?: string;
  fields?: string;
}) {
  if (!code) return null;
  const t = await getTranslations("Ops.errors");
  const fieldList = (fields ?? "").split(",").filter((f) => /^[a-z_][a-z0-9_]*$/i.test(f)).slice(0, 5);
  return (
    <div role="alert" className="mb-4 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm">
      <p className="font-medium">
        {t("generic")} <code className="ms-1">{code}</code>
      </p>
      {fieldList.length > 0 ? (
        <p className="mt-1">
          {t("checkFields", {
            fields: fieldList.map((f) => (t.has(`field.${f}`) ? t(`field.${f}`) : f)).join(", "),
          })}
        </p>
      ) : null}
      {requestId ? <p className="mt-1 text-muted-foreground">{t("reference", { id: requestId })}</p> : null}
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-xs text-muted-foreground">{hint}</span> : null}
    </label>
  );
}

export const inputClass =
  "w-full rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring";
export const buttonClass =
  "inline-flex items-center rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50";
export const subtleButtonClass = "inline-flex items-center rounded-md border px-3 py-2 text-sm hover:bg-muted";

export function IdempotencyField() {
  // A fresh key per rendered form: resubmitting the same form replays instead of acting twice.
  return <input type="hidden" name="idempotency_key" value={crypto.randomUUID()} />;
}

export function formatDate(iso: string | null | undefined, locale: string): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short", timeZone: "Africa/Djibouti" }).format(
    new Date(iso),
  );
}
