"use client";

// Planner page on the verified, sequential v2 engine.
//
// State lives in one reducer (lib/v2/state.ts). Routing happens only when the
// user presses Plan: that starts exactly one streamed operation with a fresh
// operation ID and the current input revision. Any edit or Cancel moves the
// reducer out of "running"; the effect below then aborts the request, which
// the backend detects as a disconnect and stops further provider calls.
//
// Route optimisation and single-journey refresh are not available yet (later
// stages); the UI says so instead of offering controls that would mix legacy
// v1 results into a v2 plan.

import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { ApiError, messageFor, streamCompare, streamExhaustive, streamPlan, streamRefresh } from "@/lib/v2/client.ts";
import type { StreamEnd } from "@/lib/v2/ndjson.ts";
import {
  compareRequest,
  exhaustiveRequest,
  initialState,
  readiness,
  reducer,
  refreshRequest,
  resultIsStale,
} from "@/lib/v2/state.ts";
import PlanMap, { type MapPin } from "./PlanMap";
import PlanFormV2 from "./v2/PlanFormV2";
import TimelineV2 from "./v2/TimelineV2";

type MobileTab = "form" | "map" | "timeline";
type RightTab = "map" | "timeline";

function uid(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`flex-1 rounded-md py-2 text-sm font-medium transition-colors duration-150 ${
        active ? "bg-pane-bg text-text-primary shadow-subtle" : "text-text-secondary hover:text-text-primary"
      }`}
    >
      {children}
    </button>
  );
}

const NOOP = () => {};

