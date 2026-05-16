"use client";

import { useState } from "react";
import type { FormState, Plan, PlanRequest, StopItem } from "@/lib/types";
import { postPlan, postRefreshLeg } from "@/lib/api";
import PlanForm from "./PlanForm";
import Timeline from "./Timeline";

type Refreshing =
  | { kind: "none" }
  | { kind: "reorder" }
  | { kind: "leg"; legTimelineIndex: number };

// Initialiser function so crypto.randomUUID() runs on the client at mount,
// not at module-load time (which would run on the server during SSR).
function makeDefaultForm(): FormState {
  return {
    city: "",
    stops: [
      { id: crypto.randomUUID(), query: "" },
      { id: crypto.randomUUID(), query: "" },
    ],
    start_time: "",
    mode: "transit",
  };
}

// Strip the frontend-only id field before sending to the backend.
function toPayload(form: FormState): PlanRequest {
  return {
    ...form,
    stops: form.stops.map(({ id: _, ...rest }) => rest),
  };
}

export default function PlannerPage() {
  const [form, setForm] = useState<FormState>(makeDefaultForm);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState<Refreshing>({ kind: "none" });
  // Reorder/refresh errors sit near the timeline, not above the form.
  const [timelineError, setTimelineError] = useState<string | null>(null);

  async function handleSubmit(formState: FormState) {
    setStatus("loading");
    setErrorMsg(null);
    setTimelineError(null);
    try {
      const result = await postPlan(toPayload(formState));
      setPlan(result);
      setStatus("idle");
    } catch (err) {
      setStatus("error");
      setErrorMsg(err instanceof Error ? err.message : "Something went wrong.");
    }
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
    } catch (err) {
      setForm({ ...form, stops: prevStops });
      setRefreshing({ kind: "none" });
      setTimelineError(
        "Couldn't update — your previous order is restored. Try again?"
      );
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

  return (
    <main className="mx-auto max-w-lg px-4 py-10">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-zinc-900">RouteWright</h1>
        <p className="mt-1 text-base text-zinc-600">
          Multi-stop transit planning that Google Maps doesn&apos;t do.
        </p>
      </div>

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
            stopIds={stopIds}
            onReorder={handleReorder}
            onLegRefresh={handleLegRefresh}
            isReordering={isReordering}
            refreshingLegIdx={refreshingLegIdx}
          />
        </div>
      )}
      <p className="mt-12 text-center text-sm text-zinc-400">
        Made in Dublin &middot;{" "}
        <a
          href="https://github.com/samaarr/routewright"
          target="_blank"
          rel="noopener noreferrer"
          className="underline underline-offset-2 hover:text-zinc-600"
        >
          github.com/samaarr/routewright
        </a>
      </p>
    </main>
  );
}
