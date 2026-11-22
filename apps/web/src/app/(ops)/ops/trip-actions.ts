"use server";

// Office trip actions. Start/pause/resume/complete/abort from the office are on behalf of the
// driver: the API requires trips.act_on_behalf and a reason, and records who did it.

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { apiSend } from "@/lib/api";
import { errorQuery } from "@/lib/forms";
import { TRIP_ACTIONS, type TripAction } from "@/lib/trips";

const UUID = /^[0-9a-f-]{36}$/i;

function text(form: FormData, name: string): string {
  const v = form.get(name);
  return typeof v === "string" ? v.trim() : "";
}

export async function tripAction(form: FormData): Promise<void> {
  const id = text(form, "trip_id");
  const action = text(form, "action") as TripAction;
  const back = UUID.test(id) ? `/ops/trips/${id}` : "/ops/trips";
  if (!UUID.test(id) || !TRIP_ACTIONS.includes(action)) redirect(`${back}?error=bad_request`);
  const k = text(form, "idempotency_key");
  const key = /^[A-Za-z0-9._:-]{8,128}$/.test(k) ? k : crypto.randomUUID();
  const result = await apiSend("POST", `/trips/${id}/${action}`, { reason: text(form, "reason") }, key);
  if (!result.ok) {
    redirect(`${back}?${errorQuery(result.error)}`);
  }
  revalidatePath("/ops", "layout");
  redirect(back);
}
