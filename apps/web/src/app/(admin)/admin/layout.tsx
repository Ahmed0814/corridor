import { getTranslations } from "next-intl/server";

import { AreaLayout } from "@/components/area-layout";

// Per-user content: never statically rendered or cached.
export const dynamic = "force-dynamic";

export default async function Layout({ children }: LayoutProps<"/admin">) {
  const t = await getTranslations("Home");
  return (
    <AreaLayout area="admin" title={t("admin")}>
      {children}
    </AreaLayout>
  );
}
