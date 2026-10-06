"use client";

import type { Warning } from "@/lib/api-types";
import { fmtDuration, fmtTime } from "@/lib/utils";
import { resultIsStale, type PlannerState } from "@/lib/v2/state.ts";
import type { VFailedLeg, VKnownStop, VPlannedLeg, VPlanResult, VTimelineItem } from "@/lib/v2/validate.ts";

const FAILURE_TEXT: Record<string, string> = {
  no_route: "No route was found for this journey at that time.",
  provider_temporary: "The routing service didn't respond for this journey.",
  quota_exceeded: "Today's routing allowance ran out before this journey.",
  provider_capacity: "The routing service was busy for this journey.",
  deadline_exceeded: "Planning ran out of time before this journey.",
  cancelled: "Planning was stopped before this journey.",
};

export const REFRESH_UNAVAILABLE =
  "Refreshing a single journey from its planned departure is coming in a later update. Press Plan to recalculate the whole day.";

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

function LegRow({ leg, first }: { leg: VPlannedLeg; first: boolean }) {
  return (
    <li className="py-1 pl-20">
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
        <button
          type="button"
          disabled
          aria-disabled="true"
          title={REFRESH_UNAVAILABLE}
          aria-label="Refresh this journey (not available yet)"
          className="cursor-not-allowed p-1 text-xs text-text-ghost"
        >
          ↻
        </button>
      </div>
      {first && (
        <p className="mt-0.5 text-caption text-text-muted">
          Tap when you&apos;re heading out — live times open in Google Maps.
        </p>
      )}
    </li>
  );
}

function FailedRow({ leg }: { leg: VFailedLeg }) {
  return (
    <li className="py-2 pl-20" data-testid="tl-failed-leg">
      <p className="text-body text-error-text">⚠ {FAILURE_TEXT[leg.failure_reason] ?? "This journey couldn't be planned."}</p>
      <p className="text-caption text-text-muted">Times after this point are unknown.</p>
    </li>
  );
}

function Items({ items, plan, warnings }: { items: VTimelineItem[]; plan: { timezone: string }; warnings: Warning[] }) {
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
            return <StopRow key={`s-${item.instance_id}-${i}`} stop={item} tz={plan.timezone} warnings={byStop(item.instance_id)} />;
          case "leg":
            legCount += 1;
            return <LegRow key={`l-${i}`} leg={item} first={legCount === 1} />;
          case "failed_leg":
            return <FailedRow key={`f-${i}`} leg={item} />;
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

function ResultView({ plan, dimmed }: { plan: VPlanResult; dimmed: boolean }) {
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
      <Items items={plan.timeline} plan={plan} warnings={plan.warnings} />
    </div>
  );
}

export default function TimelineV2({ state }: { state: PlannerState }) {
  const { operation, result, notice } = state;
  const stale = resultIsStale(state);
  const running = operation.kind === "running";
  const plan = result?.plan ?? null;

  const liveItems: VTimelineItem[] = [];
  if (running) {
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

      {running && (
        <section aria-label="New timetable in progress" className="mb-6">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-accent">New timetable — in progress</p>
          {liveItems.length > 0 ? (
            <Items items={liveItems} plan={{ timezone: state.draft.city?.timezone ?? "UTC" }} warnings={[]} />
          ) : (
            <p className="text-sm text-text-muted">Waiting for the first confirmed stop…</p>
          )}
        </section>
      )}

      {plan && (
        <section aria-label={running || stale ? "Previous plan" : "Plan"}>
          {(running || stale) && (
            <p className="mb-2 text-xs font-medium text-text-muted" data-testid="stale-label">
              {stale
                ? "Previous plan — these times are for earlier trip details. Press Plan to update."
                : "Previous plan"}
            </p>
          )}
          <ResultView plan={plan} dimmed={running || stale} />
        </section>
      )}

      {!plan && !running && (
        <p className="text-sm text-text-muted">Choose a city and your stops, then press Plan to see your day.</p>
      )}

      {plan && !running && (
        <p className="mt-6 text-xs text-text-muted">
          To change the order or how long you stay, edit the stops and press Plan again. {REFRESH_UNAVAILABLE.split(".")[0]}.
        </p>
      )}
    </div>
  );
}
