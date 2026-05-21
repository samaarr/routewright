"use client";

import { useEffect, useRef, useMemo } from "react";
import {
  APIProvider,
  Map,
  AdvancedMarker,
  useMap,
} from "@vis.gl/react-google-maps";
import type { StopItem } from "@/lib/types";

// AdvancedMarker requires a mapId. styles[] and mapId are mutually exclusive
// (Google ignores styles when mapId is set — styles must be configured in
// Cloud Console for the given mapId).
// NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID: set to a Cloud-configured Map ID to enable
// custom styling. Defaults to DEMO_MAP_ID which supports AdvancedMarker with
// Google's standard styling.
const API_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY ?? "";
const MAP_ID  = process.env.NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID ?? "DEMO_MAP_ID";
const ACCENT  = "#4F46C4"; // --color-accent

// --- Polyline drawn via Maps JS API (not a React component) ---------------

interface RouteLayerProps { stops: StopItem[] }

function RouteLayer({ stops }: RouteLayerProps) {
  const map = useMap();
  const polyRef = useRef<google.maps.Polyline | null>(null);

  useEffect(() => {
    if (!map) return;

    polyRef.current?.setMap(null);
    polyRef.current = null;

    if (stops.length < 2) return;

    const path = stops.map((s) => ({ lat: s.lat, lng: s.lng }));

    polyRef.current = new google.maps.Polyline({
      path,
      strokeColor: ACCENT,
      strokeOpacity: 0,
      strokeWeight: 2,
      icons: [
        {
          icon: { path: "M 0,-1 0,1", strokeOpacity: 0.75, scale: 3.5, strokeColor: ACCENT },
          offset: "0",
          repeat: "13px",
        },
      ],
      map,
    });

    const bounds = new google.maps.LatLngBounds();
    path.forEach((p) => bounds.extend(p));
    map.fitBounds(bounds, 72);

    return () => {
      polyRef.current?.setMap(null);
      polyRef.current = null;
    };
  }, [map, stops]);

  return null;
}

// --- Custom numbered pin ---------------------------------------------------

function NumberedPin({ n }: { n: number }) {
  return (
    <div
      style={{
        width: 28,
        height: 28,
        borderRadius: "50%",
        background: ACCENT,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        boxShadow: "0 2px 8px rgba(30,25,60,0.45)",
        border: "2.5px solid rgba(255,255,255,0.95)",
        cursor: "default",
        userSelect: "none",
      }}
      aria-hidden="true"
    >
      <span
        style={{
          color: "#fff",
          fontSize: 11,
          fontWeight: 700,
          lineHeight: 1,
          letterSpacing: "-0.02em",
          fontFeatureSettings: "'tnum'",
        }}
      >
        {n}
      </span>
    </div>
  );
}

// --- Empty state overlay ---------------------------------------------------

function EmptyState({ city }: { city: string }) {
  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
      <div className="rounded-lg border border-border-subtle bg-pane-bg/90 px-6 py-4 shadow-subtle backdrop-blur-sm text-center">
        <p className="text-body text-text-tertiary">
          {city ? `Plan your ${city} day to see the route` : "Enter stops to see your route on the map"}
        </p>
      </div>
    </div>
  );
}

// --- Main component --------------------------------------------------------

interface Props {
  stops: StopItem[];
  city: string;
}

export default function PlanMap({ stops, city }: Props) {
  // Stable default center: Dublin. Overridden by fitBounds when stops exist.
  const defaultCenter = useMemo(() => ({ lat: 53.3498, lng: -6.2603 }), []);

  if (!API_KEY) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-body text-text-tertiary">Map loading…</p>
      </div>
    );
  }

  return (
    <APIProvider apiKey={API_KEY}>
      {/* absolute inset-0 fills whatever the parent pane's dimensions are,
          so this component is layout-agnostic (works in any size container). */}
      <div className="absolute inset-0">
        <Map
          defaultCenter={defaultCenter}
          defaultZoom={12}
          mapId={MAP_ID}
          disableDefaultUI
          zoomControl
          style={{ width: "100%", height: "100%" }}
          gestureHandling="cooperative"
        >
          {stops.map((stop, i) => (
            <AdvancedMarker
              key={`stop-${i}`}
              position={{ lat: stop.lat, lng: stop.lng }}
              title={stop.name}
            >
              <NumberedPin n={i + 1} />
            </AdvancedMarker>
          ))}
          {stops.length >= 2 && <RouteLayer stops={stops} />}
        </Map>
      </div>
      {stops.length === 0 && <EmptyState city={city} />}
    </APIProvider>
  );
}
