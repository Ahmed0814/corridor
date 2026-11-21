import { getTranslations } from "next-intl/server";

import { NotBuiltNotice } from "@/components/area-shell";

export default async function Page() {
  const t = await getTranslations();
  return (
    <section>
      <h1 className="text-xl font-semibold">{t("Home.ops")}</h1>
      <p className="mt-1 text-muted-foreground">{t("Home.opsDescription")}</p>
      <div className="mt-6">
        <NotBuiltNotice notBuilt={t("Area.notBuilt")} noData={t("Area.noData")} />
      </div>
    </section>
  );
}
