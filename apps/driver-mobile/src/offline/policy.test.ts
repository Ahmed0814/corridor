/// <reference types="node" />
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { batteryAdvice, type Fix, shouldKeep, toEvent, TRACKING } from "./policy.ts";

const base: Fix = { latitude: 11.59, longitude: 43.14, accuracy: 5, speed: 0, heading: null, timestamp: 1_000_000 };

describe("shouldKeep", () => {
  it("keeps the first fix and every fix while moving", () => {
    assert.equal(shouldKeep(null, base).keep, true);
    assert.deepEqual(shouldKeep(base, { ...base, speed: 12, timestamp: base.timestamp + 20_000 }), { keep: true, reason: "moving" });
  });

  it("keeps one fix per heartbeat interval while stationary", () => {
    assert.deepEqual(shouldKeep(base, { ...base, timestamp: base.timestamp + 60_000 }), { keep: false, reason: "too_soon" });
    assert.deepEqual(shouldKeep(base, { ...base, timestamp: base.timestamp + TRACKING.stationaryIntervalMs }), {
      keep: true,
      reason: "heartbeat",
    });
  });

  it("keeps a fix after real movement even at low reported speed", () => {
    const moved = { ...base, latitude: base.latitude + 0.0005, timestamp: base.timestamp + 20_000 }; // ~55 m
    assert.deepEqual(shouldKeep(base, moved), { keep: true, reason: "moved" });
  });

  it("never records mock-location fixes or fixes older than the last one", () => {
    assert.deepEqual(shouldKeep(null, { ...base, mocked: true }), { keep: false, reason: "mocked" });
    assert.deepEqual(shouldKeep(base, { ...base, timestamp: base.timestamp - 1 }), { keep: false, reason: "older" });
  });
});

describe("toEvent", () => {
  it("uses the GPS fix time and drops invalid speed/heading", () => {
    const e = toEvent({ ...base, speed: -1, heading: -1 }, { tripId: "t", vehicleId: "v", deviceId: "d" }, 7, "id-1");
    assert.equal(e.recorded_at, new Date(base.timestamp).toISOString());
    assert.equal(e.speed, null);
    assert.equal(e.heading, null);
    assert.equal(e.sequence_number, 7);
    assert.deepEqual([e.trip_id, e.vehicle_id, e.device_id, e.event_id], ["t", "v", "d", "id-1"]);
  });
});

describe("batteryAdvice", () => {
  it("adds maker-specific steps for aggressive OEMs common in the region", () => {
    assert.equal(batteryAdvice("TECNO MOBILE LIMITED").maker, "Tecno/Infinix/itel");
    assert.ok(batteryAdvice("samsung").steps.some((s) => s.includes("Sleeping apps")));
    assert.equal(batteryAdvice(null).steps.length, 2);
  });
});
