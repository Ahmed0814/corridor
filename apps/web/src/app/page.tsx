import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const AREAS = [
  { href: "/ops", key: "ops" },
  { href: "/portal", key: "portal" },
  { href: "/admin", key: "admin" },
] as const;

export default async function HomePage() {
  const t = await getTranslations();
  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-12">
      <h1 className="text-2xl font-semibold">{t("App.name")}</h1>
      <p className="mt-2 text-muted-foreground">{t("App.tagline")}</p>
      <h2 className="mt-10 text-sm font-medium uppercase tracking-wide text-muted-foreground">
        {t("Home.chooseArea")}
      </h2>
      <div className="mt-4 grid gap-4 sm:grid-cols-3">
        {AREAS.map(({ href, key }) => (
          <Link key={href} href={href} prefetch={false} className="rounded-xl focus-visible:outline-2 focus-visible:outline-ring">
            <Card className="h-full transition-colors hover:bg-muted">
              <CardHeader>
                <CardTitle>{t(`Home.${key}`)}</CardTitle>
                <CardDescription>{t(`Home.${key}Description`)}</CardDescription>
              </CardHeader>
            </Card>
          </Link>
        ))}
      </div>
      <p className="mt-10">
        <Link href="/track" prefetch={false} className="me-4 text-sm font-medium underline underline-offset-4">
          {t("Home.trackContainer")}
        </Link>
        <Link href="/status" className="text-sm underline underline-offset-4">
          {t("Home.status")}
        </Link>
      </p>
    </main>
  );
}
