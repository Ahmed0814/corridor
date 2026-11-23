"use client";

// Customer-facing map of ONE shipment: an approximate (~1 km) area, the time the position was
// recorded and received, and a freshness label. Refreshes itself. Never shows driver or vehicle.

import "maplibre-gl/dist/maplibre-gl.css";

import * as maplibregl from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import type { PublicPosition } from "@/lib/phase6";
import { circlePolygon, CUSTOMER_POLL_MS } from "@/lib/shipment-map";
import { CORRIDOR_BOUNDS, FRESHNESS_COLOR } from "@/lib/tracking";

export type ShipmentMapLabels = {
  title: string;
  noPosition: string;
  recorded: string;
  received: string;
  precision: string;
  freshness: Record<"live" | "delayed" | "stale" | "offline", string>;
  basemap: string;
};

function when(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short", timeZone: "Africa/Djibouti" }).format(
    new Date(iso),
  );
}

export function ShipmentMap({
  initial,
  pollUrl,
  pollBody,
  styleUrl,
  locale,
  labels,
}: {
  initial: PublicPosition | null;
  pollUrl: string;
  /** When set, the position is fetched with a JSON POST of this body (no secrets in URLs). */
  pollBody?: Record<string, string>;
  styleUrl: string;
  locale: string;
  labels: ShipmentMapLabels;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const marker = useRef<maplibregl.Marker | null>(null);
  const [position, setPosition] = useState<PublicPosition | null>(initial);

  // Poll the same-origin position endpoint (no tokens in the browser).
  useEffect(() => {
    const id = setInterval(async () => {
      try {
        const r = await fetch(
          pollUrl,
          pollBody
            ? { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify(pollBody) }
            : { cache: "no-store" },
        );
        if (r.ok) setPosition(((await r.json()) as { position: PublicPosition | null }).position);
      } catch {
        // keep the last known position; its recorded time tells the customer how old it is
      }
    }, CUSTOMER_POLL_MS);
    return () => clearInterval(id);
  }, [pollUrl, pollBody]);

  useEffect(() => {
    if (!container.current || map.current) return;
    const m = new maplibregl.Map({ container: container.current, style: styleUrl, bounds: CORRIDOR_BOUNDS });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.on("load", () => {
      m.addSource("area", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({ id: "area-fill", type: "fill", source: "area", paint: { "fill-color": "#2563eb", "fill-opacity": 0.15 } });
      m.addLayer({ id: "area-line", type: "line", source: "area", paint: { "line-color": "#2563eb", "line-width": 1.5 } });
      setPosition((p) => (p ? { ...p } : p)); // draw the initial position once the style is ready
    });
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
    };
  }, [styleUrl]);

  useEffect(() => {
    const m = map.current;
    if (!m || !m.isStyleLoaded()) return;
    const source = m.getSource("area") as maplibregl.GeoJSONSource | undefined;
    if (!position) {
      marker.current?.remove();
      marker.current = null;
      source?.setData({ type: "FeatureCollection", features: [] });
      return;
    }
    const lngLat: [number, number] = [position.longitude, position.latitude];
    const color = FRESHNESS_COLOR[position.freshness] ?? "#6b7280";
    if (!marker.current) {
      marker.current = new maplibregl.Marker({ color }).setLngLat(lngLat).addTo(m);
      m.easeTo({ center: lngLat, zoom: 13 }); // street level: the ~1 km circle fills the view
    } else {
      marker.current.setLngLat(lngLat);
    }
    source?.setData(circlePolygon(position.latitude, position.longitude, position.precision_km));
  }, [position]);

  return (
    <section aria-label={labels.title} className="space-y-2">
      <div ref={container} className="h-72 w-full overflow-hidden rounded-lg border sm:h-96" />
      {position ? (
        <p className="text-sm">
          <span
            className="me-2 inline-block h-2.5 w-2.5 rounded-full align-middle"
            style={{ backgroundColor: FRESHNESS_COLOR[position.freshness] }}
            aria-hidden
          />
          <strong>{labels.freshness[position.freshness]}</strong> · {labels.precision} ·{" "}
          {labels.recorded.replace("{at}", when(position.recorded_at, locale))} ·{" "}
          {labels.received.replace("{at}", when(position.received_at, locale))}
        </p>
      ) : (
        <p className="text-sm text-muted-foreground">{labels.noPosition}</p>
      )}
      <p className="text-xs text-muted-foreground">{labels.basemap}</p>
    </section>
  );
}
