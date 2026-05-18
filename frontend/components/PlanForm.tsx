import type { FormState, TransportMode } from "@/lib/types";
import StopList from "./StopList";

interface Props {
  form: FormState;
  onChange: (form: FormState) => void;
  onSubmit: (form: FormState) => void;
  isLoading: boolean;
  mobileSubmitHidden?: boolean;
}

const MODES: TransportMode[] = ["transit", "walking", "driving"];

export default function PlanForm({ form, onChange, onSubmit, isLoading, mobileSubmitHidden }: Props) {
  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    // start_time conversion (naive → UTC ISO) happens in toPayload() in
    // PlannerPage so both the initial submit and reorder paths are covered.
    onSubmit(form);
  }

  return (
    <form id="plan-form" onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="mb-1 block text-body-strong text-text-label">
          City
        </label>
        <input
          type="text"
          placeholder="Dublin, Ireland"
          value={form.city}
          onChange={(e) => onChange({ ...form, city: e.target.value })}
          required
          className="w-full rounded-md border border-border-default px-3 py-2 text-body focus:outline-none focus:ring-2 focus:ring-accent-emphasis"
        />
      </div>

      <div>
        <label className="mb-1 block text-body-strong text-text-label">
          Stops
        </label>
        <StopList
          stops={form.stops}
          onChange={(stops) => onChange({ ...form, stops })}
        />
      </div>

      <div>
        <label className="mb-1 block text-body-strong text-text-label">
          Start time
        </label>
        <input
          type="datetime-local"
          value={form.start_time}
          onChange={(e) => onChange({ ...form, start_time: e.target.value })}
          required
          className="w-full rounded-md border border-border-default px-3 py-2 text-body focus:outline-none focus:ring-2 focus:ring-accent-emphasis"
        />
      </div>

      <div>
        <label className="mb-1 block text-body-strong text-text-label">
          Mode
        </label>
        <div className="flex gap-4">
          {MODES.map((m) => (
            <label
              key={m}
              className="flex cursor-pointer items-center gap-1.5 text-body text-text-label"
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
        className={`w-full rounded-md bg-accent py-2.5 text-body-strong text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50${mobileSubmitHidden ? " hidden md:block" : ""}`}
      >
        {isLoading ? "Planning…" : "Plan ↗"}
      </button>
    </form>
  );
}
