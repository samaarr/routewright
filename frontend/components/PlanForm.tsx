import type { FormState, TransportMode } from "@/lib/types";
import StopList from "./StopList";

interface Props {
  form: FormState;
  onChange: (form: FormState) => void;
  onSubmit: (form: FormState) => void;
  isLoading: boolean;
}

const MODES: TransportMode[] = ["transit", "walking", "driving"];

export default function PlanForm({ form, onChange, onSubmit, isLoading }: Props) {
  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    // start_time conversion (naive → UTC ISO) happens in toPayload() in
    // PlannerPage so both the initial submit and reorder paths are covered.
    onSubmit(form);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="mb-1 block text-sm font-medium text-zinc-700">
          City
        </label>
        <input
          type="text"
          placeholder="Dublin, Ireland"
          value={form.city}
          onChange={(e) => onChange({ ...form, city: e.target.value })}
          required
          className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-zinc-700">
          Stops
        </label>
        <StopList
          stops={form.stops}
          onChange={(stops) => onChange({ ...form, stops })}
        />
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-zinc-700">
          Start time
        </label>
        <input
          type="datetime-local"
          value={form.start_time}
          onChange={(e) => onChange({ ...form, start_time: e.target.value })}
          required
          className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-zinc-700">
          Mode
        </label>
        <div className="flex gap-4">
          {MODES.map((m) => (
            <label
              key={m}
              className="flex cursor-pointer items-center gap-1.5 text-sm text-zinc-700"
            >
              <input
                type="radio"
                name="mode"
                value={m}
                checked={form.mode === m}
                onChange={() => onChange({ ...form, mode: m })}
                className="accent-blue-600"
              />
              {m.charAt(0).toUpperCase() + m.slice(1)}
            </label>
          ))}
        </div>
      </div>

      <button
        type="submit"
        disabled={isLoading}
        className="w-full rounded-md bg-blue-600 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isLoading ? "Planning…" : "Generate"}
      </button>
    </form>
  );
}
