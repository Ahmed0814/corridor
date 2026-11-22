"use client";

import QRCode from "qrcode";
import { useTranslations } from "next-intl";
import { useActionState, useEffect, useState } from "react";

import { groupSecret, otpauthUri } from "@/lib/auth/mfa";

import { type MfaState, mfaStep } from "./actions";

const button =
  "inline-flex items-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50";

export function MfaForm({ account }: { account: string }) {
  const t = useTranslations("Mfa");
  const [state, action, pending] = useActionState<MfaState, FormData>(mfaStep, { step: "start" });
  const [qr, setQr] = useState<string | null>(null);
  const uri = state.secret ? otpauthUri(state.secret, account) : null;

  useEffect(() => {
    if (!uri) return;
    let cancelled = false;
    void QRCode.toDataURL(uri, { margin: 1, width: 220 }).then((url) => {
      if (!cancelled) setQr(url);
    });
    return () => {
      cancelled = true;
    };
  }, [uri]);

  if (state.step === "done") {
    return (
      <div role="status" className="space-y-3 rounded-lg border border-emerald-500/40 p-4 text-sm">
        <p className="font-medium">{t("done")}</p>
        <p>{t("doneNext")}</p>
        {/* Sign out (POST only), then sign in again: Cognito now asks for the authenticator code. */}
        <form method="post" action="/auth/logout">
          <button type="submit" className={button}>
            {t("signInAgain")}
          </button>
        </form>
      </div>
    );
  }

  return (
    <form action={action} className="space-y-4 text-sm">
      {state.step === "start" ? (
        <>
          <p>{t("intro")}</p>
          <button type="submit" disabled={pending} className={button}>
            {t("start")}
          </button>
        </>
      ) : (
        <>
          <ol className="list-decimal space-y-3 ps-5">
            <li>
              {t("scan")}
              <div className="mt-2 flex flex-wrap items-start gap-4">
                {qr ? (
                  // eslint-disable-next-line @next/next/no-img-element -- a data: URL generated locally
                  <img src={qr} alt={t("qrAlt")} width={220} height={220} className="rounded border bg-white p-1" />
                ) : null}
                <div className="space-y-1">
                  <p className="text-muted-foreground">{t("manual")}</p>
                  <code className="block rounded bg-muted px-2 py-1 font-mono text-base tracking-wider">
                    {groupSecret(state.secret ?? "")}
                  </code>
                  {uri ? (
                    <a href={uri} className="underline-offset-4 hover:underline">
                      {t("openOnPhone")}
                    </a>
                  ) : null}
                </div>
              </div>
            </li>
            <li>
              <label className="block">
                {t("enterCode")}
                <input
                  name="code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  pattern="[0-9 ]{6,7}"
                  maxLength={7}
                  required
                  className="mt-1 block w-40 rounded-md border bg-background px-3 py-2 font-mono text-lg tracking-widest"
                />
              </label>
            </li>
          </ol>
          <button type="submit" disabled={pending} className={button}>
            {t("verify")}
          </button>
        </>
      )}
      {state.error ? (
        <p role="alert" className="text-destructive">
          {t.has(`errors.${state.error}`) ? t(`errors.${state.error}`) : t("errors.generic", { code: state.error })}
        </p>
      ) : null}
    </form>
  );
}
