// Types mirroring the /api/v1 logistics schemas, plus pure UI logic (unit-tested).

export type Page<T> = { items: T[]; next_cursor: string | null };

export type ShipmentStatus =
  | "draft"
  | "confirmed"
  | "dispatched"
  | "in_transit"
  | "at_border"
  | "delivered"
  | "delivery_failed"
  | "cancelled";

export type Shipment = {
  id: string;
  reference: string;
  customer_id: string;
  customer_name: string | null;
  status: ShipmentStatus;
  is_delayed: boolean;
  delay_reason: string;
  cargo_description: string;
  weight_kg: number | null;
  origin_label: string;
  destination_label: string;
  eta: string | null;
  delivered_at: string | null;
  recipient_name: string;
  containers: { id: string; number: string }[];
  trip_ids: string[];
  created_at: string;
  updated_at: string;
};

export type LifecycleEvent = {
  id: number;
  type: string;
  from_status: string;
  to_status: string;
  actor_kind: string;
  actor_user_id: string | null;
  reason: string;
  payload: Record<string, unknown>;
  occurred_at: string;
};

export type Trip = {
  id: string;
  reference: string;
  status: string;
  origin_label: string;
  destination_label: string;
  shipment_ids: string[];
  assignment: { vehicle_id: string; vehicle_plate: string | null; driver_id: string; driver_name: string | null } | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
};

export type Customer = { id: string; name: string; email: string; phone_e164: string; status: string; created_at: string };
export type Container = { id: string; number: string; size_ft: number; condition: string; availability: string };
export type Vehicle = { id: string; plate: string; kind: string; status: string; assigned_trip_id: string | null };
export type Driver = {
  id: string;
  full_name: string;
  employment_status: string;
  license_expiry: string | null;
  membership_id: string | null;
  tracking_consent: boolean;
};

export type Tone = "neutral" | "info" | "progress" | "warning" | "success" | "danger";

/** Visual tone of a shipment/trip status badge. */
export function statusTone(status: string): Tone {
  switch (status) {
    case "draft":
    case "planned":
      return "neutral";
    case "confirmed":
    case "assigned":
      return "info";
    case "dispatched":
    case "in_transit":
    case "in_progress":
      return "progress";
    case "at_border":
    case "paused":
    case "delivery_failed":
      return "warning";
    case "delivered":
    case "completed":
      return "success";
    case "cancelled":
    case "aborted":
      return "danger";
    default:
      return "neutral";
  }
}

export type ShipmentAction =
  | "confirm"
  | "cancel"
  | "border-arrival"
  | "border-clearance"
  | "deliver"
  | "delivery-failed"
  | "reattempt"
  | "delay";

const ACTION_PERMISSION: Record<ShipmentAction, string> = {
  confirm: "shipments.write",
  cancel: "shipments.write",
  "border-arrival": "shipments.write",
  "border-clearance": "shipments.confirm_clearance",
  deliver: "delivery.confirm",
  "delivery-failed": "delivery.confirm",
  reattempt: "shipments.dispatch",
  delay: "shipments.write",
};

const ACTIONS_BY_STATUS: Record<ShipmentStatus, ShipmentAction[]> = {
  draft: ["confirm", "cancel"],
  confirmed: ["cancel", "delay"],
  dispatched: ["delay"],
  in_transit: ["border-arrival", "deliver", "delivery-failed", "delay"],
  at_border: ["border-clearance", "delay"],
  delivery_failed: ["reattempt", "delay"],
  delivered: [],
  cancelled: [],
};

/**
 * Actions to offer for a shipment: allowed from its status (mirrors the API state machine) and
 * permitted for the user. The API remains the authority; this only hides impossible buttons.
 */
export function shipmentActions(status: ShipmentStatus, permissions: readonly string[]): ShipmentAction[] {
  return ACTIONS_BY_STATUS[status].filter((a) => permissions.includes(ACTION_PERMISSION[a]));
}

/** Actions that must carry a reason or extra fields (rendered as a small form). */
export const ACTION_FIELDS: Partial<Record<ShipmentAction, "reason" | "border" | "recipient">> = {
  cancel: "reason",
  "delivery-failed": "reason",
  delay: "reason",
  "border-arrival": "border",
  "border-clearance": "border",
  deliver: "recipient",
};

/** Build the API request body for an action from submitted form fields. */
export function actionBody(action: ShipmentAction, form: { reason?: string; border?: string; recipient?: string }) {
  switch (ACTION_FIELDS[action]) {
    case "reason":
      return { reason: (form.reason ?? "").trim() };
    case "border":
      return { border: (form.border ?? "").trim() };
    case "recipient":
      return { recipient_name: (form.recipient ?? "").trim() };
    default:
      return {};
  }
}
