import type { StopInput } from "@/lib/types";

interface Props {
  stops: StopInput[];
  onChange: (stops: StopInput[]) => void;
}

export default function StopList({ stops, onChange }: Props) {
  function updateQuery(index: number, value: string) {
    onChange(stops.map((s, i) => (i === index ? { ...s, query: value } : s)));
  }

  function addStop() {
    onChange([...stops, { query: "" }]);
  }

  function removeStop(index: number) {
    onChange(stops.filter((_, i) => i !== index));
  }

  return (
    <div className="space-y-2">
      {stops.map((stop, i) => (
        <div key={i} className="flex items-center gap-2">
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
        className="text-sm text-blue-600 hover:text-blue-800 disabled:cursor-not-allowed disabled:opacity-40"
      >
        + Add stop
      </button>
    </div>
  );
}
