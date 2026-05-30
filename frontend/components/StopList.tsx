"use client";

// WHY uuid keys: using array index as key causes React to cross-wire inputs
// when a stop is removed from the middle. Using query string as key causes
// React and dnd-kit to treat two stops with the same query as the same
// element — dragging one would "tag along" the other and multiply entries
// in the timeline. Stable UUIDs that never derive from user input fix both.
import {
  DndContext,
  type DragEndEvent,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { StopDraft } from "@/lib/types";

// crypto.randomUUID requires a secure context (HTTPS or localhost). Fall back
// to a random string so the button works when accessing via a LAN IP in dev.
function uid(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function GripDots() {
  return (
    <svg
      width="8"
      height="12"
      viewBox="0 0 8 12"
      fill="currentColor"
      aria-hidden="true"
      className="flex-shrink-0"
    >
      <circle cx="2" cy="2" r="1.25" />
      <circle cx="6" cy="2" r="1.25" />
      <circle cx="2" cy="6" r="1.25" />
      <circle cx="6" cy="6" r="1.25" />
      <circle cx="2" cy="10" r="1.25" />
      <circle cx="6" cy="10" r="1.25" />
    </svg>
  );
}

function PinIcon({ active }: { active: boolean }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 14 14"
      fill="currentColor"
      aria-hidden="true"
    >
      {/* Simple filled pin / location marker */}
      <path d="M7 0a4.5 4.5 0 0 0-4.5 4.5C2.5 7.75 7 14 7 14s4.5-6.25 4.5-9.5A4.5 4.5 0 0 0 7 0Zm0 6.25a1.75 1.75 0 1 1 0-3.5 1.75 1.75 0 0 1 0 3.5Z" />
    </svg>
  );
}

interface RowProps {
  stop: StopDraft;
  index: number;
  total: number;
  pinned?: boolean;
  onUpdate: (value: string) => void;
  onRemove: () => void;
  onTogglePin?: () => void;
}

function SortableStopRow({ stop, index, total, pinned, onUpdate, onRemove, onTogglePin }: RowProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: stop.id });

  const showPin = onTogglePin !== undefined;

  return (
    <div
      ref={setNodeRef}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.35 : 1,
      }}
      className={`group flex items-center gap-2 rounded-sm transition-colors hover:bg-bg-base${pinned ? " border-l-2 border-accent pl-1" : ""}`}
      {...attributes}
    >
      {/* Drag handle */}
      <span
        className="cursor-grab touch-none text-text-tertiary"
        {...listeners}
      >
        <GripDots />
      </span>

      <span className="w-4 flex-shrink-0 text-right text-caption text-text-muted">
        {index + 1}
      </span>

      <input
        type="text"
        placeholder={`Stop ${index + 1}`}
        value={stop.query}
        onChange={(e) => onUpdate(e.target.value)}
        required
        title={stop.query || `Stop ${index + 1}`}
        className="input-base"
        style={{ textOverflow: "ellipsis" }}
      />

      {/* Pin icon — only on first/last; shows affordance for fixed_first/fixed_last */}
      {showPin && (
        <button
          type="button"
          onClick={onTogglePin}
          title={pinned ? "Unpin this stop" : "Pin as start/end — the optimiser won't move this"}
          aria-label={pinned ? "Unpin stop" : "Pin stop as anchor"}
          className={`-m-1 flex-shrink-0 rounded p-1 transition-colors duration-100 ${
            pinned
              ? "text-accent"
              : "text-text-ghost opacity-0 hover:text-text-muted hover:opacity-100 group-hover:opacity-100 focus:opacity-100"
          }`}
        >
          <PinIcon active={!!pinned} />
        </button>
      )}

      {/* × remove */}
      <button
        type="button"
        onClick={onRemove}
        disabled={total <= 2}
        aria-label={`Remove stop ${index + 1}`}
        className="-m-2 p-2 text-lg leading-none text-text-muted opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100 disabled:cursor-not-allowed disabled:opacity-0 group-hover:disabled:opacity-30"
      >
        ×
      </button>
    </div>
  );
}

interface Props {
  stops: StopDraft[];
  fixedFirst: boolean;
  fixedLast: boolean;
  onToggleFixedFirst: () => void;
  onToggleFixedLast: () => void;
  onChange: (stops: StopDraft[]) => void;
}

export default function StopList({
  stops,
  fixedFirst,
  fixedLast,
  onToggleFixedFirst,
  onToggleFixedLast,
  onChange,
}: Props) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  );

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const oldIndex = stops.findIndex((s) => s.id === active.id);
    const newIndex = stops.findIndex((s) => s.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;

    onChange(arrayMove(stops, oldIndex, newIndex));
  }

  function addStop() {
    onChange([...stops, { id: uid(), query: "" }]);
  }

  return (
    <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
      <SortableContext
        items={stops.map((s) => s.id)}
        strategy={verticalListSortingStrategy}
      >
        <div className="space-y-2">
          {stops.map((stop, i) => {
            const isFirst = i === 0;
            const isLast = i === stops.length - 1;
            // Pin icon only on first and last stops
            const pinned = isFirst ? fixedFirst : isLast ? fixedLast : undefined;
            const onTogglePin =
              isFirst
                ? onToggleFixedFirst
                : isLast
                ? onToggleFixedLast
                : undefined;
            return (
              <SortableStopRow
                key={stop.id}
                stop={stop}
                index={i}
                total={stops.length}
                pinned={pinned}
                onUpdate={(value) =>
                  onChange(stops.map((s, j) => (j === i ? { ...s, query: value } : s)))
                }
                onRemove={() => onChange(stops.filter((_, j) => j !== i))}
                onTogglePin={onTogglePin}
              />
            );
          })}
        </div>
      </SortableContext>

      <button
        type="button"
        onClick={addStop}
        disabled={stops.length >= 12}
        className="mt-3 w-full rounded-md border border-dashed border-border-default py-2.5 text-body text-text-secondary transition-colors duration-150 hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-40"
      >
        + Add another stop
      </button>
    </DndContext>
  );
}
