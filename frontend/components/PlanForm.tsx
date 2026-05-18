import type { FormState, TransportMode } from "@/lib/types";
import StopList from "./StopList";

interface Props {
  form: FormState;
  onChange: (form: FormState) => void;
  onSubmit: (form: FormState) => void;
  isLoading: boolean;
  mobileSubmitHidden?: boolean;
}

const MODES: { value: TransportMode; label: string }[] = [
  { value: "transit", label: "Transit" },
  { value: "walking", label: "Walking" },
  { value: "driving", label: "Driving" },
];

export default function PlanForm({ form, onChange, onSubmit, isLoading, mobileSubmitHidden }: Props) {
  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    // start_time conversion (naive → UTC ISO) happens in toPayload() in
    // PlannerPage so both the initial submit and reorder paths are covered.
    onSubmit(form);
  }

  return (
    <form id="plan-form" onSubmit={handleSubmit} className="space-y-5">
      <div>
        <label className="mb-2 block text-section-label">City</label>
        <input
          type="text"
          placeholder="Dublin, Ireland"
          value={form.city}
          onChange={(e) => onChange({ ...form, city: e.target.value })}
          required
          className="input-base"
        />
      </div>

      <div>
        <label className="mb-2 block text-section-label">Stops</label>
        <StopList
          stops={form.stops}
          onChange={(stops) => onChange({ ...form, stops })}
        />
      </div>

      <div>
        <label className="mb-2 block text-section-label">Departure</label>
        <input
          type="datetime-local"
          value={form.start_time}
          onChange={(e) => onChange({ ...form, start_time: e.target.value })}
          required
          className="input-base"
        />
      </div>

      <div>
        <label className="mb-2 block text-section-label">Mode</label>
        <div className="space-y-2">
          {MODES.map(({ value, label }) => (
            <label
              key={value}
              className={`flex cursor-pointer items-center gap-3 rounded-md border px-4 py-3 transition-colors duration-150 ${
                form.mode === value
                  ? "border-accent bg-accent-soft"
                  : "border-border-default hover:border-border-strong"
              }`}
            >
              <input
                type="radio"
                name="mode"
                value={value}
                checked={form.mode === value}
                onChange={() => onChange({ ...form, mode: value })}
                className="sr-only"
              />
              {/* Custom radio dot */}
              <div
                className={`flex h-[18px] w-[18px] flex-shrink-0 items-center justify-center rounded-full border-2 transition-colors duration-100 ${
                  form.mode === value ? "border-accent" : "border-border-default"
                }`}
              >
                {form.mode === value && (
                  <div className="h-2 w-2 rounded-full bg-accent" />
                )}
              </div>
              <span className="text-base font-medium text-text-primary">{label}</span>
            </label>
          ))}
        </div>
      </div>

      <button
        type="submit"
        disabled={isLoading}
        className={`btn-primary${isLoading ? " animate-pulse" : ""}${mobileSubmitHidden ? " hidden md:flex md:items-center md:justify-center" : ""}`}
      >
        {isLoading ? "Planning…" : "Plan ↗"}
      </button>
    </form>
  );
}
