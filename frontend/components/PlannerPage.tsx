"use client";

import { useState } from "react";
import type { Plan, PlanRequest, StopItem } from "@/lib/types";
import { postPlan, postRefreshLeg } from "@/lib/api";
import PlanForm from "./PlanForm";
import Timeline from "./Timeline";

type Refreshing =
  | { kind: "none" }
  | { kind: "reorder" }
  | { kind: "leg"; legTimelineIndex: number };

const DEFAULT_FORM: PlanRequest = {
  city: "",
  stops: [{ query: "" }, { query: "" }],
  start_time: "",
  mode: "transit",
};

export default function PlannerPage() {
  const [form, setForm] = useState<PlanRequest>(DEFAULT_FORM);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState<Refreshing>({ kind: "none" });
  // Reorder/refresh errors sit near the timeline, not above the form.
  const [timelineError, setTimelineError] = useState<string | null>(null);

  async function handleSubmit(req: PlanRequest) {
    setStatus("loading");
    setErrorMsg(null);
    setTimelineError(null);
    try {
      const result = await postPlan(req);
      setPlan(result);
      setStatus("idle");
    } catch (err) {
      setStatus("error");
      setErrorMsg(err instanceof Error ? err.message : "Something went wrong.");
    }
  }

  async function handleReorder(newQueries: string[]) {
    if (!plan) return;
    // Snapshot so we can revert on failure.
    const prevStops = form.stops;

    // Build reordered stops preserving any user-set stay_minutes.
    const queryToStop = new Map(prevStops.map((s) => [s.query, s]));
    const newStops = newQueries.map((q) => queryToStop.get(q) ?? { query: q });
    const newForm = { ...form, stops: newStops };

    setForm(newForm);
    setRefreshing({ kind: "reorder" });
    setTimelineError(null);
    try {
      const result = await postPlan(newForm);
      setPlan(result);
      setRefreshing({ kind: "none" });
    } catch (err) {
      // Revert to previous stop order.
      setForm({ ...form, stops: prevStops });
      setRefreshing({ kind: "none" });
      setTimelineError(
        "Couldn't update — your previous order is restored. Try again?"
      );
    }
  }

  async function handleLegRefresh(legTimelineIndex: number) {
    if (!plan) return;

    // Find the stops on either side of this leg.
    const timeline = plan.timeline;
    const legItem = timeline[legTimelineIndex];
    if (!legItem || legItem.item_type !== "leg") return;

    // The stop before the leg is at legTimelineIndex - 1,
    // the stop after is at legTimelineIndex + 1.
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
      // Splice the refreshed leg into the existing plan — stops stay unchanged.
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

  return (
    <main className="mx-auto max-w-lg px-4 py-10">
      <h1 className="mb-8 text-2xl font-bold text-zinc-900">RouteWright</h1>

      {/* Form-level errors: bad stop names, geocode failures */}
      {status === "error" && errorMsg && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {errorMsg}
        </div>
      )}

      <PlanForm
        form={form}
        onChange={setForm}
        onSubmit={handleSubmit}
        isLoading={status === "loading"}
      />

      {status === "idle" && plan === null && (
        <p className="mt-4 text-center text-sm text-zinc-400">
          Enter your stops and tap Generate.
        </p>
      )}

      {plan !== null && (
        <div className="mt-8">
          {/* Timeline-level errors: transient reorder/refresh failures */}
          {timelineError && (
            <div className="mb-3 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              <span className="flex-1">{timelineError}</span>
              <button
                type="button"
                onClick={() => setTimelineError(null)}
                aria-label="Dismiss"
                className="flex-shrink-0 text-amber-600 hover:text-amber-800"
              >
                ✕
              </button>
            </div>
          )}

          <Timeline
            plan={plan}
            onReorder={handleReorder}
            onLegRefresh={handleLegRefresh}
            isReordering={isReordering}
            refreshingLegIdx={refreshingLegIdx}
          />
        </div>
      )}
    </main>
  );
}
