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
        <div key={stop.id} className="flex items-center gap-2">
          <span className="w-4 flex-shrink-0 text-right text-xs text-zinc-400">
            {i + 1}
          </span>
          <input
            type="text"
            placeholder={`Stop ${i + 1}`}
            value={stop.query}
            onChange={(e) => updateQuery(i, e.target.value)}
            required
            className="flex-1 rounded-md border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            type="button"
            onClick={() => removeStop(i)}
            disabled={stops.length <= 2}
            aria-label={`Remove stop ${i + 1}`}
            className="text-lg leading-none text-zinc-400 hover:text-zinc-700 disabled:cursor-not-allowed disabled:opacity-30"
          >
            ×
          </button>
        </div>
      ))}

      <button
        type="button"
        onClick={addStop}
        disabled={stops.length >= 12}
        className="py-2 text-sm text-blue-600 hover:text-blue-800 disabled:cursor-not-allowed disabled:opacity-40"
      >
        + Add stop
      </button>
    </div>
  );
}
