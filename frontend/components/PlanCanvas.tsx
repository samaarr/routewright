import type { Plan } from "@/lib/types";
import Timeline from "./Timeline";
import EmptyTimeline from "./EmptyTimeline";

interface Props {
  plan: Plan | null;
  stopCount: number;
  stopIds: string[];
  timelineError: string | null;
  onTimelineErrorDismiss: () => void;
  onReorder: (newIds: string[]) => void;
  onLegRefresh: (legTimelineIndex: number) => void;
  onStayEdit: (stopId: string, minutes: number) => void;
  isReordering: boolean;
  refreshingLegIdx: number | null;
}

export default function PlanCanvas({
  plan,
  stopCount,
  stopIds,
  timelineError,
  onTimelineErrorDismiss,
  onReorder,
  onLegRefresh,
  onStayEdit,
  isReordering,
  refreshingLegIdx,
}: Props) {
  return (
    <div>
      {/* Scroll target — scrollToTimeline() anchors here so the full pane
          including the "Your day" header lands at the top of the viewport. */}
      <div id="timeline-anchor" />

      {/* Pane header — sticky so it stays visible as the timeline scrolls */}
      <div className="sticky top-0 z-10 mb-6 flex items-baseline justify-between border-b border-border-subtle bg-pane-bg pb-4">
        <span className="text-display-large">Your day</span>
        {plan && (
          <a
            href={plan.overview_map_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-text-secondary transition-colors hover:text-accent"
          >
            Overview map ↗
          </a>
        )}
      </div>

      {timelineError && (
        <div className="mb-4 flex items-start gap-2 rounded-md border border-warning-border bg-warning-bg px-3 py-2 text-body text-warning-text">
          <span className="flex-1">{timelineError}</span>
          <button
            type="button"
            onClick={onTimelineErrorDismiss}
            aria-label="Dismiss"
            className="flex-shrink-0 text-warning-icon hover:text-warning-text"
          >
            ✕
          </button>
        </div>
      )}

      {plan !== null ? (
        <Timeline
          plan={plan}
          stopIds={stopIds}
          onReorder={onReorder}
          onLegRefresh={onLegRefresh}
          onStayEdit={onStayEdit}
          isReordering={isReordering}
          refreshingLegIdx={refreshingLegIdx}
        />
      ) : (
        <EmptyTimeline stopCount={stopCount} />
      )}
    </div>
  );
}
