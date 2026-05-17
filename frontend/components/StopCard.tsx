import { useState } from "react";
import type { StopItem } from "@/lib/types";
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

export default function StopCard({ stop, isFirst, isLast, dragHandleProps, onStayEdit }: Props) {
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
    <div className="flex items-start py-2.5">
      {/* Drag handle — w-6 column, 44px tall touch target via py-2 */}
      <button
        type="button"
        aria-label="Drag to reorder"
        /* touch-none prevents scroll conflict on mobile during drag */
        className="flex w-6 flex-shrink-0 cursor-grab items-center justify-center py-2 text-zinc-300 touch-none hover:text-zinc-500 active:cursor-grabbing"
        {...(dragHandleProps ?? {})}
      >
        <GripIcon />
      </button>

      {/* Arrival time — right-aligned in fixed column */}
      <span className="w-12 flex-shrink-0 pt-0.5 text-right text-sm font-semibold tabular-nums text-zinc-900">
        {fmtTime(stop.arrive_at)}
      </span>

      {/* Dot — centred over the dotted vertical line (line is at left-[5rem]) */}
      <div className="flex w-4 flex-shrink-0 justify-center pt-1">
        <div className="relative z-10 h-2.5 w-2.5 rounded-full border-2 border-blue-500 bg-white" />
      </div>

      {/* Content — name + optional stay/leave info. min-w-0 enables truncate. */}
      <div className="ml-2 min-w-0 flex-1">
        <div className="flex flex-col sm:flex-row sm:items-baseline sm:gap-2">
          <span className="truncate font-medium text-zinc-900">{stop.name}</span>

          {showStayInfo && (
            <span className="flex-shrink-0 text-sm text-zinc-400">
              {editing ? (
                <>
                  {"· stay "}
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
                    className="w-12 rounded border border-blue-400 bg-white px-1 text-center text-sm text-zinc-900 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                  {" min"}
                </>
              ) : (
                <>
                  {"· "}
                  {onStayEdit ? (
                    <button
                      type="button"
                      onClick={startEdit}
                      title="Tap to edit"
                      className={`-mx-0.5 rounded px-0.5 hover:text-zinc-600 ${stop.stay_source === "user" ? "font-medium text-zinc-600" : ""}`}
                    >
                      stay {stop.stay_minutes} min
                    </button>
                  ) : (
                    <>stay {stop.stay_minutes} min</>
                  )}
                  {" · leave "}
                  {fmtTime(stop.depart_at)}
                </>
              )}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