export default function PlannerPage() {
  const [state, dispatch] = useReducer(reducer, undefined, () => initialState([uid(), uid()]));
  const [mobileTab, setMobileTab] = useState<MobileTab>("form");
  // Tablet and desktop share the map-tab / plan-tab layout (D48).
  const [rightTab, setRightTab] = useState<RightTab>("timeline");
  const active = useRef<{ id: string; controller: AbortController } | null>(null);

  // Abort the in-flight request whenever the reducer stops treating it as the
  // running operation (edit, Cancel, completion) — and on unmount.
  useEffect(() => {
    const current = active.current;
    if (!current) return;
    const op = state.operation;
    if (!(op.kind === "running" && op.operationId === current.id)) {
      current.controller.abort();
      active.current = null;
    }
  }, [state.operation]);
  useEffect(() => () => active.current?.controller.abort(), []);

  function focusTimeline() {
    if (typeof window === "undefined") return;
    if (window.innerWidth >= 768) setRightTab("timeline");
    else setMobileTab("timeline");
  }

  // Routes one operation's stream into the reducer. The reducer ignores
  // anything for an operation that is no longer the running one.
  function follow(operationId: string, run: Promise<StreamEnd>) {
    run.then(
      (end) => dispatch({ type: "streamEnded", operationId, end }),
      (err: unknown) => {
        const e = err instanceof ApiError ? err : null;
        const ids = e?.details?.instance_ids;
        dispatch({
          type: "planFailed",
          operationId,
          code: e?.code ?? "unexpected",
          message: e?.message ?? messageFor("unexpected"),
          instanceIds: Array.isArray(ids) ? ids.filter((x): x is string => typeof x === "string") : [],
          role: typeof e?.details?.role === "string" ? e.details.role : null,
        });
      },
    );
  }

  // One operation at a time: starting a new one aborts the previous request
  // (the server treats it as a disconnect and stops further provider calls).
  function begin(): { operationId: string; signal: AbortSignal } {
    active.current?.controller.abort();
    const operationId = uid();
    const controller = new AbortController();
    active.current = { id: operationId, controller };
    return { operationId, signal: controller.signal };
  }

  function startPlan() {
    const r = readiness(state);
    if (!r.ready) return;
    const { operationId, signal } = begin();
    dispatch({ type: "planStarted", operationId });
    focusTimeline();
    follow(
      operationId,
      streamPlan(
        { ...r.request, operation_id: operationId, input_revision: state.revision },
        (event) => dispatch({ type: "streamEvent", operationId, event }),
        signal,
      ),
    );
  }

  // "Refresh from here" / "Try again": recompute from leg k at its planned
  // departure in the current plan (the same instant on every retry).
  function startRefresh(legIndex: number) {
    const r = refreshRequest(state, legIndex);
    if (!r) return;
    const { target: _target, ...request } = r;
    const { operationId, signal } = begin();
    dispatch({ type: "refreshStarted", operationId, legIndex });
    follow(
      operationId,
      streamRefresh(
        { ...request, operation_id: operationId, input_revision: state.revision },
        (event) => dispatch({ type: "streamEvent", operationId, event }),
        signal,
      ),
    );
  }

  // Compare: one alternative order vs a fresh original (Step 8).
  function startCompare() {
    const r = compareRequest(state);
    if (!r) return;
    const { operationId, signal } = begin();
    dispatch({ type: "compareStarted", operationId });
    focusTimeline();
    follow(
      operationId,
      streamCompare(
        { ...r, operation_id: operationId, input_revision: state.revision },
        (event) => dispatch({ type: "streamEvent", operationId, event }),
        signal,
      ),
    );
  }

  // Experimental: evaluate all 24 orders of four stops (2026-10-08).
  function startExhaustive() {
    const r = exhaustiveRequest(state);
    if (!r) return;
    const { operationId, signal } = begin();
    dispatch({ type: "exhaustiveStarted", operationId });
    focusTimeline();
    follow(
      operationId,
      streamExhaustive(
        { ...r, operation_id: operationId, input_revision: state.revision },
        (event) => dispatch({ type: "streamEvent", operationId, event }),
        signal,
      ),
    );
  }

  const pins: MapPin[] = useMemo(() => {
    const current = state.result && !resultIsStale(state) ? state.result.plan : null;
    if (current) {
      return current.timeline.flatMap((i) => (i.item_type === "stop" ? [{ lat: i.lat, lng: i.lng, name: i.name }] : []));
    }
    return state.draft.stops.flatMap((s) => (s.selected ? [{ lat: s.selected.lat, lng: s.selected.lng, name: s.selected.label }] : []));
  }, [state]);

  const formPane = (
    <PlanFormV2
      state={state}
      dispatch={dispatch}
      onPlan={startPlan}
      onCancel={() => dispatch({ type: "cancelRequested" })}
    />
  );
  const timelinePane = (
    <TimelineV2
      state={state}
      onRefresh={startRefresh}
      onCancel={() => dispatch({ type: "cancelRequested" })}
      onCompare={startCompare}
      onAccept={() => dispatch({ type: "comparisonAccepted" })}
      onDismiss={() => dispatch({ type: "comparisonDismissed" })}
      onExhaustive={startExhaustive}
      onExhaustiveAccept={() => dispatch({ type: "exhaustiveAccepted" })}
      onExhaustiveDismiss={() => dispatch({ type: "exhaustiveDismissed" })}
    />
  );
  const mapPane = (
    <>
      <PlanMap stops={pins} optimiseState={{ kind: "none" }} onApply={NOOP} onDismiss={NOOP} onToggleView={NOOP} />
    </>
  );

  return (
    <>
      <main className="mx-auto w-full max-w-[1440px] flex-1 px-4 lg:flex lg:min-h-0 lg:flex-col lg:overflow-hidden lg:px-6">
        <div className="mb-4 mt-10 text-center md:mb-6 md:mt-12 lg:mb-6 lg:mt-14 lg:flex-shrink-0 lg:text-left">
          <h1 className="text-display text-text-primary">RouteWright</h1>
          <p className="mt-2 text-tagline">Multi-stop transit planning that Google Maps doesn&apos;t do.</p>
        </div>

        {/* MOBILE layout (<768px) */}
        <div className="md:hidden">
          <div className="mb-3 flex rounded-lg border border-border-subtle bg-bg-base p-0.5">
            <TabButton active={mobileTab === "form"} onClick={() => setMobileTab("form")}>Form</TabButton>
            <TabButton active={mobileTab === "map"} onClick={() => setMobileTab("map")}>Map</TabButton>
            <TabButton active={mobileTab === "timeline"} onClick={() => setMobileTab("timeline")}>Plan</TabButton>
          </div>
          {mobileTab === "form" && (
            <div className="rounded-lg border border-border-subtle bg-pane-bg p-6 shadow-subtle">{formPane}</div>
          )}
          {mobileTab === "map" && (
            <div className="relative h-[65vh] overflow-hidden rounded-lg border border-border-subtle bg-pane-bg shadow-subtle">
              {mapPane}
            </div>
          )}
          {mobileTab === "timeline" && (
            <div className="rounded-lg border border-border-subtle bg-pane-bg p-6 shadow-subtle">{timelinePane}</div>
          )}
        </div>

        {/* TABLET + DESKTOP layout (>=768px): form + Map/Plan tabs (D48) */}
        <div className="hidden w-full md:flex md:min-h-0 md:flex-1 md:flex-col">
          <div className="mb-4 flex rounded-lg border border-border-subtle bg-bg-base p-0.5">
            <TabButton active={rightTab === "map"} onClick={() => setRightTab("map")}>Map</TabButton>
            <TabButton active={rightTab === "timeline"} onClick={() => setRightTab("timeline")}>Plan</TabButton>
          </div>
          <div className="flex w-full flex-row items-stretch gap-4 md:min-h-0 md:flex-1">
            <div className="flex flex-shrink-0 flex-col rounded-lg border border-border-subtle bg-pane-bg p-6 shadow-subtle md:min-h-0 md:w-[340px] md:overflow-y-auto md:[scrollbar-gutter:stable] lg:w-[400px] lg:p-8">
              {formPane}
            </div>
            <div
              className={`relative min-w-0 overflow-hidden rounded-lg border border-border-subtle bg-pane-bg shadow-subtle ${
                rightTab === "map" ? "flex min-h-[60vh] flex-1 md:min-h-0" : "hidden"
              }`}
            >
              {mapPane}
            </div>
            <div
              className={`rounded-lg border border-border-subtle bg-pane-bg shadow-subtle ${
                rightTab === "timeline" ? "flex min-h-0 flex-1 flex-col overflow-y-auto p-6 [scrollbar-gutter:stable] lg:p-8" : "hidden"
              }`}
            >
              {timelinePane}
            </div>
          </div>
        </div>

        <p className="mb-10 mt-6 text-center text-body text-text-muted lg:flex-shrink-0">
          Made in Dublin &middot;{" "}
          <a
            href="https://github.com/samaarr/routewright"
            target="_blank"
            rel="noopener noreferrer"
            className="underline underline-offset-2 hover:text-text-secondary"
          >
            github.com/samaarr/routewright
          </a>
        </p>
      </main>

    </>
  );
}
