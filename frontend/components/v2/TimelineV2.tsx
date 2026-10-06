"use client";

import type { Warning } from "@/lib/api-types";
import { fmtDuration, fmtTime } from "@/lib/utils";
import { legPosition } from "@/lib/v2/refresh.ts";
import { progressLabel, refreshableTarget, resultIsStale, type PlannerState } from "@/lib/v2/state.ts";
import type { VFailedLeg, VKnownStop, VPlanResult, VPlannedLeg, VTimelineItem } from "@/lib/v2/validate.ts";

const FAILURE_TEXT: Record<string, string> = {
  no_route: "No route was found for this journey at that time.",
  provider_temporary: "The routing service didn't respond for this journey.",
  quota_exceeded: "Today's routing allowance ran out before this journey.",
  provider_capacity: "The routing service was busy for this journey.",
  deadline_exceeded: "Planning ran out of time before this journey.",
  cancelled: "Planning was stopped before this journey.",
};

const STALE_REASON = "Press Plan first — these times are for earlier trip details.";
const BUSY_REASON = "Wait for the current update to finish.";

interface Actions {
  /** Global leg index -> enabled? (null = no actions shown, e.g. live/previous items) */
  canRefresh: ((legIndex: number) => boolean) | null;
  disabledReason: string;
  onRefresh: (legIndex: number) => void;
}

function hoursText(stop: VKnownStop, tz: string): { text: string; tone: "ok" | "warn" | "muted" } | null {
  const d = stop.hours_detail;
  const status = stop.hours_status ?? "unknown";
  const qual =
    d?.hours_source === "weekly"
      ? " · usual weekly hours; holiday hours not confirmed"
      : d?.hours_source === "date_specific"
        ? ` · hours for this date${d.special_day ? " (special hours)" : ""}`
        : "";
  if (status === "unknown") return { text: "Opening hours unavailable", tone: "muted" };
  if (d?.always_open) return { text: `Open 24 hours${qual}`, tone: "ok" };
  if (status === "open") return { text: `Open${d?.closes_at ? ` until ${d.closes_at}` : ""}${qual}`, tone: "ok" };
  if (status === "closes_soon") return { text: `Closes soon (${d?.closes_at ?? "?"})${qual}`, tone: "warn" };
  if (status === "closes_during_visit") {
    return { text: `Closes at ${d?.closes_at ?? "?"}, during your visit${qual}`, tone: "warn" };
  }
  if (status === "closed_on_arrival") {
    const opens = d?.opens_at ? ` — opens ${d.opens_at}${d.opens_on ? ` on ${d.opens_on}` : ""}` : "";
    return { text: `Looks closed when you arrive (${fmtTime(stop.arrive_at, tz)})${opens}${qual}`, tone: "warn" };
  }
  return null;
}

function StopRow({ stop, tz, warnings }: { stop: VKnownStop; tz: string; warnings: Warning[] }) {
  const hours = hoursText(stop, tz);
  return (
    <li className="flex items-start py-3" data-testid={`tl-stop-${stop.instance_id}`}>
      <span className="w-14 flex-shrink-0 pt-0.5 text-right text-time-chip">{fmtTime(stop.arrive_at, tz)}</span>
      <div className="flex w-6 flex-shrink-0 justify-center pt-1.5">
        <div className="relative z-10 h-3 w-3 rounded-full bg-accent" />
      </div>
      <div className="min-w-0 flex-1">
        <span className="block text-body-strong">{stop.name}</span>
        {hours && (
          <p
            className={`mt-0.5 text-xs ${hours.tone === "warn" ? "text-spark" : hours.tone === "ok" ? "text-text-tertiary" : "text-text-muted"}`}
            data-testid="hours-line"
          >
            {hours.tone === "warn" ? "⚠ " : ""}
            {hours.text}
          </p>
        )}
        {stop.stay_minutes > 0 && (
          <p className="mt-1 text-xs text-text-secondary">
            Stay {stop.stay_minutes} min ({stop.stay_source === "user" ? "your choice" : "typical visit"}) · leave{" "}
            {fmtTime(stop.depart_at, tz)}
          </p>
        )}
        {warnings.map((w, i) => (
          <p key={i} className={`mt-1 text-xs ${w.severity === "info" ? "text-text-muted" : "text-warning-strong"}`}>
            {w.message}
          </p>
        ))}
      </div>
    </li>
  );
}

function ActionButton({
  legIndex,
  actions,
  label,
}: {
  legIndex: number;
  actions: Actions;
  label: "Refresh from here" | "Try again";
}) {
  if (!actions.canRefresh) return null;
  const enabled = actions.canRefresh(legIndex);
  return (
    <button
      type="button"
      onClick={() => actions.onRefresh(legIndex)}
      disabled={!enabled}
      title={enabled ? "Recalculate this journey and everything after it, from its planned departure" : actions.disabledReason}
      className="rounded px-1.5 py-0.5 text-xs text-accent underline-offset-2 hover:underline disabled:cursor-not-allowed disabled:text-text-ghost disabled:no-underline"
    >
      ↻ {label}
    </button>
  );
}

