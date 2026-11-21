import { getTranslations } from "next-intl/server";

import { AreaShell } from "@/components/area-shell";

export default async function Layout({ children }: LayoutProps<"/admin">) {
  const t = await getTranslations("Home");
  return (
    <AreaShell title={t("admin")} scope="admin">
      {children}
    </AreaShell>
  );
}
