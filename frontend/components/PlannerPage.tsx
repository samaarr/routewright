"use client";

import { useState, useMemo } from "react";
import type {
  FormState,
  InfeasibilityFlag,
  Plan,
  PlanRequest,
  StopItem,
} from "@/lib/types";
import { postOptimise, postPlan, postRefreshLeg } from "@/lib/api";
import { fmtDuration } from "@/lib/utils";
import PlanForm from "./PlanForm";
import PlanCanvas from "./PlanCanvas";
import PlanMap, { type OptimiseMapState } from "./PlanMap";

// ---------------------------------------------------------------------------
// Optimise state machine
// ---------------------------------------------------------------------------

type OptimisePhase =
  | { kind: "none" }
  | { kind: "loading" }
  | { kind: "already_optimal" }
  | {
      kind: "suggested";
      optimisedIds: string[];
      savingKm: number;
      flags: InfeasibilityFlag[];
    }
  | {
      kind: "accepted";
      optimisedIds: string[];
      originalIds: string[];
      flags: InfeasibilityFlag[];
      view: "optimised" | "original";
      isFlipping: boolean;
    }
  | { kind: "error" };

// ---------------------------------------------------------------------------
// Misc helpers
// ---------------------------------------------------------------------------

type Refreshing =
  | { kind: "none" }
  | { kind: "reorder" }
  | { kind: "leg"; legTimelineIndex: number };

type MobileTab = "form" | "map" | "timeline";
type TabletRightTab = "map" | "timeline";

