"use client";

import { useEffect, useRef, useMemo, useState } from "react";
import {
  APIProvider,
  Map,
  AdvancedMarker,
  useMap,
} from "@vis.gl/react-google-maps";
import type { StopItem } from "@/lib/types";

const API_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY ?? "";
const MAP_ID  = process.env.NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID ?? "DEMO_MAP_ID";
const ACCENT  = "#4F46C4"; // --color-accent (indigo)
const SPARK   = "#F5613A"; // --color-spark  (coral)

// ---------------------------------------------------------------------------
// Optimise suggestion state from PlannerPage
// ---------------------------------------------------------------------------

export type OptimiseMapState =
  | { kind: "none" }
  | { kind: "loading" }
  | { kind: "already_optimal" }
  | { kind: "suggested"; savingKm: number }
  | { kind: "accepted"; view: "optimised" | "original"; isFlipping: boolean }
  | { kind: "error" };

// ---------------------------------------------------------------------------
// Map utilities
// ---------------------------------------------------------------------------

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

interface RouteLayerProps { stops: StopItem[] }

function RouteLayer({ stops }: RouteLayerProps) {
  const map = useMap();
  const linesRef = useRef<google.maps.Polyline[]>([]);

  useEffect(() => {
    if (!map) return;
    linesRef.current.forEach((p) => p.setMap(null));
    linesRef.current = [];

    if (stops.length < 2) return;

    const pts = stops.map((s) => ({ lat: s.lat, lng: s.lng }));
    const line = new google.maps.Polyline({
      path: pts,
      strokeColor: ACCENT,
      strokeOpacity: 0,
      strokeWeight: 2,
      icons: [
        {
          icon: {
            path: "M 0,-1 0,1",
            strokeOpacity: 0.75,
            scale: 3.5,
            strokeColor: ACCENT,
          },
          offset: "0",
          repeat: "13px",
        },
      ],
      map,
    });
    linesRef.current.push(line);

    return () => {
      linesRef.current.forEach((p) => p.setMap(null));
      linesRef.current = [];
    };
  }, [map, stops]);

  return null;
}

function NumberedPin({ n, coral }: { n: number; coral?: boolean }) {
  const bg = coral ? SPARK : ACCENT;
  const glow = coral ? "rgba(245,97,58,0.18)" : "rgba(79,70,196,0.16)";
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

function EmptyState() {
  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
      <div className="rounded-lg border border-border-subtle bg-pane-bg/90 px-6 py-4 shadow-subtle backdrop-blur-sm text-center">
        <p className="text-body text-text-tertiary">Enter stops to see your route on the map</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Order toggle (Optimised ⇄ My order)
// ---------------------------------------------------------------------------

function Spinner() {
  return (
    <span
      className="inline-block h-3 w-3 animate-spin rounded-full border border-current border-t-transparent"
      aria-hidden="true"
    />
  );
}

function OrderToggle({
  view,
  isFlipping,
  onToggle,
}: {
  view: "optimised" | "original";
  isFlipping: boolean;
  onToggle: (to: "optimised" | "original") => void;
}) {
  return (
    <div className="relative flex h-8 items-stretch rounded-full border border-border-subtle bg-bg-base p-0.5 text-xs font-medium">
      {/* Sliding pill */}
      <div
        className="pointer-events-none absolute bottom-0.5 left-0.5 top-0.5 w-[calc(50%-2px)] rounded-full bg-accent"
        style={{
          transform: view === "optimised" ? "translateX(0)" : "translateX(100%)",
          transition: "transform 300ms cubic-bezier(.34,1.56,.64,1)",
        }}
      />
      <button
        type="button"
        onClick={() => onToggle("optimised")}
        disabled={isFlipping}
        className={`relative z-10 flex min-w-[4.5rem] items-center justify-center gap-1 rounded-full px-3 transition-colors duration-150 ${
          view === "optimised" ? "text-white" : "text-text-secondary hover:text-text-primary"
        }`}
      >
        {view === "optimised" && isFlipping ? <Spinner /> : "Optimised"}
      </button>
      <button
        type="button"
        onClick={() => onToggle("original")}
        disabled={isFlipping}
        className={`relative z-10 flex min-w-[4.5rem] items-center justify-center gap-1 rounded-full px-3 transition-colors duration-150 ${
          view === "original" ? "text-white" : "text-text-secondary hover:text-text-primary"
        }`}
      >
        {view === "original" && isFlipping ? <Spinner /> : "My order"}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface Props {
  stops: StopItem[];
  optimiseState: OptimiseMapState;
  onApply: () => void;
  onDismiss: () => void;
  onToggleView: (to: "optimised" | "original") => void;
}

export default function PlanMap({
  stops,
  optimiseState,
  onApply,
  onDismiss,
  onToggleView,
}: Props) {
  const defaultCenter = useMemo(() => ({ lat: 53.3498, lng: -6.2603 }), []);

  // Dismiss "already_optimal" message automatically after 4 s.
  const [alreadyOptimalVisible, setAlreadyOptimalVisible] = useState(false);
  useEffect(() => {
    if (optimiseState.kind === "already_optimal") {
      setAlreadyOptimalVisible(true);
      const t = setTimeout(() => {
        setAlreadyOptimalVisible(false);
        onDismiss(); // reset to none so Optimise button reappears
      }, 4000);
      return () => clearTimeout(t);
    } else {
      setAlreadyOptimalVisible(false);
    }
  }, [optimiseState]); // eslint-disable-line react-hooks/exhaustive-deps

  const showChip =
    optimiseState.kind === "suggested" ||
    optimiseState.kind === "error" ||
    (optimiseState.kind === "already_optimal" && alreadyOptimalVisible);

  const chipMessage =
    optimiseState.kind === "suggested"
      ? optimiseState.savingKm >= 2
        ? "A more direct order across the city. Use this instead?"
        : "A slightly tighter route. Use this instead?"
      : optimiseState.kind === "error"
      ? "Can't optimise right now — try again."
      : optimiseState.kind === "already_optimal"
      ? "Your order's already efficient ✓"
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
          <MapFitter stops={stops} />
        </Map>
      </div>

      {/* Bottom overlay — chip (suggestion/error/already-optimal) or toggle */}
      {showChip && (
        <div className="absolute bottom-3 left-3 right-3 z-10 flex items-start gap-3 rounded-lg border border-border-subtle bg-pane-bg/95 px-4 py-3 shadow-raised backdrop-blur-sm">
          <div className="flex-1">
            <p className="text-sm leading-snug text-text-primary">{chipMessage}</p>
            {optimiseState.kind === "suggested" && (
              <button
                type="button"
                onClick={onApply}
                className="mt-2 text-xs font-medium text-accent transition-opacity hover:opacity-75"
              >
                Use this order ↑
              </button>
            )}
          </div>
          <button
            type="button"
            onClick={onDismiss}
            aria-label="Dismiss"
            className="flex-shrink-0 text-text-muted transition-opacity hover:opacity-75"
          >
            ✕
          </button>
        </div>
      )}

      {optimiseState.kind === "accepted" && (
        <div className="absolute bottom-3 left-3 right-3 z-10 flex justify-center">
          <OrderToggle
            view={optimiseState.view}
            isFlipping={optimiseState.isFlipping}
            onToggle={onToggleView}
          />
        </div>
      )}

      {stops.length === 0 && <EmptyState />}
    </APIProvider>
  );
}