function LegRow({ leg, first, legIndex, actions }: { leg: VPlannedLeg; first: boolean; legIndex: number; actions: Actions }) {
  return (
    <li className="py-1 pl-20" data-testid={`tl-leg-${legIndex}`}>
      <div className="flex flex-wrap items-baseline gap-x-1.5">
        <span className="text-text-muted">↓</span>
        <span className="text-body text-text-secondary">{leg.summary}</span>
        <span className="text-text-ghost">· {fmtDuration(leg.duration_seconds)} ·</span>
        <a
          href={leg.map_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-body text-spark underline underline-offset-2 hover:opacity-75"
        >
          Get directions ↗
        </a>
        <ActionButton legIndex={legIndex} actions={actions} label="Refresh from here" />
      </div>
      {first && (
        <p className="mt-0.5 text-caption text-text-muted">
          Tap when you&apos;re heading out — live times open in Google Maps.
        </p>
      )}
    </li>
  );
}

function FailedRow({ leg, legIndex, actions }: { leg: VFailedLeg; legIndex: number; actions: Actions }) {
  return (
    <li className="py-2 pl-20" data-testid="tl-failed-leg">
      <p className="text-body text-error-text">
        ⚠ {FAILURE_TEXT[leg.failure_reason] ?? "This journey couldn't be planned."}{" "}
        <ActionButton legIndex={legIndex} actions={actions} label="Try again" />
      </p>
      <p className="text-caption text-text-muted">Times after this point are unknown.</p>
    </li>
  );
}

const NO_ACTIONS: Actions = { canRefresh: null, disabledReason: "", onRefresh: () => {} };

function Items({
  items,
  tz,
  warnings,
  legOffset = 0,
  actions = NO_ACTIONS,
}: {
  items: VTimelineItem[];
  tz: string;
  warnings: Warning[];
  legOffset?: number;
  actions?: Actions;
}) {
  let legCount = 0;
  // Hours warnings repeat what each stop's hours line already shows, so only
  // other stop warnings (e.g. outside-area) are listed under the stop.
  const byStop = (id: string) =>
    warnings.filter((w) => w.affects_instance_id === id && !(w.code ?? "").startsWith("hours_"));
  return (
    <ol className="relative before:absolute before:bottom-4 before:left-[4.25rem] before:top-4 before:border-l-2 before:border-dashed before:border-border-subtle">
      {items.map((item, i) => {
        switch (item.item_type) {
          case "stop":
            return <StopRow key={`s-${item.instance_id}-${i}`} stop={item} tz={tz} warnings={byStop(item.instance_id)} />;
          case "leg": {
            const legIndex = legOffset + legCount;
            legCount += 1;
            return <LegRow key={`l-${i}`} leg={item} first={legIndex === 0} legIndex={legIndex} actions={actions} />;
          }
          case "failed_leg": {
            const legIndex = legOffset + legCount;
            legCount += 1;
            return <FailedRow key={`f-${i}`} leg={item} legIndex={legIndex} actions={actions} />;
          }
          case "unknown_stop":
            return (
              <li key={`u-${item.instance_id}-${i}`} className="flex items-start py-3 opacity-70" data-testid={`tl-unknown-${item.instance_id}`}>
                <span className="w-14 flex-shrink-0 pt-0.5 text-right text-time-chip">—</span>
                <div className="flex w-6 flex-shrink-0 justify-center pt-1.5">
                  <div className="relative z-10 h-3 w-3 rounded-full border-2 border-accent bg-pane-bg" />
                </div>
                <div className="min-w-0 flex-1">
                  <span className="block text-body-strong">{item.name}</span>
                  <p className="text-xs text-text-muted">Arrival time unknown</p>
                  {byStop(item.instance_id).map((w, j) => (
                    <p key={j} className="mt-1 text-xs text-warning-strong">
                      {w.message}
                    </p>
                  ))}
                </div>
              </li>
            );
        }
      })}
    </ol>
  );
}

function ResultView({ plan, dimmed, actions }: { plan: VPlanResult; dimmed: boolean; actions: Actions }) {
  const general = plan.warnings.filter((w) => !w.affects_instance_id);
  return (
    <div className={dimmed ? "opacity-50" : undefined} data-testid={dimmed ? "previous-result" : "current-result"}>
      {plan.result_type === "partial" && (
        <p role="alert" className="mb-3 rounded-md border border-warning-border bg-warning-bg px-3 py-2 text-body text-warning-text">
          Only part of the day could be planned. Stops after the failed journey have unknown times.
        </p>
      )}
      {general.map((w, i) => (
        <p key={i} className="mb-2 text-xs text-text-muted">
          {w.message}
        </p>
      ))}
      <Items items={plan.timeline} tz={plan.timezone} warnings={plan.warnings} actions={actions} />
    </div>
  );
}

/** Live view while a refresh runs: prefix unchanged, new journeys separate,
 *  previous suffix visible but explicitly labelled. */
function RefreshingView({ state, plan, onCancel }: { state: PlannerState; plan: VPlanResult; onCancel: () => void }) {
  const op = state.operation;
  if (op.kind !== "running" || !op.refresh) return null;
  const pos = legPosition(plan.timeline, op.refresh.legIndex);
  const prefix = plan.timeline.slice(0, pos);
  const previous = plan.timeline.slice(pos);
  const live: VTimelineItem[] = [];
  op.legs.forEach((leg, i) => {
    live.push(leg);
    const stop = op.stops[i];
    if (stop) live.push(stop);
  });
  const prefixIds = new Set(prefix.flatMap((i) => (i.item_type === "stop" ? [i.instance_id] : [])));
  return (
    <div data-testid="refreshing-view">
      <Items items={prefix} tz={plan.timezone} warnings={plan.warnings.filter((w) => prefixIds.has(w.affects_instance_id ?? ""))} />
      <section aria-label="Refreshed journeys" className="my-4 rounded-md border border-accent-faint bg-accent-soft/40 px-3 py-3">
        <div className="flex items-center gap-2">
          <p role="status" aria-live="polite" className="flex-1 text-sm text-text-secondary" data-testid="refresh-progress">
            Refreshing from {op.refresh.fromName} → {op.refresh.toName} (planned{" "}
            {fmtTime(op.refresh.plannedDeparture, plan.timezone)}). {progressLabel(op)}
          </p>
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-border-default px-3 py-1.5 text-sm font-medium text-text-primary hover:border-border-strong"
          >
            Cancel
          </button>
        </div>
        {live.length > 0 && (
          <div className="mt-2" data-testid="refreshed-items">
            <p className="text-xs font-medium uppercase tracking-wide text-accent">Refreshed journeys</p>
            <Items items={live} tz={plan.timezone} warnings={[]} legOffset={op.refresh.legIndex} />
          </div>
        )}
      </section>
      <section aria-label="Previous timings — refreshing" data-testid="previous-timings">
        <p className="mb-1 text-xs font-medium text-text-muted">Previous timings — refreshing.</p>
        <div className="opacity-50">
          <Items items={previous} tz={plan.timezone} warnings={[]} legOffset={op.refresh.legIndex} />
        </div>
      </section>
    </div>
  );
}

export default function TimelineV2({
  state,
  onRefresh,
  onCancel,
}: {
  state: PlannerState;
  onRefresh: (legIndex: number) => void;
  onCancel: () => void;
}) {
  const { operation, result, notice } = state;
  const stale = resultIsStale(state);
  const running = operation.kind === "running";
  const refreshing = running && operation.purpose === "refresh";
  const planning = running && operation.purpose === "plan";
  const plan = result?.plan ?? null;

  const actions: Actions = {
    canRefresh: (legIndex) => refreshableTarget(state, legIndex) !== null,
    disabledReason: stale ? STALE_REASON : BUSY_REASON,
    onRefresh,
  };

  const liveItems: VTimelineItem[] = [];
  if (planning) {
    operation.stops.forEach((s, i) => {
      liveItems.push(s);
      const leg = operation.legs[i];
      if (leg) liveItems.push(leg);
    });
  }

  return (
    <div>
      <div className="sticky top-0 z-10 mb-6 flex items-center justify-between border-b border-border-subtle bg-pane-bg pb-4">
        <span className="text-display-large">Your day</span>
        {plan && !running && (
          <a href={plan.overview_map_url} target="_blank" rel="noopener noreferrer" className="text-sm text-spark hover:opacity-75">
            Overview map ↗
          </a>
        )}
      </div>

      {notice && (
        <div
          role="alert"
          data-testid="plan-notice"
          className={`mb-4 rounded-md border px-3 py-2 text-body ${
            notice.kind === "error" ? "border-error-border bg-error-bg text-error-text" : "border-warning-border bg-warning-bg text-warning-text"
          }`}
        >
          {notice.message}
        </div>
      )}

      {planning && (
        <section aria-label="New timetable in progress" className="mb-6">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-accent">New timetable — in progress</p>
          {liveItems.length > 0 ? (
            <Items items={liveItems} tz={state.draft.city?.timezone ?? "UTC"} warnings={[]} />
          ) : (
            <p className="text-sm text-text-muted">Waiting for the first confirmed stop…</p>
          )}
        </section>
      )}

      {refreshing && plan && <RefreshingView state={state} plan={plan} onCancel={onCancel} />}

      {plan && !refreshing && (
        <section aria-label={planning || stale ? "Previous plan" : "Plan"}>
          {(planning || stale) && (
            <p className="mb-2 text-xs font-medium text-text-muted" data-testid="stale-label">
              {stale
                ? "Previous plan — these times are for earlier trip details. Press Plan to update."
                : "Previous plan"}
            </p>
          )}
          <ResultView plan={plan} dimmed={planning || stale} actions={actions} />
        </section>
      )}

      {!plan && !running && (
        <p className="text-sm text-text-muted">Choose a city and your stops, then press Plan to see your day.</p>
      )}

      {plan && !running && (
        <p className="mt-6 text-xs text-text-muted">
          To change the order or how long you stay, edit the stops and press Plan again. “Refresh from here”
          recalculates a journey and everything after it from its planned departure.
        </p>
      )}
    </div>
  );
}
