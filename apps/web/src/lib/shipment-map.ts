// Pure helpers for the customer shipment map (unit-tested in shipment-map.test.ts).

/** Customers refresh every 30 s: positions are approximate, so faster polling adds nothing. */
export const CUSTOMER_POLL_MS = 30_000;

type Polygon = {
  type: "FeatureCollection";
  features: { type: "Feature"; properties: Record<string, never>; geometry: { type: "Polygon"; coordinates: [number, number][][] } }[];
};

/** A circle of `radiusKm` around a point as a GeoJSON polygon (the "about 1 km" area). */
export function circlePolygon(lat: number, lng: number, radiusKm: number, steps = 48): Polygon {
  const ring: [number, number][] = [];
  const dLat = radiusKm / 110.574;
  const dLng = radiusKm / (111.32 * Math.cos((lat * Math.PI) / 180));
  for (let i = 0; i <= steps; i++) {
    const a = (i / steps) * 2 * Math.PI;
    ring.push([Number((lng + dLng * Math.cos(a)).toFixed(6)), Number((lat + dLat * Math.sin(a)).toFixed(6))]);
  }
  return { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [ring] } }] };
}
