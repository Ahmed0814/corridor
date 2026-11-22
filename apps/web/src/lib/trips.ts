// Trip actions offered in the office web app (pure logic, unit-tested in trips.test.ts).
// Mirrors the API state machine; the API remains the authority.

export type TripAction = "start" | "pause" | "resume" | "complete" | "cancel" | "abort" | "unassign";

const BY_STATUS: Record<string, TripAction[]> = {
  planned: ["cancel"],
  assigned: ["start", "unassign", "cancel"],
  in_progress: ["pause", "complete", "abort"],
  paused: ["resume", "complete", "abort"],
};

/** Driver actions done from the office are "on behalf of the driver": permission + reason. */
const PERMISSION: Record<TripAction, string> = {
  start: "trips.act_on_behalf",
  pause: "trips.act_on_behalf",
  resume: "trips.act_on_behalf",
  complete: "trips.act_on_behalf",
  abort: "trips.act_on_behalf",
  cancel: "trips.assign",
  unassign: "trips.assign",
};

export function officeTripActions(status: string, permissions: readonly string[]): TripAction[] {
  return (BY_STATUS[status] ?? []).filter((a) => permissions.includes(PERMISSION[a]));
}

export const TRIP_ACTIONS: readonly TripAction[] = ["start", "pause", "resume", "complete", "cancel", "abort", "unassign"];

export type TripEvent = {
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
