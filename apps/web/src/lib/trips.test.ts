import { describe, expect, it } from "vitest";

import { officeTripActions } from "./trips";

const OPS = ["trips.act_on_behalf", "trips.assign"];

describe("officeTripActions", () => {
  it("follows the trip state machine", () => {
    expect(officeTripActions("assigned", OPS)).toEqual(["start", "unassign", "cancel"]);
    expect(officeTripActions("in_progress", OPS)).toEqual(["pause", "complete", "abort"]);
    expect(officeTripActions("paused", OPS)).toEqual(["resume", "complete", "abort"]);
    expect(officeTripActions("completed", OPS)).toEqual([]);
  });

  it("needs act-on-behalf for driver actions", () => {
    expect(officeTripActions("assigned", ["trips.assign"])).toEqual(["unassign", "cancel"]);
    expect(officeTripActions("in_progress", ["trips.assign"])).toEqual([]);
  });
});
