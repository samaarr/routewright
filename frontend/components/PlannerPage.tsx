"use client";

import { useState, useMemo } from "react";
import type { FormState, Plan, PlanRequest, StopItem } from "@/lib/types";
import { postPlan, postRefreshLeg } from "@/lib/api";
import { fmtDuration } from "@/lib/utils";
import PlanForm from "./PlanForm";
import PlanCanvas from "./PlanCanvas";
import PlanMap from "./PlanMap";

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

function toPayload(form: FormState): PlanRequest {
  return {
    ...form,
    stops: form.stops.map(({ id: _, ...rest }) => rest),
    start_time: new Date(form.start_time).toISOString(),
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

// Pill toggle button used in both the mobile segmented control and the
// tablet map/timeline tab toggle.
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

export default function PlannerPage() {
  const [form, setForm] = useState<FormState>(makeDefaultForm);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState<Refreshing>({ kind: "none" });
  const [timelineError, setTimelineError] = useState<string | null>(null);
  const [planVersion, setPlanVersion] = useState(0);
  const [mobileTab, setMobileTab] = useState<MobileTab>("form");
  // Tablet right panel defaults to "timeline" (users land on the plan after submit).
  const [tabletRightTab, setTabletRightTab] = useState<TabletRightTab>("timeline");

  const mapStops = useMemo(
    () =>
      plan
        ? (plan.timeline.filter(
            (i): i is StopItem => i.item_type === "stop"
          ))
        : [],
    [plan]
  );

  // On mobile: switch to timeline tab. On tablet: switch right panel to timeline.
  // On desktop: no-op (all three columns always visible).
  function focusTimeline() {
    if (typeof window === "undefined") return;
    if (window.innerWidth >= 1024) return;
    if (window.innerWidth >= 768) {
      setTabletRightTab("timeline");
      return;
    }
    setMobileTab("timeline");
  }

  async function handleSubmit(formState: FormState) {
    setStatus("loading");
    setErrorMsg(null);
    setTimelineError(null);
    try {
      const result = await postPlan(toPayload(formState));
      setPlan(result);
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
    setRefreshing({ kind: "reorder" });
    setTimelineError(null);
    try {
      const result = await postPlan(toPayload(newForm));
      setPlan(result);
      setRefreshing({ kind: "none" });
    } catch {
      setForm({ ...form, stops: prevStops });
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
      const result = await postPlan(toPayload(newForm));
      setPlan(result);
      setRefreshing({ kind: "none" });
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

  const isReordering = refreshing.kind === "reorder";
  const refreshingLegIdx =
    refreshing.kind === "leg" ? refreshing.legTimelineIndex : null;
  const stopIds = form.stops.map((s) => s.id);
  const stopCount = form.stops.length;
  const totalDuration = plan ? computeTotalDuration(plan) : "";

  // Shared pane contents — built once, placed in both layout sections.
  // State lives in PlannerPage so both sections stay in sync when both are
  // mounted (tablet+desktop section is always in DOM via CSS).
  const formPane = (hasPaddingBottom: boolean) => (
    <>
      {status === "error" && errorMsg && (
        <div className="mb-4 rounded-md border border-error-border bg-error-bg px-3 py-2 text-body text-error-text">
          {errorMsg}
        </div>
      )}
      <PlanForm
        form={form}
        onChange={setForm}
        onSubmit={handleSubmit}
        isLoading={status === "loading"}
        mobileSubmitHidden={plan === null}
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

  function handleMoveHintStop() {
    if (!plan?.route_hint) return;
    const { flagged_stop_index, suggested_before_index } = plan.route_hint;
    const currentIds = form.stops.map((s) => s.id);
    const flaggedId = currentIds[flagged_stop_index];
    const withoutFlagged = currentIds.filter((_, i) => i !== flagged_stop_index);
    const insertIdx = withoutFlagged.indexOf(currentIds[suggested_before_index]);
    const newIds = [
      ...withoutFlagged.slice(0, insertIdx),
      flaggedId,
      ...withoutFlagged.slice(insertIdx),
    ];
    handleReorder(newIds);
  }

  const mapPane = (
    <PlanMap
      stops={mapStops}
      city={form.city}
      routeHint={plan?.route_hint ?? null}
      onMoveHintStop={handleMoveHintStop}
    />
  );

  return (
    <>
      <main className="mx-auto w-full flex-1 max-w-[1440px] px-4 lg:flex lg:flex-col lg:min-h-0 lg:overflow-hidden lg:px-6">

        {/* ── Page header — always visible ─────────────────────────────── */}
        <div className="mb-4 mt-10 text-center md:mb-6 md:mt-12 lg:mb-6 lg:mt-14 lg:flex-shrink-0 lg:text-left">
          <h1 className="text-display text-text-primary">RouteWright</h1>
          <p className="mt-2 text-tagline">
            Multi-stop transit planning that Google Maps doesn&apos;t do.
          </p>
        </div>

        {/* ── MOBILE layout (<768px) ────────────────────────────────────── */}
        {/* Hidden on md+. Segmented control switches between form/map/plan. */}
        <div className="md:hidden">
          {/* Segmented control */}
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
            /* relative so PlanMap's absolute inset-0 positions correctly */
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

        {/* ── TABLET + DESKTOP layout (>=768px) ─────────────────────────── */}
        {/* Hidden on mobile. On tablet: form (left) + tabbed right panel.   */}
        {/* On desktop: three independent columns.                           */}
        <div className="hidden md:flex md:flex-col md:flex-1 md:min-h-0 w-full">

          {/* Tablet-only tab toggle — sits above the column row, hidden on desktop */}
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

          {/* Column row — three direct flex siblings at all breakpoints.
              w-full ensures it fills the parent rather than sizing to content.
              No lg:contents trick — map and timeline are always direct children. */}
          <div className="flex w-full flex-row items-stretch gap-4 md:flex-1 md:min-h-0">

            {/* FORM — left column, always visible */}
            <div className="flex flex-shrink-0 flex-col rounded-lg border border-border-subtle bg-pane-bg p-6 shadow-subtle md:w-[300px] md:min-h-0 md:overflow-y-auto md:[scrollbar-gutter:stable] lg:w-[340px] lg:p-8">
              {formPane(true)}
            </div>

            {/* MAP PANE
                Tablet: visible only when tabletRightTab="map".
                Desktop: always visible — lg:flex overrides the tablet hidden. */}
            <div
              className={`relative overflow-hidden rounded-lg border border-border-subtle bg-pane-bg shadow-subtle min-w-0 lg:flex lg:flex-1 lg:min-h-0 lg:min-w-0 ${
                tabletRightTab === "map"
                  ? "flex flex-1 min-h-0"
                  : "hidden lg:flex"
              }`}
            >
              {mapPane}
            </div>

            {/* TIMELINE PANE
                Tablet: visible only when tabletRightTab="timeline".
                Desktop: always visible — lg:flex overrides the tablet hidden. */}
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

        {/* ── Footer ───────────────────────────────────────────────────── */}
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

      {/* Mobile sticky Plan button — only on form tab, only when no plan yet */}
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

      {/* Mobile summary bar — shown on map/timeline tabs when plan exists,
          so the user can see city + stop count without switching to the plan tab */}
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
