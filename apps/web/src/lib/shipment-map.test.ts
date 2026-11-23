import { describe, expect, it } from "vitest";

import { circlePolygon } from "./shipment-map";

describe("circlePolygon", () => {
  it("is a closed ring about the right size around the point", () => {
    const fc = circlePolygon(11.59, 43.15, 1);
    const ring = fc.features[0].geometry.coordinates[0];
    expect(ring[0]).toEqual(ring[ring.length - 1]);
    const lats = ring.map(([, lat]) => lat);
    const spanKm = (Math.max(...lats) - Math.min(...lats)) * 110.574;
    expect(spanKm).toBeGreaterThan(1.9);
    expect(spanKm).toBeLessThan(2.1);
  });
});
