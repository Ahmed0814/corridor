import type { Metadata } from "next";
import { cookies } from "next/headers";
import { getTranslations } from "next-intl/server";

import { type Me, apiGet } from "@/lib/api";
import { COOKIES } from "@/lib/auth/config";
import { mfaMode } from "@/lib/auth/mfa";

import { MfaForm } from "./mfa-form";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Authenticator setup", robots: { index: false } };

export default async function MfaPage() {
  const t = await getTranslations("Mfa");
  const store = await cookies();
  const client = store.get(COOKIES.client)?.value;
  const area = client === "portal" ? "portal" : "ops";
  const signIn = `/auth/login?area=${area}&next=${encodeURIComponent("/account/mfa")}`;

  if (!store.has(COOKIES.access)) {
    return (
      <main className="mx-auto max-w-xl space-y-4 p-6">
        <h1 className="text-xl font-semibold">{t("title")}</h1>
        <p className="text-sm">{t("signInFirst")}</p>
        <a href={signIn} className="text-sm underline-offset-4 hover:underline">
          {t("signIn")}
        </a>
      </main>
    );
  }

  const mode = mfaMode(process.env.AUTH_TOKEN_URL);
  const me = await apiGet<Me>("/me");
  const account = me.ok ? (me.data.email ?? me.data.display_name) : "corridor";

  return (
    <main className="mx-auto max-w-xl space-y-4 p-6">
      <h1 className="text-xl font-semibold">{t("title")}</h1>
      {me.ok && me.data.mfa_verified ? <p className="text-sm text-emerald-700">{t("alreadyOn")}</p> : null}
      {mode.kind === "local" ? (
        <p className="text-sm">{t("localNote")}</p>
      ) : (
        <MfaForm account={account} />
      )}
      <p className="text-xs text-muted-foreground">{t("apps")}</p>
    </main>
  );
}
