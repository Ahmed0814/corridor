// TOTP (authenticator app) enrolment against Cognito with the user's own access token
// (DECISIONS D-073). Server-side only: the token stays in the HttpOnly cookie.
//
// Cognito's hosted sign-in does not walk users through MFA setup when MFA is optional, so the app
// does it: AssociateSoftwareToken -> show the secret / QR -> VerifySoftwareToken with a code from
// the app -> SetUserMFAPreference (TOTP enabled and preferred). These are Cognito "user" APIs:
// no AWS credentials, only an access token with the aws.cognito.signin.user.admin scope.

export const ACCOUNT_SCOPE = "aws.cognito.signin.user.admin";

export type MfaMode = { kind: "cognito"; region: string } | { kind: "local" };

/** Cognito when the token endpoint is a Cognito hosted domain; otherwise the local dev issuer. */
export function mfaMode(tokenUrl: string | undefined): MfaMode {
  const m = /^https:\/\/[a-z0-9-]+\.auth\.([a-z0-9-]+)\.amazoncognito\.com\//.exec(tokenUrl ?? "");
  return m ? { kind: "cognito", region: m[1] } : { kind: "local" };
}

/** otpauth:// URI understood by Google/Microsoft Authenticator and others. */
export function otpauthUri(secret: string, account: string, issuer = "Corridor"): string {
  const label = encodeURIComponent(`${issuer}:${account}`);
  return `otpauth://totp/${label}?secret=${encodeURIComponent(secret)}&issuer=${encodeURIComponent(issuer)}`;
}

/** Secret in groups of four for manual entry. */
export function groupSecret(secret: string): string {
  return secret.replace(/(.{4})/g, "$1 ").trim();
}

export function validCode(code: string): boolean {
  return /^\d{6}$/.test(code);
}

export type CognitoResult<T> = { ok: true; data: T } | { ok: false; code: string };

async function call<T>(region: string, target: string, body: Record<string, unknown>): Promise<CognitoResult<T>> {
  try {
    const response = await fetch(`https://cognito-idp.${region}.amazonaws.com/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": `AWSCognitoIdentityProviderService.${target}`,
      },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    const data: unknown = await response.json().catch(() => null);
    if (response.ok) return { ok: true, data: data as T };
    const type = String((data as { __type?: string } | null)?.__type ?? "error");
    return { ok: false, code: type.split("#").pop() ?? type };
  } catch {
    return { ok: false, code: "unreachable" };
  }
}

export function associate(region: string, accessToken: string) {
  return call<{ SecretCode: string }>(region, "AssociateSoftwareToken", { AccessToken: accessToken });
}

export async function verifyAndEnable(region: string, accessToken: string, code: string): Promise<CognitoResult<null>> {
  const verified = await call<{ Status: string }>(region, "VerifySoftwareToken", {
    AccessToken: accessToken,
    UserCode: code,
    FriendlyDeviceName: "Authenticator",
  });
  if (!verified.ok) return verified;
  if (verified.data.Status !== "SUCCESS") return { ok: false, code: "CodeMismatchException" };
  const pref = await call<unknown>(region, "SetUserMFAPreference", {
    AccessToken: accessToken,
    SoftwareTokenMfaSettings: { Enabled: true, PreferredMfa: true },
  });
  return pref.ok ? { ok: true, data: null } : pref;
}
