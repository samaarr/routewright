"use client";

import { useEffect, useRef, useMemo, useState } from "react";
import {
  APIProvider,
  Map,
  AdvancedMarker,
  useMap,
} from "@vis.gl/react-google-maps";
import type { RouteHint, StopItem } from "@/lib/types";

// AdvancedMarker requires a mapId. styles[] and mapId are mutually exclusive
// (Google ignores styles when mapId is set — styles must be configured in
// Cloud Console for the given mapId).
// NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID: set to a Cloud-configured Map ID to enable
// custom styling. Defaults to DEMO_MAP_ID which supports AdvancedMarker with
// Google's standard styling.
const API_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY ?? "";
const MAP_ID  = process.env.NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID ?? "DEMO_MAP_ID";
const ACCENT  = "#4F46C4"; // --color-accent (indigo)
const SPARK   = "#F5613A"; // --color-spark  (coral)

// Deterministic template picker — stable per plan (no flicker on re-render).
const HINT_TEMPLATES: Array<(flagged: string, before: string) => string> = [
  (flagged, before) =>
    `${flagged} is back the way you came — see the long leg on the map. Visiting it before ${before} may avoid doubling back.`,
  (flagged, before) =>
    `Your route doubles back to reach ${flagged} (the long coral leg). Moving it before ${before} may keep your day in one direction.`,
];

// --- Fit viewport to stops (always mounted inside Map) --------------------

interface MapFitterProps { stops: StopItem[] }

function MapFitter({ stops }: MapFitterProps) {
  const map = useMap();

  useEffect(() => {
    if (!map || stops.length === 0) return;

    if (stops.length === 1) {
      map.setCenter({ lat: stops[0].lat, lng: stops[0].lng });
      map.setZoom(14);
      return;
    }

    const bounds = new google.maps.LatLngBounds();
    stops.forEach((s) => bounds.extend({ lat: s.lat, lng: s.lng }));
    map.fitBounds(bounds, 60);
  }, [map, stops]);

  return null;
}

// --- Polyline with optional highlighted segment ---------------------------

interface RouteLayerProps {
  stops: StopItem[];
  highlightLeg: { from: number; to: number } | null;
}

function RouteLayer({ stops, highlightLeg }: RouteLayerProps) {
  const map = useMap();
  const normalRefs = useRef<google.maps.Polyline[]>([]);
  const coralRef   = useRef<google.maps.Polyline | null>(null);

  useEffect(() => {
    if (!map) return;

    normalRefs.current.forEach((p) => p.setMap(null));
    normalRefs.current = [];
    coralRef.current?.setMap(null);
    coralRef.current = null;

    if (stops.length < 2) return;

    function makeLine(
      path: google.maps.LatLngLiteral[],
      color: string,
    ): google.maps.Polyline {
      return new google.maps.Polyline({
        path,
        strokeColor: color,
        strokeOpacity: 0,
        strokeWeight: 2,
        icons: [
          {
            icon: {
              path: "M 0,-1 0,1",
              strokeOpacity: 0.75,
              scale: 3.5,
              strokeColor: color,
            },
            offset: "0",
            repeat: "13px",
          },
        ],
        map,
      });
    }

    const pts = stops.map((s) => ({ lat: s.lat, lng: s.lng }));

    if (!highlightLeg) {
      normalRefs.current.push(makeLine(pts, ACCENT));
    } else {
      const { from: f, to: t } = highlightLeg;
      if (f > 0)
        normalRefs.current.push(makeLine(pts.slice(0, f + 1), ACCENT));
      coralRef.current = makeLine([pts[f], pts[t]], SPARK);
      if (t < stops.length - 1)
        normalRefs.current.push(makeLine(pts.slice(t), ACCENT));
    }

    return () => {
      normalRefs.current.forEach((p) => p.setMap(null));
      normalRefs.current = [];
      coralRef.current?.setMap(null);
      coralRef.current = null;
    };
  }, [map, stops, highlightLeg]);

  return null;
}

// --- Numbered pin (indigo or coral) ---------------------------------------

function NumberedPin({ n, coral }: { n: number; coral?: boolean }) {
  const bg = coral ? SPARK : ACCENT;
  const glow = coral
    ? "rgba(245,97,58,0.18)"
    : "rgba(79,70,196,0.16)";
  return (
    <div
      style={{
        width: 28,
        height: 28,
        borderRadius: "50%",
        background: bg,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        boxShadow: `0 2px 8px rgba(30,25,60,0.45), 0 0 0 6px ${glow}`,
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
  routeHint: RouteHint | null;
  onMoveHintStop: () => void;
}

export default function PlanMap({ stops, city, routeHint, onMoveHintStop }: Props) {
  const [dismissed, setDismissed] = useState(false);
  const defaultCenter = useMemo(() => ({ lat: 53.3498, lng: -6.2603 }), []);

  // Reset dismissed state when a new hint (or no hint) arrives for a new plan.
  useEffect(() => {
    setDismissed(false);
  }, [routeHint]);

  const showChip = !dismissed && routeHint !== null;
  const highlightLeg = routeHint
    ? { from: routeHint.long_leg_from_index, to: routeHint.long_leg_to_index }
    : null;

  const hintMessage = routeHint
    ? HINT_TEMPLATES[routeHint.flagged_stop_index % HINT_TEMPLATES.length](
        routeHint.flagged_stop_name,
        routeHint.suggested_before_name,
      )
    : "";

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
              <NumberedPin
                n={i + 1}
                coral={routeHint?.flagged_stop_index === i}
              />
            </AdvancedMarker>
          ))}
          {stops.length >= 2 && (
            <RouteLayer stops={stops} highlightLeg={highlightLeg} />
          )}
          <MapFitter stops={stops} />
        </Map>
      </div>

      {/* Hint chip — bottom of map, above the empty state overlay z-order */}
      {showChip && (
        <div className="absolute bottom-3 left-3 right-3 z-10 flex items-start gap-3 rounded-lg border border-border-subtle bg-pane-bg/95 px-4 py-3 shadow-raised backdrop-blur-sm">
          <div className="flex-1">
            <p className="text-sm leading-snug text-text-primary">{hintMessage}</p>
            <button
              type="button"
              onClick={() => {
                onMoveHintStop();
                setDismissed(true);
              }}
              className="mt-2 text-xs font-medium text-accent transition-opacity hover:opacity-75"
            >
              Move it earlier ↑
            </button>
          </div>
          <button
            type="button"
            onClick={() => setDismissed(true)}
            aria-label="Dismiss hint"
            className="flex-shrink-0 text-text-muted transition-opacity hover:opacity-75"
          >
            ✕
          </button>
        </div>
      )}

      {stops.length === 0 && <EmptyState city={city} />}
    </APIProvider>
  );
}
