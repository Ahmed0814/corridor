import { getTranslations } from "next-intl/server";

import { AreaShell } from "@/components/area-shell";

export default async function Layout({ children }: LayoutProps<"/ops">) {
  const t = await getTranslations("Home");
  return (
    <AreaShell title={t("ops")} scope="ops">
      {children}
    </AreaShell>
  );
}
