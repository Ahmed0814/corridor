import { getTranslations } from "next-intl/server";

import { AreaLayout } from "@/components/area-layout";

// Per-user content: never statically rendered or cached.
export const dynamic = "force-dynamic";

export default async function Layout({ children }: LayoutProps<"/ops">) {
  const t = await getTranslations("Home");
  return (
    <AreaLayout area="ops" title={t("ops")}>
      {children}
    </AreaLayout>
  );
}
