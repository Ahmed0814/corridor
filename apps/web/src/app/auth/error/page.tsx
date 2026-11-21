import Link from "next/link";
import { getTranslations } from "next-intl/server";

export default async function AuthErrorPage({ searchParams }: PageProps<"/auth/error">) {
  const t = await getTranslations("Session");
  const { reason } = await searchParams;
  return (
    <main className="mx-auto w-full max-w-xl px-4 py-12">
      <h1 className="text-xl font-semibold">{t("signInFailed")}</h1>
      <p className="mt-2 text-muted-foreground" data-reason={typeof reason === "string" ? reason : "unknown"}>
        {t("signInFailedHelp")}
      </p>
      <Link href="/" className="mt-6 inline-block underline underline-offset-4">
        {t("backHome")}
      </Link>
    </main>
  );
}
