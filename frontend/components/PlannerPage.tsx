"use client";

import { useState, useEffect } from "react";
import type { FormState, Plan, PlanRequest, StopItem } from "@/lib/types";
import { postPlan, postRefreshLeg } from "@/lib/api";
import { fmtDuration } from "@/lib/utils";
import PlanForm from "./PlanForm";
import PlanCanvas from "./PlanCanvas";

type Refreshing =
  | { kind: "none" }
  | { kind: "reorder" }
  | { kind: "leg"; legTimelineIndex: number };

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

// Strip the frontend-only id field and convert the naive datetime-local string
// to a UTC ISO 8601 string before sending to the backend.
// new Date("2026-05-17T19:10") interprets the value in the browser's local
// timezone; .toISOString() converts to UTC with a trailing Z — the backend
// validator requires timezone-aware datetimes.
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

export default function PlannerPage() {
  const [form, setForm] = useState<FormState>(makeDefaultForm);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState<Refreshing>({ kind: "none" });
  const [timelineError, setTimelineError] = useState<string | null>(null);
  // Controls the mobile sticky summary bar that appears when the user
  // scrolls past the timeline on a narrow viewport.
  const [showStickyBar, setShowStickyBar] = useState(false);

  useEffect(() => {
    if (!plan) {
      setShowStickyBar(false);
      return;
    }
    function onScroll() {
      if (window.innerWidth >= 768) {
        setShowStickyBar(false);
        return;
      }
      const anchor = document.getElementById("timeline-anchor");
      if (!anchor) return;
      setShowStickyBar(anchor.getBoundingClientRect().bottom < 0);
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener("scroll", onScroll);
  }, [plan]);

  async function handleSubmit(formState: FormState) {
    setStatus("loading");
    setErrorMsg(null);
    setTimelineError(null);
    try {
      const result = await postPlan(toPayload(formState));
      setPlan(result);
      setStatus("idle");
      scrollToTimeline();
    } catch (err) {
      setStatus("error");
      setErrorMsg(err instanceof Error ? err.message : "Something went wrong.");
    }
  }

  // On desktop (>=1024px) the timeline is always visible — no scroll needed.
  // On mobile the timeline is at the top of the stacked layout so we scroll up.
  function scrollToTimeline() {
    if (typeof window !== "undefined" && window.innerWidth >= 1024) return;
    setTimeout(() => {
      document.getElementById("timeline-anchor")?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }, 100);
  }

  // newIds: UUIDs in the new stop order — parallel to form.stops.
  async function handleReorder(newIds: string[]) {
    if (!plan) return;
    const prevStops = form.stops;

    // Reorder by UUID so identical query strings don't cross-wire.
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
      scrollToTimeline();
    } catch (err) {
      setForm({ ...form, stops: prevStops });
      setRefreshing({ kind: "none" });
      setTimelineError(
        "Couldn't update — your previous order is restored. Try again?"
      );
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
    } catch (err) {
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

  // Parallel array: form.stops[i].id corresponds to the i-th StopItem in
  // plan.timeline. Passed to Timeline so it can use UUIDs for dnd-kit ids
  // and React keys instead of query strings.
  const stopIds = form.stops.map((s) => s.id);
  const stopCount = form.stops.length;
  const totalDuration = plan ? computeTotalDuration(plan) : "";

  return (
    <>
      {/* Mobile sticky summary bar — appears when plan exists and the user
          has scrolled past the timeline. Tap to jump back up. */}
      {showStickyBar && plan && (
        <div
          className="fixed left-0 right-0 top-0 z-50 flex h-12 cursor-pointer items-center justify-between bg-pane-bg px-4 shadow-raised md:hidden"
          role="button"
          tabIndex={0}
          onClick={scrollToTimeline}
          onKeyDown={(e) => e.key === "Enter" && scrollToTimeline()}
          aria-label="Scroll back to timeline"
        >
          <span className="text-body-strong text-text-primary">
            {plan.city} · {stopCount} stop{stopCount !== 1 ? "s" : ""}
            {totalDuration ? ` · ${totalDuration}` : ""}
          </span>
          <span className="text-text-muted">↑</span>
        </div>
      )}

      <main className="mx-auto flex-1 max-w-[980px] px-4 lg:flex lg:flex-col lg:min-h-0 lg:overflow-hidden lg:px-6">
        {/* Header — full-width hero above both columns */}
        <div className="mb-6 mt-12 text-center lg:mb-8 lg:mt-16 lg:flex-shrink-0 lg:text-left">
          <h1 className="text-display text-text-primary">RouteWright</h1>
          <p className="mt-3 text-tagline">
            Multi-stop transit planning that Google Maps doesn&apos;t do.
          </p>
        </div>

        {/* Split-pane: stacked on mobile, side-by-side on lg+.
            On desktop lg:flex-1 lg:min-h-0 makes the row fill remaining
            viewport height so each column can scroll independently. */}
        <div className="flex flex-col gap-4 lg:min-h-0 lg:flex-1 lg:flex-row lg:items-stretch lg:gap-8">
          {/* Form column — white pane, order-2 (below) on mobile, order-1 (left) on lg+ */}
          <div
            className={`order-2 rounded-lg border border-border-subtle bg-pane-bg p-6 shadow-subtle lg:order-1 lg:w-[380px] lg:flex-shrink-0 lg:min-h-0 lg:overflow-y-auto lg:p-8 lg:[scrollbar-gutter:stable]${plan === null ? " pb-20 md:pb-6 lg:pb-8" : ""}`}
          >
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
          </div>

          {/* Timeline canvas — white pane, order-1 (above) on mobile, order-2 (right) on lg+ */}
          <div className="order-1 rounded-lg border border-border-subtle bg-pane-bg p-6 shadow-subtle lg:order-2 lg:flex-1 lg:max-w-[560px] lg:min-h-0 lg:overflow-y-auto lg:p-8 lg:[scrollbar-gutter:stable]">
            <PlanCanvas
              plan={plan}
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
          </div>
        </div>

        <p className="mb-10 mt-8 text-center text-body text-text-muted lg:flex-shrink-0">
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

      {/* Mobile sticky Plan button — visible only on mobile when no plan exists yet.
          Uses form="plan-form" to submit the PlanForm without being inside it. */}
      {plan === null && (
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
    </>
  );
}
