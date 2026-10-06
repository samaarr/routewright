// Suffix refresh helpers (Step 7, D21).
//
// refreshTarget(): which leg can be refreshed and from which planned
// departure. A leg qualifies only when everything before it is confirmed
// (no failed journey or unknown stop earlier). The planned departure is the
// confirmed departure of the leg's origin stop in the current plan — the
// same instant every time, so "Try again" retries from the same planned
// departure rather than from "now".
//
// mergeRefresh(): builds the new plan atomically from the unchanged prefix
// (everything before leg k) plus the refreshed suffix. Old downstream items
// and their warnings are dropped wholesale — no old downstream timing is ever
// merged into refreshed results. Any inconsistency (different origin stop,
// different planned departure, different downstream stops) throws, and the
// caller keeps the previous plan.

import type { Warning } from "../api-types";
import type { VPlanResult, VRefreshResult, VTimelineItem } from "./validate.ts";

export interface RefreshTarget {
  legIndex: number;
  plannedDeparture: string; // ISO instant of leg k's planned departure
  fromStopId: string;
  fromName: string;
  toName: string;
  retry: boolean; // true when leg k is a failed journey ("Try again")
}

export class RefreshMergeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RefreshMergeError";
  }
}

/** Timeline position of the k-th journey (planned or failed), or -1. */
export function legPosition(timeline: VTimelineItem[], legIndex: number): number {
  let seen = -1;
  for (let i = 0; i < timeline.length; i++) {
    const t = timeline[i].item_type;
    if (t === "leg" || t === "failed_leg") {
      seen += 1;
      if (seen === legIndex) return i;
    }
  }
  return -1;
}

export function refreshTarget(plan: VPlanResult, legIndex: number): RefreshTarget | null {
  const tl = plan.timeline;
  const pos = legPosition(tl, legIndex);
  if (pos < 1) return null;
  const origin = tl[pos - 1];
  const leg = tl[pos];
  if (origin.item_type !== "stop" || (leg.item_type !== "leg" && leg.item_type !== "failed_leg")) return null;
  if (tl.slice(0, pos).some((i) => i.item_type === "failed_leg" || i.item_type === "unknown_stop")) return null;
  return {
    legIndex,
    plannedDeparture: origin.depart_at,
    fromStopId: origin.instance_id,
    fromName: leg.from_name,
    toName: leg.to_name,
    retry: leg.item_type === "failed_leg",
  };
}

function stopIds(items: VTimelineItem[]): string[] {
  return items.flatMap((i) => (i.item_type === "stop" || i.item_type === "unknown_stop" ? [i.instance_id] : []));
}

function sameWarning(a: Warning, b: Warning): boolean {
  return a.code === b.code && a.message === b.message && (a.affects_instance_id ?? null) === (b.affects_instance_id ?? null);
}

export function mergeRefresh(plan: VPlanResult, refresh: VRefreshResult): VPlanResult {
  const target = refreshTarget(plan, refresh.leg_index);
  if (!target) throw new RefreshMergeError("The refreshed journey is not refreshable in this plan.");
  if (Date.parse(target.plannedDeparture) !== Date.parse(refresh.planned_departure)) {
    throw new RefreshMergeError("The refresh used a different planned departure.");
  }
  const first = refresh.suffix[0];
  if (first.item_type !== "leg" && first.item_type !== "failed_leg") {
    throw new RefreshMergeError("The refresh does not start with the selected journey.");
  }
  if (first.from_stop_id !== target.fromStopId) {
    throw new RefreshMergeError("The refresh starts from a different stop.");
  }
  const pos = legPosition(plan.timeline, refresh.leg_index);
  const prefix = plan.timeline.slice(0, pos);
  const oldDownstream = stopIds(plan.timeline.slice(pos));
  const newDownstream = stopIds(refresh.suffix);
  if (oldDownstream.join("\u0000") !== newDownstream.join("\u0000")) {
    throw new RefreshMergeError("The refresh covers different stops.");
  }

  // Prefix stop warnings stay; every downstream warning comes from the refresh.
  const prefixIds = new Set(stopIds(prefix));
  const kept = plan.warnings.filter((w) =>
    w.affects_instance_id ? prefixIds.has(w.affects_instance_id) : !refresh.warnings.some((r) => sameWarning(r, w)),
  );
  const common = {
    operation_id: refresh.operation_id,
    input_revision: refresh.input_revision,
    city: plan.city,
    mode: plan.mode,
    timezone: plan.timezone,
    overview_map_url: plan.overview_map_url,
    timeline: [...prefix, ...refresh.suffix],
    warnings: [...kept, ...refresh.warnings],
  };
  if (refresh.result_type === "refresh_partial") {
    return {
      ...common,
      result_type: "partial",
      failed_at_leg_index: refresh.failed_at_leg_index,
      failure_reason: refresh.failure_reason,
    };
  }
  return { ...common, result_type: "complete" };
}
