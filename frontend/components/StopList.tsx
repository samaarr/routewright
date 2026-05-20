// WHY uuid keys: using array index as key causes React to cross-wire inputs
// when a stop is removed from the middle. Using query string as key causes
// React and dnd-kit to treat two stops with the same query as the same
// element — dragging one would "tag along" the other and multiply entries
// in the timeline. Stable UUIDs that never derive from user input fix both.
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

interface Props {
  stops: StopDraft[];
  onChange: (stops: StopDraft[]) => void;
}

export default function StopList({ stops, onChange }: Props) {
  function updateQuery(index: number, value: string) {
    onChange(stops.map((s, i) => (i === index ? { ...s, query: value } : s)));
  }

  function addStop() {
    onChange([...stops, { id: uid(), query: "" }]);
  }

  function removeStop(index: number) {
    onChange(stops.filter((_, i) => i !== index));
  }

  return (
    <div className="space-y-2">
      {stops.map((stop, i) => (
        <div
          key={stop.id}
          className="animate-slide-down group flex items-center gap-2 rounded-sm transition-colors hover:bg-bg-base"
        >
          {/* Visual grip handle — decorative, matches timeline stop appearance */}
          <span className="cursor-grab text-text-tertiary">
            <GripDots />
          </span>

          {/* Stop number */}
          <span className="w-4 flex-shrink-0 text-right text-caption text-text-muted">
            {i + 1}
          </span>

          <input
            type="text"
            placeholder={`Stop ${i + 1}`}
            value={stop.query}
            onChange={(e) => updateQuery(i, e.target.value)}
            required
            className="input-base"
          />

          {/* × remove — invisible at rest, appears on row hover */}
          <button
            type="button"
            onClick={() => removeStop(i)}
            disabled={stops.length <= 2}
            aria-label={`Remove stop ${i + 1}`}
            className="-m-2 p-2 text-lg leading-none text-text-muted opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100 disabled:cursor-not-allowed disabled:opacity-0 group-hover:disabled:opacity-30"
          >
            ×
          </button>
        </div>
      ))}

      <button
        type="button"
        onClick={addStop}
        disabled={stops.length >= 12}
        className="mt-1 w-full rounded-md border border-dashed border-border-default py-2.5 text-body text-text-secondary transition-colors duration-150 hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-40"
      >
        + Add another stop
      </button>
    </div>
  );
}
