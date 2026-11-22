"use server";

// Team management: invite members, change roles, suspend/reactivate, and link driver / customer
// accounts to their profiles. The API enforces every rule (who may do what, owner protections).

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { type ApiResult, apiSend } from "@/lib/api";
import { ROLES } from "@/lib/team";

const UUID = /^[0-9a-f-]{36}$/i;
const BACK = "/ops/team";

function text(form: FormData, name: string): string {
  const v = form.get(name);
  return typeof v === "string" ? v.trim() : "";
}

function key(form: FormData): string {
  const k = text(form, "idempotency_key");
  return /^[A-Za-z0-9._:-]{8,128}$/.test(k) ? k : crypto.randomUUID();
}

function finish<T>(result: ApiResult<T>, success?: string): never {
  if (!result.ok) {
    const q = new URLSearchParams({ error: result.error.code });
    if (result.error.requestId) q.set("ref", result.error.requestId);
    redirect(`${BACK}?${q.toString()}`);
  }
  revalidatePath(BACK);
  redirect(success ? `${BACK}?done=${success}` : BACK);
}

export async function inviteMember(form: FormData): Promise<void> {
  const role = text(form, "role");
  if (!(ROLES as readonly string[]).includes(role)) redirect(`${BACK}?error=bad_request`);
  const body = { email: text(form, "email").toLowerCase(), display_name: text(form, "display_name"), role };
  finish(await apiSend("POST", "/memberships", body, key(form)), "invited");
}

export async function changeRole(form: FormData): Promise<void> {
  const id = text(form, "membership_id");
  const role = text(form, "role");
  if (!UUID.test(id) || !(ROLES as readonly string[]).includes(role)) redirect(`${BACK}?error=bad_request`);
  finish(await apiSend("POST", `/memberships/${id}/role`, { role }, key(form)));
}

export async function setMemberStatus(form: FormData): Promise<void> {
  const id = text(form, "membership_id");
  const action = text(form, "action");
  if (!UUID.test(id) || !["suspend", "reactivate"].includes(action)) redirect(`${BACK}?error=bad_request`);
  finish(await apiSend("POST", `/memberships/${id}/${action}`, {}, key(form)));
}

export async function linkDriver(form: FormData): Promise<void> {
  const membershipId = text(form, "membership_id");
  const driverId = text(form, "driver_id");
  if (!UUID.test(membershipId) || !UUID.test(driverId)) redirect(`${BACK}?error=bad_request`);
  finish(await apiSend("POST", `/drivers/${driverId}/link`, { membership_id: membershipId }, key(form)), "linked");
}

export async function linkCustomer(form: FormData): Promise<void> {
  const membershipId = text(form, "membership_id");
  const customerId = text(form, "customer_id");
  if (!UUID.test(membershipId) || !UUID.test(customerId)) redirect(`${BACK}?error=bad_request`);
  finish(
    await apiSend("POST", `/customers/${customerId}/portal-users`, { membership_id: membershipId }, key(form)),
    "linked",
  );
}
