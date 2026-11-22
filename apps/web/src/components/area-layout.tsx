import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { AreaShell } from "@/components/area-shell";
import { Badge } from "@/components/ui/badge";
import { type ApiResult, apiGet, type Me } from "@/lib/api";
import type { Area } from "@/lib/auth/config";

/** Problems the API reports for a valid sign-in, mapped to a message key in "Session". */
const PROBLEMS: Record<string, string> = {
  no_access: "noAccess",
  no_membership: "noMembership",
  membership_suspended: "membershipSuspended",
  tenant_suspended: "tenantSuspended",
  wrong_client: "wrongClient",
  not_found: "tenantNotFound",
  unreachable: "unreachable",
  session_rejected: "sessionRejected",
};

export type SessionState =
  | { kind: "problem"; code: string; requestId: string | null }
  | { kind: "ready"; me: Me };

/** Pure mapping from the /me result to what the layout shows (unit-tested). */
export function sessionState(result: ApiResult<Me>, area: Area): SessionState {
  if (!result.ok) {
    // The proxy only lets requests with a session cookie through, so a 401 here means the API
    // rejected the token. Show it instead of redirecting (a misconfiguration would loop).
    if (result.status === 401) return { kind: "problem", code: "session_rejected", requestId: result.error.requestId };
    return { kind: "problem", code: result.error.code, requestId: result.error.requestId };
  }
  const me = result.data;
  if (area === "admin" && !me.is_platform_admin) return { kind: "problem", code: "not_platform_admin", requestId: null };
  if (area !== "admin" && me.active_tenant === null) return { kind: "problem", code: "no_membership", requestId: null };
  return { kind: "ready", me };
}

export async function AreaLayout({ area, title, children }: { area: Area; title: string; children: ReactNode }) {
  const t = await getTranslations("Session");
  const state = sessionState(await apiGet<Me>("/me"), area);

  const signOut = (
    <form action="/auth/logout" method="post">
      <button type="submit" className="text-sm underline underline-offset-4">
        {t("signOut")}
      </button>
    </form>
  );

  if (state.kind === "problem") {
    const key = PROBLEMS[state.code] ?? (state.code === "not_platform_admin" ? "notPlatformAdmin" : "generic");
    return (
      <AreaShell title={title} scope={area} actions={signOut}>
        <div role="alert" className="rounded-lg border border-destructive/40 p-6">
          <p className="font-medium">{t(key)}</p>
          {state.code === "session_rejected" ? (
            <a className="mt-3 inline-block underline underline-offset-4" href={`/auth/login?area=${area}`}>
              {t("signInAgain")}
            </a>
          ) : null}
          {state.requestId ? (
            <p className="mt-2 text-sm text-muted-foreground">{t("reference", { id: state.requestId })}</p>
          ) : null}
        </div>
      </AreaShell>
    );
  }

  const { me } = state;
  const active = me.active_tenant;
  const switchable = me.memberships.filter((m) => m.status !== "suspended" && m.tenant_status === "active");
  const actions = (
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <span>{me.display_name || me.email}</span>
      {active ? <Badge variant="secondary">{t(`roles.${active.role}`)}</Badge> : null}
      {area !== "admin" && switchable.length > 1 ? (
        <form action="/auth/tenant" method="post" className="flex items-center gap-2">
          <input type="hidden" name="next" value={`/${area}`} />
          <label htmlFor="tenant" className="sr-only">
            {t("company")}
          </label>
          <select id="tenant" name="tenant" defaultValue={active?.tenant_slug} className="rounded border px-2 py-1">
            {switchable.map((m) => (
              <option key={m.tenant_id} value={m.tenant_slug}>
                {m.tenant_name}
              </option>
            ))}
          </select>
          <button type="submit" className="underline underline-offset-4">
            {t("switch")}
          </button>
        </form>
      ) : active && area !== "admin" ? (
        <span className="text-muted-foreground">{active.tenant_name}</span>
      ) : null}
      {signOut}
    </div>
  );

  return (
    <AreaShell title={title} scope={area} actions={actions}>
      {me.mfa_required ? (
        <div role="alert" className="mb-6 rounded-lg border border-amber-500/60 p-4 text-sm" data-mfa="required">
          {t("mfaRequired")}{" "}
          <a href="/account/mfa" className="font-medium underline underline-offset-4">
            {t("mfaSetup")}
          </a>
        </div>
      ) : null}
      {area === "admin" && !me.mfa_verified ? (
        <div role="alert" className="mb-6 rounded-lg border border-amber-500/60 p-4 text-sm" data-mfa="required">
          {t("mfaRequired")}
        </div>
      ) : null}
      {children}
    </AreaShell>
  );
}