function uid(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function makeDefaultForm(): FormState {
  return {
    city: "",
    stops: [
      { id: uid(), query: "" },
      { id: uid(), query: "" },
    ],
    start_time: "",
    mode: "transit",
  };
}

function toPayload(
  form: FormState,
  opts: { fixed_first?: boolean; fixed_last?: boolean } = {}
): PlanRequest {
  return {
    ...form,
    stops: form.stops.map(({ id: _, ...rest }) => rest),
    start_time: new Date(form.start_time).toISOString(),
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    ...opts,
  };
}

function computeTotalDuration(plan: Plan): string {
  const stops = plan.timeline.filter(
    (i): i is StopItem => i.item_type === "stop"
  );
  if (stops.length < 2) return "";
  const first = new Date(stops[0].arrive_at).getTime();
  const last = new Date(stops[stops.length - 1].arrive_at).getTime();
  return fmtDuration(Math.round((last - first) / 1000));
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex-1 rounded-md py-2 text-sm font-medium transition-colors duration-150 ${
        active
          ? "bg-pane-bg text-text-primary shadow-subtle"
          : "text-text-secondary hover:text-text-primary"
      }`}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// State model (invariant)
//
// Pre-plan:   form = user input. map/timeline = empty.
// Planned:    form = user input. map/timeline = user order. Optimise btn visible (bottom-centre).
// Optimised:  form = user input + subtle hint. map/timeline = optimised order. Toggle visible.
// My order:   form = user input. map/timeline = user order. Toggle visible. Hint gone.
// Custom:     form = new manual order. map/timeline = same. Toggle gone, Optimise btn reappears.
//
// THE INVARIANT: form.stops always reflects the user's typed/dragged input — it never mutates
// from toggle interactions. Toggle flips only affect the plan fetch and displayStopIds.
// Only user-initiated actions (text edit, add/remove stop, drag) mutate form.stops.
// ---------------------------------------------------------------------------

// Root component
// ---------------------------------------------------------------------------

export default function PlannerPage() {
  const [form, setForm] = useState<FormState>(makeDefaultForm);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState<Refreshing>({ kind: "none" });
  const [timelineError, setTimelineError] = useState<string | null>(null);
  const [planVersion, setPlanVersion] = useState(0);
  const [mobileTab, setMobileTab] = useState<MobileTab>("form");
  const [tabletRightTab, setTabletRightTab] = useState<TabletRightTab>("timeline");

  // Optimise state
  const [optimisePhase, setOptimisePhase] = useState<OptimisePhase>({ kind: "none" });

  // Current stop ID order used for the plan, timeline, and map.
  // Diverges from form.stops order when "Optimised" view is active.
  // form.stops is always the user's typed/dragged order (the invariant above).
  const [displayStopIds, setDisplayStopIds] = useState<string[]>([]);

  // Pin state — fixed_first / fixed_last for the next optimise call
  const [fixedFirst, setFixedFirst] = useState(false);
  const [fixedLast, setFixedLast] = useState(false);

  const mapStops = useMemo(
    () =>
      plan
        ? (plan.timeline.filter((i): i is StopItem => i.item_type === "stop"))
        : [],
    [plan]
  );

  function focusTimeline() {
    if (typeof window === "undefined") return;
    if (window.innerWidth >= 1024) return;
    if (window.innerWidth >= 768) {
      setTabletRightTab("timeline");
      return;
    }
    setMobileTab("timeline");
  }

  // handleFormChange: user-initiated edit → reset optimise state
  function handleFormChange(newForm: FormState) {
    setForm(newForm);
    setOptimisePhase({ kind: "none" });
    setFixedFirst(false);
    setFixedLast(false);
  }

  async function handleSubmit(formState: FormState) {
    setStatus("loading");
    setErrorMsg(null);
    setTimelineError(null);
    setOptimisePhase({ kind: "none" });
    setFixedFirst(false);
    setFixedLast(false);
    try {
      const result = await postPlan(toPayload(formState));
      setPlan(result);
      setDisplayStopIds(formState.stops.map((s) => s.id));
      setPlanVersion((v) => v + 1);
      setStatus("idle");
      focusTimeline();
    } catch (err) {
      setStatus("error");
      setErrorMsg(err instanceof Error ? err.message : "Something went wrong.");
    }
  }

  async function handleReorder(newIds: string[]) {
    if (!plan) return;
    const prevStops = form.stops;
    const idToStop = new Map(prevStops.map((s) => [s.id, s]));
    const newStops = newIds.map((id) => idToStop.get(id)!);
    const newForm = { ...form, stops: newStops };
    setForm(newForm);
    setDisplayStopIds(newIds);
    // A manual drag always invalidates accepted optimise — the stored orders are stale
    setOptimisePhase({ kind: "none" });
    setRefreshing({ kind: "reorder" });
    setTimelineError(null);
    try {
      const result = await postPlan(toPayload(newForm));
      setPlan(result);
      setRefreshing({ kind: "none" });
    } catch {
      setForm({ ...form, stops: prevStops });
      setDisplayStopIds(prevStops.map((s) => s.id));
      setRefreshing({ kind: "none" });
      setTimelineError("Couldn't update — your previous order is restored. Try again?");
    }
  }

  async function handleStayEdit(stopId: string, minutes: number) {
    if (!plan) return;
    const prevStops = form.stops;
    const newStops = prevStops.map((s) =>
      s.id === stopId ? { ...s, stay_minutes: minutes } : s
    );
    const newForm = { ...form, stops: newStops };
    setForm(newForm);
    setRefreshing({ kind: "reorder" });
    setTimelineError(null);
    try {
      // Preserve current display order (may be optimised) with the updated stay duration
      const idToStop = new Map(newForm.stops.map((s) => [s.id, s]));
      const orderedStops =
        displayStopIds.length > 0
          ? displayStopIds.map((id) => idToStop.get(id)!)
          : newForm.stops;
      const result = await postPlan(toPayload({ ...newForm, stops: orderedStops }));
      setPlan(result);
      setRefreshing({ kind: "none" });
      // displayStopIds unchanged — same order, just updated stay
    } catch {
      setForm({ ...form, stops: prevStops });
      setRefreshing({ kind: "none" });
      setTimelineError("Couldn't update stay duration. Try again?");
    }
  }

  async function handleLegRefresh(legTimelineIndex: number) {
    if (!plan) return;
    const timeline = plan.timeline;
    const legItem = timeline[legTimelineIndex];
    if (!legItem || legItem.item_type !== "leg") return;
    const fromStop = timeline[legTimelineIndex - 1] as StopItem | undefined;
    const toStop = timeline[legTimelineIndex + 1] as StopItem | undefined;
    if (!fromStop || fromStop.item_type !== "stop") return;
    if (!toStop || toStop.item_type !== "stop") return;
    setRefreshing({ kind: "leg", legTimelineIndex });
    setTimelineError(null);
    try {
      const refreshed = await postRefreshLeg({
        from_lat: fromStop.lat,
        from_lng: fromStop.lng,
        from_name: fromStop.name,
        to_lat: toStop.lat,
        to_lng: toStop.lng,
        to_name: toStop.name,
        mode: form.mode,
        city: form.city,
      });
      const newTimeline = [...timeline];
      newTimeline[legTimelineIndex] = refreshed;
      setPlan({ ...plan, timeline: newTimeline });
      setRefreshing({ kind: "none" });
    } catch (err) {
      setRefreshing({ kind: "none" });
      setTimelineError(
        err instanceof Error ? err.message : "Couldn't refresh leg. Try again?"
      );
    }
  }

  // ---------------------------------------------------------------------------
  // Optimise flow
  // ---------------------------------------------------------------------------

  async function handleOptimise() {
    if (!plan || form.stops.length < 3) return;
    setOptimisePhase({ kind: "loading" });
    try {
      const response = await postOptimise(
        toPayload(form, { fixed_first: fixedFirst, fixed_last: fixedLast })
      );

      // Match response stop order back to form stop IDs (handles duplicates)
      const remaining = [...form.stops];
      const optimisedIds = response.stops.map((optStop) => {
        const idx = remaining.findIndex((s) => s.query === optStop.query);
        if (idx === -1) return remaining[0].id;
        const [matched] = remaining.splice(idx, 1);
        return matched.id;
      });

      const originalIds = form.stops.map((s) => s.id);
      const isSameOrder = optimisedIds.every((id, i) => id === originalIds[i]);

      if (isSameOrder) {
        setOptimisePhase({ kind: "already_optimal" });
      } else {
        const savingKm = Math.max(0, response.original_km - response.optimised_km);
        setOptimisePhase({
          kind: "suggested",
          optimisedIds,
          savingKm,
          flags: response.infeasibility_flags,
        });
      }
    } catch {
      setOptimisePhase({ kind: "error" });
    }
  }

  async function handleApplyOptimise() {
    if (optimisePhase.kind !== "suggested") return;
    const { optimisedIds, flags } = optimisePhase;
    const originalIds = form.stops.map((s) => s.id);

    const idToStop = new Map(form.stops.map((s) => [s.id, s]));
    const orderedStops = optimisedIds.map((id) => idToStop.get(id)!);

    // form.stops stays in the user's typed order — only the plan fetch uses the optimised order
    setRefreshing({ kind: "reorder" });
    setTimelineError(null);

    try {
      const result = await postPlan(toPayload({ ...form, stops: orderedStops }));
      setPlan(result);
      setDisplayStopIds(optimisedIds);
      setRefreshing({ kind: "none" });
      setOptimisePhase({
        kind: "accepted",
        optimisedIds,
        originalIds,
        flags,
        view: "optimised",
        isFlipping: false,
      });
    } catch {
      setRefreshing({ kind: "none" });
      setTimelineError("Couldn't apply optimised order — try again?");
    }
  }

  async function handleToggleView(to: "optimised" | "original") {
    if (optimisePhase.kind !== "accepted") return;
    const { optimisedIds, originalIds, flags } = optimisePhase;
    if (optimisePhase.view === to) return;

    const ids = to === "optimised" ? optimisedIds : originalIds;
    setOptimisePhase({ ...optimisePhase, isFlipping: true });

    // form.stops is invariant under toggle flips — only the plan fetch uses the target order
    const idToStop = new Map(form.stops.map((s) => [s.id, s]));
    const orderedStops = ids.map((id) => idToStop.get(id)!);

    setRefreshing({ kind: "reorder" });

    try {
      const result = await postPlan(toPayload({ ...form, stops: orderedStops }));
      setPlan(result);
      setDisplayStopIds(ids);
      setRefreshing({ kind: "none" });
      setOptimisePhase({
        kind: "accepted",
        optimisedIds,
        originalIds,
        flags,
        view: to,
        isFlipping: false,
      });
    } catch {
      setRefreshing({ kind: "none" });
      setOptimisePhase({ ...optimisePhase, isFlipping: false });
      setTimelineError("Couldn't switch order — try again?");
    }
  }

  function handleDismissOptimise() {
    setOptimisePhase({ kind: "none" });
  }

  // ---------------------------------------------------------------------------
  // Derived values for rendering
  // ---------------------------------------------------------------------------

  const isReordering = refreshing.kind === "reorder";
  const refreshingLegIdx =
    refreshing.kind === "leg" ? refreshing.legTimelineIndex : null;
  // When a plan is active, stopIds must match the plan's stop order for correct dnd-kit behaviour.
  // displayStopIds tracks that order; form.stops is the user's input order (may differ in optimised view).
  const stopIds =
    plan !== null && displayStopIds.length > 0
      ? displayStopIds
      : form.stops.map((s) => s.id);
  const stopCount = form.stops.length;
  const totalDuration = plan ? computeTotalDuration(plan) : "";
  const canOptimise = plan !== null && stopCount >= 3;

  // Map view of the optimise state (only the fields PlanMap needs)
  const optimiseMapState: OptimiseMapState = (() => {
    if (optimisePhase.kind === "suggested") {
      return { kind: "suggested", savingKm: optimisePhase.savingKm };
    }
    if (optimisePhase.kind === "accepted") {
      return {
        kind: "accepted",
        view: optimisePhase.view,
        isFlipping: optimisePhase.isFlipping,
      };
    }
    return optimisePhase; // none | loading | already_optimal | error
  })();

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const formPane = (hasPaddingBottom: boolean) => (
    <>
      {status === "error" && errorMsg && (
        <div className="mb-4 rounded-md border border-error-border bg-error-bg px-3 py-2 text-body text-error-text">
          {errorMsg}
        </div>
      )}
      {optimisePhase.kind === "accepted" && optimisePhase.view === "optimised" && (
        <button
          type="button"
          onClick={() => handleToggleView("original")}
          className="mb-4 flex w-full items-center gap-1.5 rounded-md bg-accent-soft px-3 py-2 text-left text-xs text-accent transition-colors hover:bg-accent-soft/70"
        >
          <span aria-hidden="true">↻</span>
          <span>Your typed order — Optimised view active</span>
        </button>
      )}
      <PlanForm
        form={form}
        onChange={handleFormChange}
        onSubmit={handleSubmit}
        isLoading={status === "loading"}
        mobileSubmitHidden={plan === null}
        fixedFirst={fixedFirst}
        fixedLast={fixedLast}
        onToggleFixedFirst={() => setFixedFirst((v) => !v)}
        onToggleFixedLast={() => setFixedLast((v) => !v)}
      />
      {hasPaddingBottom && plan === null && <div className="h-14" />}
    </>
  );

  const timelinePane = (
    <PlanCanvas
      plan={plan}
      planVersion={planVersion}
      stopCount={stopCount}
      stopIds={stopIds}
      timelineError={timelineError}
      onTimelineErrorDismiss={() => setTimelineError(null)}
      onReorder={handleReorder}
      onLegRefresh={handleLegRefresh}
      onStayEdit={handleStayEdit}
      isReordering={isReordering}
      refreshingLegIdx={refreshingLegIdx}
    />
  );

  const mapPane = (
    <>
      <PlanMap
        stops={mapStops}
        optimiseState={optimiseMapState}
        onApply={handleApplyOptimise}
        onDismiss={handleDismissOptimise}
        onToggleView={handleToggleView}
      />

      {/* Optimise button — bottom-centre, same position as the toggle/chip once accepted.
          z-20 keeps it above the Google Maps controls (z-10). */}
      {canOptimise && (optimisePhase.kind === "none" || optimisePhase.kind === "loading") && (
        <div className="absolute bottom-3 left-0 right-0 z-20 flex justify-center">
          {optimisePhase.kind === "none" ? (
            <button
              type="button"
              onClick={handleOptimise}
              className="flex items-center gap-1.5 rounded-full border border-accent bg-pane-bg/95 px-4 py-2 text-sm font-medium text-accent shadow-raised backdrop-blur-sm transition-colors hover:bg-accent-soft"
            >
              Optimise route ↗
            </button>
          ) : (
            <div className="flex items-center gap-1.5 rounded-full border border-border-subtle bg-pane-bg/95 px-4 py-2 text-sm text-text-muted shadow-raised backdrop-blur-sm">
              <span className="inline-block h-3 w-3 animate-spin rounded-full border border-current border-t-transparent" />
              Optimising…
            </div>
          )}
        </div>
      )}
    </>
  );

  return (
    <>
      <main className="mx-auto w-full flex-1 max-w-[1440px] px-4 lg:flex lg:flex-col lg:min-h-0 lg:overflow-hidden lg:px-6">

        {/* Page header */}
        <div className="mb-4 mt-10 text-center md:mb-6 md:mt-12 lg:mb-6 lg:mt-14 lg:flex-shrink-0 lg:text-left">
          <h1 className="text-display text-text-primary">RouteWright</h1>
          <p className="mt-2 text-tagline">
            Multi-stop transit planning that Google Maps doesn&apos;t do.
          </p>
        </div>

        {/* MOBILE layout (<768px) */}
        <div className="md:hidden">
          <div className="mb-3 flex rounded-lg border border-border-subtle bg-bg-base p-0.5">
            <TabButton active={mobileTab === "form"} onClick={() => setMobileTab("form")}>
              Form
            </TabButton>
            <TabButton active={mobileTab === "map"} onClick={() => setMobileTab("map")}>
              Map
            </TabButton>
            <TabButton active={mobileTab === "timeline"} onClick={() => setMobileTab("timeline")}>
              Plan
            </TabButton>
          </div>

          {mobileTab === "form" && (
            <div className={`rounded-lg border border-border-subtle bg-pane-bg p-6 shadow-subtle${plan === null ? " pb-20" : ""}`}>
              {formPane(false)}
            </div>
          )}
          {mobileTab === "map" && (
            <div className="relative h-[65vh] overflow-hidden rounded-lg border border-border-subtle bg-pane-bg shadow-subtle">
              {mapPane}
            </div>
          )}
          {mobileTab === "timeline" && (
            <div className="rounded-lg border border-border-subtle bg-pane-bg p-6 shadow-subtle">
              {timelinePane}
            </div>
          )}
        </div>

        {/* TABLET + DESKTOP layout (>=768px) */}
        <div className="hidden md:flex md:flex-col md:flex-1 md:min-h-0 w-full">

          {/* Tablet-only tab toggle */}
          <div className="mb-4 flex rounded-lg border border-border-subtle bg-bg-base p-0.5 lg:hidden">
            <TabButton
              active={tabletRightTab === "map"}
              onClick={() => setTabletRightTab("map")}
            >
              Map
            </TabButton>
            <TabButton
              active={tabletRightTab === "timeline"}
              onClick={() => setTabletRightTab("timeline")}
            >
              Plan
            </TabButton>
          </div>

          <div className="flex w-full flex-row items-stretch gap-4 md:flex-1 md:min-h-0">

            {/* FORM */}
            <div className="flex flex-shrink-0 flex-col rounded-lg border border-border-subtle bg-pane-bg p-6 shadow-subtle md:w-[300px] md:min-h-0 md:overflow-y-auto md:[scrollbar-gutter:stable] lg:w-[340px] lg:p-8">
              {formPane(true)}
            </div>

            {/* MAP PANE */}
            <div
              className={`relative overflow-hidden rounded-lg border border-border-subtle bg-pane-bg shadow-subtle min-w-0 lg:flex lg:flex-1 lg:min-h-0 lg:min-w-0 ${
                tabletRightTab === "map"
                  ? "flex flex-1 min-h-0"
                  : "hidden lg:flex"
              }`}
            >
              {mapPane}
            </div>

            {/* TIMELINE PANE */}
            <div
              className={`rounded-lg border border-border-subtle bg-pane-bg shadow-subtle lg:flex lg:flex-col lg:w-[360px] lg:flex-shrink-0 lg:min-h-0 lg:overflow-y-auto lg:p-8 lg:[scrollbar-gutter:stable] ${
                tabletRightTab === "timeline"
                  ? "flex flex-col flex-1 min-h-0 overflow-y-auto p-6"
                  : "hidden lg:flex"
              }`}
            >
              {timelinePane}
            </div>
          </div>
        </div>

        {/* Footer */}
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

      {/* Mobile sticky Plan button */}
      {plan === null && mobileTab === "form" && (
        <div className="fixed bottom-0 left-0 right-0 border-t border-border-subtle bg-pane-bg p-3 md:hidden">
          <button
            type="submit"
            form="plan-form"
            disabled={status === "loading"}
            className={`btn-primary${status === "loading" ? " animate-planning" : ""}`}
          >
            {status === "loading" ? "Planning…" : "Plan ↗"}
          </button>
        </div>
      )}

      {/* Mobile summary bar */}
      {plan !== null && (mobileTab === "map" || mobileTab === "timeline") && (
        <div className="fixed left-0 right-0 top-0 z-50 flex h-10 items-center justify-between border-b border-border-subtle bg-pane-bg/95 px-4 backdrop-blur-sm md:hidden">
          <span className="text-sm font-medium text-text-primary">
            {plan.city} · {stopCount} stop{stopCount !== 1 ? "s" : ""}
            {totalDuration ? ` · ${totalDuration}` : ""}
          </span>
          <button
            type="button"
            onClick={() => setMobileTab("form")}
            className="text-xs text-text-secondary hover:text-text-primary"
          >
            Edit ↩
          </button>
        </div>
      )}
    </>
  );
}
