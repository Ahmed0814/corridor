import { getTranslations } from "next-intl/server";

import { AreaShell } from "@/components/area-shell";

export default async function Layout({ children }: LayoutProps<"/portal">) {
  const t = await getTranslations("Home");
  return (
    <AreaShell title={t("portal")} scope="portal">
      {children}
    </AreaShell>
  );
}
