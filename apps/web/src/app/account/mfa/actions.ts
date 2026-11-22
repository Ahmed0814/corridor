"use server";

import { cookies } from "next/headers";

import { COOKIES } from "@/lib/auth/config";
import { associate, mfaMode, validCode, verifyAndEnable } from "@/lib/auth/mfa";

export type MfaState = { step: "start" | "verify" | "done"; secret?: string; error?: string };

async function context(): Promise<{ token: string; region: string } | { error: string }> {
  const mode = mfaMode(process.env.AUTH_TOKEN_URL);
  if (mode.kind !== "cognito") return { error: "local_issuer" };
  const token = (await cookies()).get(COOKIES.access)?.value;
  if (!token) return { error: "unauthenticated" };
  return { token, region: mode.region };
}

export async function mfaStep(prev: MfaState, form: FormData): Promise<MfaState> {
  const ctx = await context();
  if ("error" in ctx) return { ...prev, error: ctx.error };

  if (prev.step === "start") {
    const result = await associate(ctx.region, ctx.token);
    return result.ok ? { step: "verify", secret: result.data.SecretCode } : { step: "start", error: result.code };
  }

  const code = String(form.get("code") ?? "").replace(/\s+/g, "");
  if (!validCode(code)) return { ...prev, error: "invalid_code" };
  const result = await verifyAndEnable(ctx.region, ctx.token, code);
  return result.ok ? { step: "done" } : { ...prev, error: result.code };
}
