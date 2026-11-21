import { getFormatter, getTranslations } from "next-intl/server";

import { ReadinessList } from "@/components/readiness-list";
import { fetchReadiness } from "@/lib/health";

export const dynamic = "force-dynamic";

export default async function StatusPage() {
  const t = await getTranslations("Status");
  const format = await getFormatter();
  // Server-side call inside the cluster/compose network; never exposed to the browser.
  const readiness = await fetchReadiness(process.env.API_INTERNAL_URL ?? "http://localhost:8000");
  return (
    <main className="mx-auto w-full max-w-xl px-4 py-12">
      <h1 className="text-xl font-semibold">{t("title")}</h1>
      <div className="mt-6 rounded-lg border px-4">
        <ReadinessList
          readiness={readiness}
          labels={{
            api: t("api"),
            database: t("database"),
            redis: t("redis"),
            ok: t("ok"),
            down: t("down"),
            unreachable: t("unreachable"),
          }}
        />
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        {t("checkedAt", { time: format.dateTime(new Date(), { timeStyle: "medium" }) })}
      </p>
    </main>
  );
}
