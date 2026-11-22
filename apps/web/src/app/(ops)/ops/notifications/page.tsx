import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import { apiGet } from "@/lib/api";
import { type NotificationPage, safeNotificationLink } from "@/lib/phase6";

import { markAllNotificationsRead, markNotificationRead } from "../phase6-actions";
import { ActionError, formatDate, IdempotencyField, OpsNav, subtleButtonClass } from "../_components/ui";

export default async function Notifications({ searchParams }: PageProps<"/ops/notifications">) {
  const sp = await searchParams;
  const t = await getTranslations("Ops.notifications");
  const locale = await getLocale();
  const page = await apiGet<NotificationPage>("/notifications?limit=100");

  return (
    <section>
      <OpsNav current="notifications" />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">
          {t("title")}
          {page.ok && page.data.unread > 0 ? (
            <span className="ms-2 rounded-full bg-primary px-2 py-0.5 text-xs text-primary-foreground">{page.data.unread}</span>
          ) : null}
        </h1>
        {page.ok && page.data.unread > 0 ? (
          <form action={markAllNotificationsRead}>
            <IdempotencyField />
            <button type="submit" className={subtleButtonClass}>
              {t("markAll")}
            </button>
          </form>
        ) : null}
      </div>
      <ActionError code={sp.error as string | undefined} requestId={sp.ref as string | undefined} />
      {!page.ok ? (
        <ActionError code={page.error.code} requestId={page.error.requestId ?? undefined} />
      ) : page.data.items.length === 0 ? (
        <p className="mt-4 text-sm text-muted-foreground">{t("empty")}</p>
      ) : (
        <ul className="mt-4 divide-y rounded-lg border">
          {page.data.items.map((n) => {
            const href = safeNotificationLink(n.link);
            return (
              <li key={n.id} className={`flex flex-wrap items-start justify-between gap-3 p-3 ${n.read_at ? "" : "bg-muted/40"}`}>
                <div className="text-sm">
                  <p className={n.read_at ? "" : "font-medium"}>
                    {href ? (
                      <Link href={href} prefetch={false} className="underline-offset-4 hover:underline">
                        {n.title}
                      </Link>
                    ) : (
                      n.title
                    )}
                  </p>
                  {n.body ? <p className="text-muted-foreground">{n.body}</p> : null}
                  <p className="text-xs text-muted-foreground">{formatDate(n.created_at, locale)}</p>
                </div>
                {n.read_at ? null : (
                  <form action={markNotificationRead}>
                    <IdempotencyField />
                    <input type="hidden" name="notification_id" value={n.id} />
                    <button type="submit" className={subtleButtonClass}>
                      {t("markRead")}
                    </button>
                  </form>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
