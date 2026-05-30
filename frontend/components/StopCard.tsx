import { useState } from "react";
import type { HoursDetail, HoursStatus, StopItem } from "@/lib/types";
import { fmtTime } from "@/lib/utils";

// Opaque handle prop type: dnd-kit listeners are event-handler records.
// Typed loosely here to avoid importing @dnd-kit/core in this component.
type DragHandleProps = Record<string, React.EventHandler<React.SyntheticEvent>>;

interface Props {
  stop: StopItem;
  isFirst: boolean;
  isLast: boolean;
  dragHandleProps?: DragHandleProps;
  onStayEdit?: (minutes: number) => void;
  tz?: string;
}

function GripIcon() {
  return (
    <svg
      width="10"
      height="14"
      viewBox="0 0 10 14"
      fill="currentColor"
      aria-hidden="true"
    >
      <circle cx="2" cy="2" r="1.5" />
      <circle cx="8" cy="2" r="1.5" />
      <circle cx="2" cy="7" r="1.5" />
      <circle cx="8" cy="7" r="1.5" />
      <circle cx="2" cy="12" r="1.5" />
      <circle cx="8" cy="12" r="1.5" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Hours status line — one quiet line under the stop name.
// "unknown" renders nothing (no false "closed" for places without hours data).
// ---------------------------------------------------------------------------

function HoursStatusLine({
  status,
  detail,
  arriveAt,
  tz,
}: {
  status: HoursStatus;
  detail: HoursDetail | null;
  arriveAt: string;
  tz?: string;
}) {
  if (status === "unknown") return null;

  if (status === "open") {
    const closesAt = detail?.closes_at;
    return (
      <p className="mt-0.5 text-xs text-text-tertiary">
        {closesAt === "00:00" ? "Open 24 hours" : `Open${closesAt ? ` · until ${closesAt}` : ""}`}
      </p>
    );
  }

  if (status === "closed_on_arrival") {
    const opensAt = detail?.opens_at;
    const arrive = fmtTime(arriveAt, tz);
    return (
      <p className="mt-0.5 text-xs text-spark">
        ⚠ {opensAt ? `Opens ${opensAt}` : "Closed"} — you arrive {arrive}
      </p>
    );
  }

  if (status === "closes_during_visit") {
    return (
      <p className="mt-0.5 text-xs text-spark">
        ⚠ Closes {detail?.closes_at ?? "early"} — during your visit
      </p>
    );
  }

  if (status === "closes_soon") {
    return (
      <p className="mt-0.5 text-xs text-text-secondary">
        Closes soon{detail?.closes_at ? ` (${detail.closes_at})` : ""}
      </p>
    );
  }

  return null;
}

export default function StopCard({ stop, isFirst, isLast, dragHandleProps, onStayEdit, tz }: Props) {
  const showStayInfo = !isFirst && !isLast && stop.stay_minutes > 0;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  function startEdit() {
    setDraft(stop.stay_minutes.toString());
    setEditing(true);
  }

  function commit() {
    const val = parseInt(draft, 10);
    if (!isNaN(val) && val >= 0 && val <= 480) {
      onStayEdit?.(val);
    }
    setEditing(false);
  }

  function cancel() {
    setEditing(false);
  }

  return (
    <div className="group flex items-start py-3">
      {/* Drag handle — w-6 column, 44px tall touch target via py-2 */}
      <button
        type="button"
        aria-label="Drag to reorder"
        /* touch-none prevents scroll conflict on mobile during drag */
        className="flex w-6 flex-shrink-0 cursor-grab items-center justify-center py-2 text-text-ghost touch-none hover:text-text-tertiary active:cursor-grabbing"
        {...(dragHandleProps ?? {})}
      >
        <GripIcon />
      </button>

      {/* Arrival time — right-aligned in fixed column */}
      <span className="w-12 flex-shrink-0 pt-0.5 text-right text-time-chip">
        {fmtTime(stop.arrive_at, tz)}
      </span>

      {/* Dot — centred over the dotted vertical line (line is at left-[5rem]) */}
      <div className="flex w-4 flex-shrink-0 justify-center pt-1.5">
        <div
          className="relative z-10 h-3 w-3 rounded-full bg-accent transition-shadow duration-150 group-hover:shadow-[0_0_0_4px_var(--color-marker-glow-spark)]"
        />
      </div>

      {/* Content — name + optional stay chip. min-w-0 enables truncate. */}
      <div className="ml-2 min-w-0 flex-1">
        <span className="block truncate text-body-strong">{stop.name}</span>
        <HoursStatusLine
          status={stop.hours_status}
          detail={stop.hours_detail}
          arriveAt={stop.arrive_at}
          tz={tz}
        />

        {showStayInfo && (
          <div className="mt-1">
            {editing ? (
              <div className="flex items-center gap-1 text-sm text-text-secondary">
                <span>stay</span>
                <input
                  type="number"
                  min={0}
                  max={480}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onBlur={commit}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") e.currentTarget.blur();
                    if (e.key === "Escape") cancel();
                  }}
                  autoFocus
                  className="w-14 rounded border border-accent-border bg-bg-elevated px-1.5 py-0.5 text-center text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-accent-emphasis"
                />
                <span>min</span>
              </div>
            ) : (
              <button
                type="button"
                onClick={onStayEdit ? startEdit : undefined}
                disabled={!onStayEdit}
                title={onStayEdit ? "Tap to edit" : undefined}
                className={`inline-flex items-center rounded-sm border px-2 py-0.5 text-xs transition-colors duration-100 ${
                  stop.stay_source === "user"
                    ? "border-accent-faint bg-accent-soft font-medium text-accent hover:border-accent"
                    : "border-border-subtle bg-bg-base text-text-secondary hover:border-border-default hover:text-text-primary"
                } ${onStayEdit ? "cursor-pointer" : "cursor-default"}`}
              >
                stay {stop.stay_minutes} min · leave {fmtTime(stop.depart_at, tz)}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
