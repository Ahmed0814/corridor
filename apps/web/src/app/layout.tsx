import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getTranslations } from "next-intl/server";

import { textDirection } from "@/i18n/config";

import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("App");
  return { title: { default: t("name"), template: `%s · ${t("name")}` }, description: t("tagline") };
}

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const locale = await getLocale();
  return (
    <html lang={locale} dir={textDirection(locale)} className="h-full antialiased">
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <NextIntlClientProvider>{children}</NextIntlClientProvider>
      </body>
    </html>
  );
}
