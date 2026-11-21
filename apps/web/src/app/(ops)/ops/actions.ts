"use server";

// Server actions for the operations screens. They run on the server with the user's session;
// the API enforces permissions, tenant isolation and the state machines. No client-side logic
// decides anything: errors come back from the API and are shown on the page.

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { type ApiResult, apiSend } from "@/lib/api";
import { actionBody, type ShipmentAction } from "@/lib/logistics";

const SHIPMENT_ACTIONS = new Set<ShipmentAction>([
  "confirm",
  "cancel",
  "border-arrival",
  "border-clearance",
  "deliver",
  "delivery-failed",
  "reattempt",
  "delay",
]);

function text(form: FormData, name: string): string {
  const v = form.get(name);
  return typeof v === "string" ? v.trim() : "";
}

function key(form: FormData): string {
  const k = text(form, "idempotency_key");
  return k || crypto.randomUUID();
}

/** Relative paths only: never redirect to a URL taken from user input. */
function safePath(path: string, fallback: string): string {
  return path.startsWith("/ops") && !path.startsWith("//") ? path : fallback;
}

function finish<T>(result: ApiResult<T>, back: string, success?: string): never {
  if (!result.ok) {
    const q = new URLSearchParams({ error: result.error.code });
    if (result.error.requestId) q.set("ref", result.error.requestId);
    redirect(`${back}?${q.toString()}`);
  }
  revalidatePath("/ops", "layout");
  redirect(success ?? back);
}

export async function createCustomer(form: FormData): Promise<void> {
  const body = { name: text(form, "name"), email: text(form, "email"), phone_e164: text(form, "phone_e164") };
  finish(await apiSend("POST", "/customers", body, key(form)), "/ops/customers");
}

export async function createShipment(form: FormData): Promise<void> {
  const weight = text(form, "weight_kg");
  const body = {
    customer_id: text(form, "customer_id"),
    origin_label: text(form, "origin_label"),
    destination_label: text(form, "destination_label"),
    cargo_description: text(form, "cargo_description"),
    weight_kg: weight ? Number(weight) : null,
    container_ids: form.getAll("container_ids").filter((v): v is string => typeof v === "string" && v !== ""),
  };
  const result = await apiSend<{ id: string }>("POST", "/shipments", body, key(form));
  finish(result, "/ops/shipments", result.ok ? `/ops/shipments/${result.data.id}` : undefined);
}

export async function shipmentAction(form: FormData): Promise<void> {
  const id = text(form, "shipment_id");
  const action = text(form, "action") as ShipmentAction;
  const back = safePath(`/ops/shipments/${id}`, "/ops/shipments");
  if (!/^[0-9a-f-]{36}$/i.test(id) || !SHIPMENT_ACTIONS.has(action)) redirect(`${back}?error=bad_request`);
  const body = actionBody(action, {
    reason: text(form, "reason"),
    border: text(form, "border"),
    recipient: text(form, "recipient"),
  });
  finish(await apiSend("POST", `/shipments/${id}/${action}`, body, key(form)), back);
}

export async function dispatchPlan(form: FormData): Promise<void> {
  const body = {
    shipment_ids: form.getAll("shipment_ids").filter((v): v is string => typeof v === "string" && v !== ""),
    vehicle_id: text(form, "vehicle_id"),
    driver_id: text(form, "driver_id"),
    origin_label: text(form, "origin_label"),
    destination_label: text(form, "destination_label"),
  };
  finish(await apiSend("POST", "/dispatch", body, key(form)), "/ops/dispatch");
}

export async function createVehicle(form: FormData): Promise<void> {
  const body = { plate: text(form, "plate"), kind: text(form, "kind") || "tractor" };
  finish(await apiSend("POST", "/vehicles", body, key(form)), "/ops/fleet");
}

export async function setVehicleStatus(form: FormData): Promise<void> {
  const id = text(form, "vehicle_id");
  if (!/^[0-9a-f-]{36}$/i.test(id)) redirect("/ops/fleet?error=bad_request");
  const body = { status: text(form, "status") };
  finish(await apiSend("POST", `/vehicles/${id}/status`, body, key(form)), "/ops/fleet");
}

export async function createDriver(form: FormData): Promise<void> {
  const expiry = text(form, "license_expiry");
  const body = {
    full_name: text(form, "full_name"),
    phone_e164: text(form, "phone_e164"),
    license_number: text(form, "license_number"),
    license_expiry: expiry || null,
  };
  finish(await apiSend("POST", "/drivers", body, key(form)), "/ops/fleet");
}
