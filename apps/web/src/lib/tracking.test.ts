import { describe, expect, it } from "vitest";

import { displayedFreshness, formatAge, isFeedStale, snapshotAge } from "./tracking";

const T = { freshness_live_seconds: 120, freshness_delayed_seconds: 600, freshness_stale_seconds: 3600 };

describe("displayedFreshness", () => {
  it("keeps the API state for a fresh snapshot", () => {
    expect(displayedFreshness({ freshness: "live", age_seconds: 30, session_active: true }, 0, T)).toBe("live");
  });

  it("downgrades as the snapshot ages but never upgrades", () => {
    expect(displayedFreshness({ freshness: "live", age_seconds: 100, session_active: true }, 60, T)).toBe("delayed");
    expect(displayedFreshness({ freshness: "stale", age_seconds: 700, session_active: true }, 0, T)).toBe("stale");
    expect(displayedFreshness({ freshness: "delayed", age_seconds: 5, session_active: true }, 0, T)).toBe("delayed");
  });

  it("is offline whenever the tracking session is not active (hard rule 3)", () => {
    expect(displayedFreshness({ freshness: "live", age_seconds: 1, session_active: false }, 0, T)).toBe("offline");
  });
});

describe("feed staleness", () => {
  it("flags the feed when polls have stopped succeeding", () => {
    const now = new Date("2026-11-21T10:00:20Z");
    expect(isFeedStale(null, now)).toBe(true);
    expect(isFeedStale(new Date("2026-11-21T10:00:15Z"), now)).toBe(false);
    expect(isFeedStale(new Date("2026-11-21T10:00:05Z"), now)).toBe(true);
  });

  it("computes snapshot age and never goes negative", () => {
    expect(snapshotAge("2026-11-21T10:00:00Z", new Date("2026-11-21T10:00:30Z"))).toBe(30);
    expect(snapshotAge("2026-11-21T10:00:30Z", new Date("2026-11-21T10:00:00Z"))).toBe(0);
  });
});

describe("formatAge", () => {
  it("formats seconds, minutes and hours", () => {
    expect(formatAge(42)).toBe("42s");
    expect(formatAge(600)).toBe("10 min");
    expect(formatAge(3600)).toBe("1 h");
    expect(formatAge(5400)).toBe("1 h 30 min");
  });
});
