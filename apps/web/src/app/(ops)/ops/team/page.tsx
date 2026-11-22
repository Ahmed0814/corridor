import { getLocale, getTranslations } from "next-intl/server";

import { type Me, apiGet } from "@/lib/api";
import type { Customer, Driver, Page } from "@/lib/logistics";
import { assignableRoles, type Member, memberNeedsLink, unlinkedDrivers } from "@/lib/team";

import { changeRole, inviteMember, linkCustomer, linkDriver, setMemberStatus } from "../team-actions";
import {
  ActionError,
  buttonClass,
  Field,
  formatDate,
  IdempotencyField,
  inputClass,
  OpsNav,
  StatusBadge,
  subtleButtonClass,
} from "../_components/ui";

export default async function TeamPage({ searchParams }: PageProps<"/ops/team">) {
  const sp = await searchParams;
  const t = await getTranslations("Ops");
  const locale = await getLocale();
  const me = await apiGet<Me>("/me");
  const perms = me.ok ? me.data.permissions : [];
  const canManage = perms.includes("users.manage");
  const canAssign = perms.includes("roles.assign");
  const canLinkDrivers = perms.includes("drivers.write");

  if (!canManage) {
    return (
      <section>
        <OpsNav current="team" />
        <h1 className="text-xl font-semibold">{t("team.title")}</h1>
        <p className="mt-2 text-sm text-muted-foreground">{t("team.noAccess")}</p>
      </section>
    );
  }

  const [members, drivers, customers] = await Promise.all([
    apiGet<Member[]>("/memberships"),
    apiGet<Page<Driver>>("/drivers?limit=200"),
    apiGet<Page<Customer>>("/customers?limit=200"),
  ]);
  const myRole = me.ok ? me.data.active_tenant?.role : null;
  const roles = assignableRoles(myRole);
  const freeDrivers = unlinkedDrivers(drivers.ok ? drivers.data.items : []);
  const customerList = customers.ok ? customers.data.items : [];
  const driverName = new Map((drivers.ok ? drivers.data.items : []).map((d) => [d.id, d.full_name]));
  const customerName = new Map(customerList.map((c) => [c.id, c.name]));
  const done = typeof sp.done === "string" ? sp.done : undefined;

  return (
    <section>
      <OpsNav current="team" />
      <h1 className="text-xl font-semibold">{t("team.title")}</h1>
      <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{t("team.description")}</p>
      <ActionError code={sp.error as string | undefined} requestId={sp.ref as string | undefined} />
      {done === "invited" ? (
        <p role="status" className="mt-3 rounded-md border border-emerald-500/40 p-3 text-sm">
          {t("team.invited")}
        </p>
      ) : null}
      {!members.ok ? <ActionError code={members.error.code} requestId={members.error.requestId ?? undefined} /> : null}

      <div className="mt-4 overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            <tr>
              <th className="px-3 py-2 text-start font-medium">{t("team.member")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("team.role")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("common.status")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("team.linkedTo")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("team.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {(members.ok ? members.data : []).map((m) => {
              const isMe = me.ok && m.user_id === me.data.user_id;
              const needs = memberNeedsLink(m);
              return (
                <tr key={m.id} className="border-t align-top">
                  <td className="px-3 py-2">
                    <span className="font-medium">{m.display_name || m.email || m.phone_masked}</span>
                    {isMe ? <span className="ms-2 text-xs text-muted-foreground">({t("team.you")})</span> : null}
                    <p className="text-xs text-muted-foreground">{m.email ?? m.phone_masked}</p>
                    <p className="text-xs text-muted-foreground">
                      {t("team.since", { at: formatDate(m.activated_at ?? m.created_at, locale) })}
                    </p>
                  </td>
                  <td className="px-3 py-2">
                    {canAssign && !isMe ? (
                      <form action={changeRole} className="flex items-center gap-1">
                        <IdempotencyField />
                        <input type="hidden" name="membership_id" value={m.id} />
                        <select name="role" defaultValue={m.role} className={`${inputClass} h-8 w-40`} aria-label={t("team.role")}>
                          {roles.includes(m.role) ? null : <option value={m.role}>{t(`team.roles.${m.role}`)}</option>}
                          {roles.map((r) => (
                            <option key={r} value={r}>
                              {t(`team.roles.${r}`)}
                            </option>
                          ))}
                        </select>
                        <button type="submit" className={subtleButtonClass}>
                          {t("common.save")}
                        </button>
                      </form>
                    ) : (
                      t(`team.roles.${m.role}`)
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <StatusBadge status={`member_${m.status}`} />
                  </td>
                  <td className="px-3 py-2">
                    {m.driver_id ? (
                      <span>
                        {t("team.driverProfile")}: {driverName.get(m.driver_id) ?? "—"}
                      </span>
                    ) : null}
                    {m.customer_id ? (
                      <span>
                        {t("team.customerCompany")}: {customerName.get(m.customer_id) ?? "—"}
                      </span>
                    ) : null}
                    {needs === "driver" ? (
                      canLinkDrivers && freeDrivers.length > 0 ? (
                        <form action={linkDriver} className="flex items-center gap-1">
                          <IdempotencyField />
                          <input type="hidden" name="membership_id" value={m.id} />
                          <select name="driver_id" required className={`${inputClass} h-8 w-44`} aria-label={t("team.driverProfile")}>
                            {freeDrivers.map((d) => (
                              <option key={d.id} value={d.id}>
                                {d.full_name}
                              </option>
                            ))}
                          </select>
                          <button type="submit" className={subtleButtonClass}>
                            {t("team.link")}
                          </button>
                        </form>
                      ) : (
                        <span className="text-xs text-amber-700">{t("team.needsDriverProfile")}</span>
                      )
                    ) : null}
                    {needs === "customer" ? (
                      customerList.length > 0 ? (
                        <form action={linkCustomer} className="flex items-center gap-1">
                          <IdempotencyField />
                          <input type="hidden" name="membership_id" value={m.id} />
                          <select name="customer_id" required className={`${inputClass} h-8 w-44`} aria-label={t("team.customerCompany")}>
                            {customerList.map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.name}
                              </option>
                            ))}
                          </select>
                          <button type="submit" className={subtleButtonClass}>
                            {t("team.link")}
                          </button>
                        </form>
                      ) : (
                        <span className="text-xs text-amber-700">{t("team.needsCustomer")}</span>
                      )
                    ) : null}
                    {!m.driver_id && !m.customer_id && !needs ? <span className="text-muted-foreground">—</span> : null}
                  </td>
                  <td className="px-3 py-2">
                    {!isMe ? (
                      <form action={setMemberStatus}>
                        <IdempotencyField />
                        <input type="hidden" name="membership_id" value={m.id} />
                        <input type="hidden" name="action" value={m.status === "suspended" ? "reactivate" : "suspend"} />
                        <button type="submit" className={subtleButtonClass}>
                          {m.status === "suspended" ? t("team.reactivate") : t("team.suspend")}
                        </button>
                      </form>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <form action={inviteMember} className="mt-6 grid max-w-3xl gap-3 rounded-lg border p-4 sm:grid-cols-3">
        <h2 className="text-base font-semibold sm:col-span-3">{t("team.invite")}</h2>
        <IdempotencyField />
        <Field label={t("team.email")}>
          <input name="email" type="email" required maxLength={254} className={inputClass} />
        </Field>
        <Field label={t("team.name")} hint={t("common.optional")}>
          <input name="display_name" maxLength={200} className={inputClass} />
        </Field>
        <Field label={t("team.role")}>
          <select name="role" defaultValue="dispatcher" className={inputClass}>
            {roles.map((r) => (
              <option key={r} value={r}>
                {t(`team.roles.${r}`)}
              </option>
            ))}
          </select>
        </Field>
        <p className="text-xs text-muted-foreground sm:col-span-3">{t("team.inviteNote")}</p>
        <div className="sm:col-span-3">
          <button type="submit" className={buttonClass}>
            {t("team.sendInvite")}
          </button>
        </div>
      </form>
    </section>
  );
}
