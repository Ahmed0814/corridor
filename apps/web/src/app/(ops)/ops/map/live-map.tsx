"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import * as maplibregl from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  boundsAround,
  CORRIDOR_BOUNDS,
  displayedFreshness,
  type FleetSnapshot,
  formatAge,
  FRESHNESS_COLOR,
  isFeedStale,
  POLL_INTERVAL_MS,
  snapshotAge,
} from "@/lib/tracking";

export type LiveMapLabels = Record<
  | "live"
  | "delayed"
  | "stale"
  | "offline"
  | "vehicle"
  | "freshness"
  | "recorded"
  | "received"
  | "accuracy"
  | "age"
  | "none"
  | "feedStale"
  | "updated"
  | "basemap",
  string
>;

function fmt(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: "short", timeStyle: "medium", timeZone: "Africa/Djibouti" }).format(
    new Date(iso),
  );
}

export function LiveMap({
  initial,
  styleUrl,
  locale,
  labels,
}: {
  initial: FleetSnapshot | null;
  styleUrl: string;
  locale: string;
  labels: LiveMapLabels;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const markers = useRef(new Map<string, maplibregl.Marker>());
  const fitted = useRef(false);
  const [snapshot, setSnapshot] = useState<FleetSnapshot | null>(initial);
  const [lastSuccess, setLastSuccess] = useState<Date | null>(initial ? new Date() : null);
  const [now, setNow] = useState(() => new Date());

  // Map instance (client only).
  useEffect(() => {
    if (!container.current || map.current) return;
    map.current = new maplibregl.Map({ container: container.current, style: styleUrl, bounds: CORRIDOR_BOUNDS });
    map.current.addControl(new maplibregl.NavigationControl(), "top-right");
    return () => {
      map.current?.remove();
      map.current = null;
    };
  }, [styleUrl]);

  // Poll the same-origin fleet endpoint; never pretend to be live when polls fail.
  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const response = await fetch("/ops/map/fleet", { cache: "no-store" });
        if (!response.ok) return;
        const data = (await response.json()) as FleetSnapshot;
        if (!cancelled && Array.isArray(data.vehicles)) {
          setSnapshot(data);
          setLastSuccess(new Date());
        }
      } catch {
        /* keep the last snapshot; the banner shows that it is ageing */
      }
    }
    const pollTimer = setInterval(poll, POLL_INTERVAL_MS);
    const clockTimer = setInterval(() => setNow(new Date()), 1_000);
    return () => {
      cancelled = true;
      clearInterval(pollTimer);
      clearInterval(clockTimer);
    };
  }, []);

  const rows = useMemo(() => {
    if (!snapshot) return [];
    const age = snapshotAge(snapshot.generated_at, now);
    return snapshot.vehicles.map((v) => ({ ...v, shown: displayedFreshness(v, age, snapshot.thresholds), shownAge: v.age_seconds + age }));
  }, [snapshot, now]);

  // Markers: one per vehicle, coloured by displayed freshness, popup with both timestamps.
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    // First time vehicles are known: show where they actually are (not only the corridor view).
    if (!fitted.current && rows.length > 0) {
      const b = boundsAround(rows);
      if (b) m.fitBounds(b, { padding: 60, maxZoom: 14, duration: 0 });
      fitted.current = true;
    }
    const seen = new Set<string>();
    for (const v of rows) {
      seen.add(v.vehicle_id);
      let marker = markers.current.get(v.vehicle_id);
      if (!marker) {
        const el = document.createElement("div");
        el.style.cssText = "width:16px;height:16px;border-radius:9999px;border:2px solid white;box-shadow:0 0 0 1px #0003";
        el.setAttribute("role", "img");
        marker = new maplibregl.Marker({ element: el }).setLngLat([v.longitude, v.latitude]).addTo(m);
        marker.setPopup(new maplibregl.Popup({ offset: 12 }));
        markers.current.set(v.vehicle_id, marker);
      }
      marker.setLngLat([v.longitude, v.latitude]);
      const el = marker.getElement();
      el.style.background = FRESHNESS_COLOR[v.shown];
      el.setAttribute("aria-label", `${v.vehicle_plate ?? v.vehicle_id}: ${labels[v.shown]}`);
      el.dataset.freshness = v.shown;
      marker.getPopup()?.setHTML(
        `<strong>${(v.vehicle_plate ?? "").replace(/[<>&]/g, "")}</strong><br/>` +
          `${labels.freshness}: ${labels[v.shown]} (${formatAge(v.shownAge)})<br/>` +
          `${labels.recorded}: ${fmt(v.recorded_at, locale)}<br/>` +
          `${labels.received}: ${fmt(v.received_at, locale)}<br/>` +
          `${labels.accuracy}: ${v.accuracy_meters !== null ? `±${Math.round(v.accuracy_meters)} m` : "—"}`,
      );
    }
    for (const [id, marker] of markers.current) {
      if (!seen.has(id)) {
        marker.remove();
        markers.current.delete(id);
      }
    }
  }, [rows, labels, locale]);

  const feedStale = isFeedStale(lastSuccess, now);

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
      <div>
        {feedStale ? (
          <div role="alert" className="mb-2 rounded-md border border-amber-400 bg-amber-50 p-2 text-sm text-amber-900">
            {labels.feedStale.replace("{time}", lastSuccess ? fmt(lastSuccess.toISOString(), locale) : "—")}
          </div>
        ) : null}
        <div ref={container} className="h-[32rem] w-full rounded-lg border" data-testid="live-map" />
        <p className="mt-1 text-xs text-muted-foreground">
          {snapshot ? labels.updated.replace("{time}", fmt(snapshot.generated_at, locale)) : null} · {labels.basemap}
        </p>
      </div>
      <div className="max-h-[34rem] overflow-y-auto rounded-lg border">
        {rows.length === 0 ? (
          <p className="p-4 text-sm text-muted-foreground">{labels.none}</p>
        ) : (
          <ul className="divide-y text-sm">
            {rows.map((v) => (
              <li key={v.vehicle_id} className="p-3" data-freshness={v.shown}>
                <div className="flex items-center gap-2">
                  <span className="inline-block size-3 rounded-full" style={{ background: FRESHNESS_COLOR[v.shown] }} />
                  <span className="font-medium">{v.vehicle_plate ?? v.vehicle_id}</span>
                  <span className="ms-auto text-xs">
                    {labels[v.shown]} · {formatAge(v.shownAge)}
                  </span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {labels.recorded}: {fmt(v.recorded_at, locale)} · {labels.received}: {fmt(v.received_at, locale)}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
