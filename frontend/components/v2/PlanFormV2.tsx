"use client";

import {
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { Dispatch } from "react";
import { selectCity, selectPlace, suggestCities, suggestPlaces } from "@/lib/v2/client.ts";
import { AREA_UNAVAILABLE_MESSAGE, OUTSIDE_AREA_MESSAGE } from "@/lib/v2/area.ts";
import {
  MAX_STAY_MINUTES,
  MAX_STOPS,
  departureCheck,
  progressLabel,
  readiness,
  stopChecks,
  type Action,
  type Mode,
  type PlannerState,
  type StopCheck,
  type StopDraft,
} from "@/lib/v2/state.ts";
import type { VViewport } from "@/lib/v2/validate.ts";
import SearchSelect from "./SearchSelect";

function uid(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

const MODES: { value: Mode; label: string }[] = [
  { value: "transit", label: "Transit" },
  { value: "walking", label: "Walking" },
  { value: "driving", label: "Driving" },
];

function GripDots() {
  return (
    <svg width="8" height="12" viewBox="0 0 8 12" fill="currentColor" aria-hidden="true" className="flex-shrink-0">
      {[2, 6, 10].flatMap((y) => [2, 6].map((x) => <circle key={`${x}-${y}`} cx={x} cy={y} r="1.25" />))}
    </svg>
  );
}

interface RowProps {
  stop: StopDraft;
  index: number;
  total: number;
  check: StopCheck;
  pinned: boolean | null;
  serverFlagged: boolean;
  cityId: string;
  cityViewport: VViewport | null;
  dispatch: Dispatch<Action>;
}

function StopRow({ stop, index, total, check, pinned, serverFlagged, cityId, cityViewport, dispatch }: RowProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: stop.id });
  const notes: { text: string; tone: "warn" | "error" | "info" }[] = [];
  if (check.timezoneProblem === "different") {
    notes.push({ text: "This place is in a different timezone from the selected city. Trips must stay in one timezone.", tone: "error" });
  } else if (check.timezoneProblem === "unresolved") {
    notes.push({ text: "This place's timezone couldn't be determined. Choose a different place.", tone: "error" });
  }
  if (check.area === "outside") notes.push({ text: OUTSIDE_AREA_MESSAGE, tone: "warn" });
  if (serverFlagged) notes.push({ text: "This place needs to be selected again.", tone: "error" });
  const noteId = `stop-notes-${stop.id}`;

  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.35 : 1 }}
      className={`group rounded-sm py-1 ${pinned ? "border-l-2 border-accent pl-1" : ""}`}
      data-testid={`stop-row-${index}`}
    >
      <div className="flex items-start gap-2">
        <button
          type="button"
          className="mt-3 cursor-grab touch-none text-text-tertiary"
          aria-label={`Move stop ${index + 1}`}
          {...attributes}
          {...listeners}
        >
          <GripDots />
        </button>
        <span className="mt-2.5 w-4 flex-shrink-0 text-right text-caption text-text-muted">{index + 1}</span>
        <SearchSelect
          label={`Stop ${index + 1}`}
          placeholder={`Stop ${index + 1}`}
          query={stop.query}
          selected={stop.selected !== null}
          context={cityId}
          invalid={serverFlagged || check.timezoneProblem !== null}
          describedBy={notes.length ? noteId : undefined}
          testId={`stop-search-${index}`}
          fetchSuggestions={(q, token, signal) => suggestPlaces(q, token, cityViewport, signal)}
          confirm={(placeId, token, signal) => selectPlace(placeId, token, signal)}
          onQueryChange={(q) => dispatch({ type: "stopQuery", id: stop.id, query: q })}
          onSelected={(place, s) => dispatch({ type: "stopSelected", id: stop.id, place, label: s.primary_text })}
        />
        <button
          type="button"
          onClick={() => dispatch({ type: "stopRemoved", id: stop.id })}
          disabled={total <= 2}
          aria-label={`Remove stop ${index + 1}`}
          className="mt-1.5 p-2 text-lg leading-none text-text-muted disabled:cursor-not-allowed disabled:opacity-30"
        >
          ×
        </button>
      </div>
      <div className="ml-12 mt-1 flex items-center gap-3">
        <label className="flex items-center gap-1.5 text-xs text-text-muted">
          <span>Stay</span>
          <input
            type="number"
            min={0}
            max={MAX_STAY_MINUTES}
            step={5}
            inputMode="numeric"
            placeholder="auto"
            aria-label={`Stay at stop ${index + 1} in minutes (blank for the usual time)`}
            value={stop.stayMinutes ?? ""}
            onChange={(e) => {
              const raw = e.target.value;
              if (raw === "") return dispatch({ type: "stayChanged", id: stop.id, minutes: null });
              const n = Number(raw);
              if (Number.isInteger(n)) dispatch({ type: "stayChanged", id: stop.id, minutes: n });
            }}
            className="w-16 rounded border border-border-default bg-bg-elevated px-1 py-0.5 text-center text-sm text-text-primary"
          />
          <span>min</span>
        </label>
        {pinned !== null && (
          <button
            type="button"
            onClick={() => dispatch({ type: "pinToggled", end: index === 0 ? "first" : "last" })}
            aria-pressed={pinned}
            aria-label={pinned ? `Unpin stop ${index + 1} (route optimisation may move it)` : `Pin stop ${index + 1} in place for route optimisation`}
            title={pinned ? "Pinned: route optimisation won't move this stop" : "Unpinned: route optimisation may move this stop"}
            className={`rounded px-1 text-xs ${pinned ? "text-accent" : "text-text-muted"}`}
          >
            {pinned ? "📌 Pinned" : "Unpinned"}
          </button>
        )}
      </div>
      {notes.length > 0 && (
        <ul id={noteId} className="ml-12 mt-0.5 space-y-0.5">
          {notes.map((n) => (
            <li
              key={n.text}
              className={`text-xs ${n.tone === "error" ? "text-error-text" : n.tone === "warn" ? "text-warning-strong" : "text-text-muted"}`}
            >
              {n.tone === "error" ? "⚠ " : ""}
              {n.text}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

interface Props {
  state: PlannerState;
  dispatch: Dispatch<Action>;
  onPlan: () => void;
  onCancel: () => void;
}

export default function PlanFormV2({ state, dispatch, onPlan, onCancel }: Props) {
  const { draft, operation, notice } = state;
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const checks = stopChecks(draft);
  const dep = departureCheck(draft);
  const ready = readiness(state);
  const running = operation.kind === "running";
  const flagged = new Set(notice?.kind === "error" ? notice.instanceIds : []);
  const cityFlagged = notice?.kind === "error" && notice.role === "city";
  const progress = progressLabel(operation);

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const ids = draft.stops.map((s) => s.id);
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from >= 0 && to >= 0) dispatch({ type: "stopsReordered", ids: arrayMove(ids, from, to) });
  }

  return (
    <form
      id="plan-form"
      className="space-y-5"
      onSubmit={(e) => {
        e.preventDefault();
        onPlan();
      }}
      noValidate
    >
      <div>
        <span className="mb-2 block text-section-label">City</span>
        <SearchSelect
          label="City"
          placeholder="Dublin, Ireland"
          query={draft.cityQuery}
          selected={draft.city !== null}
          context="cities"
          invalid={cityFlagged}
          testId="city-search"
          fetchSuggestions={(q, token, signal) => suggestCities(q, token, signal)}
          confirm={(placeId, token, signal) => selectCity(placeId, token, signal)}
          onQueryChange={(q) => dispatch({ type: "cityQuery", query: q })}
          onSelected={(city, s) =>
            dispatch({ type: "citySelected", city, query: s.secondary_text ? `${s.primary_text}, ${s.secondary_text}` : s.primary_text })
          }
        />
        {draft.city && (
          <p className="mt-1 text-xs text-text-muted" data-testid="city-context">
            Times use {draft.city.name} local time ({draft.city.timezone}).
            {draft.city.viewport === null && ` ${AREA_UNAVAILABLE_MESSAGE}`}
          </p>
        )}
      </div>

      <div>
        <span className="mb-2 block text-section-label">Stops</span>
        <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
          <SortableContext items={draft.stops.map((s) => s.id)} strategy={verticalListSortingStrategy}>
            <ol className="space-y-1">
              {draft.stops.map((stop, i) => (
                <StopRow
                  key={stop.id}
                  stop={stop}
                  index={i}
                  total={draft.stops.length}
                  check={checks[i]}
                  pinned={i === 0 ? draft.pinFirst : i === draft.stops.length - 1 ? draft.pinLast : null}
                  serverFlagged={flagged.has(stop.id)}
                  cityId={draft.city?.place_id ?? ""}
                  cityViewport={draft.city?.viewport ?? null}
                  dispatch={dispatch}
                />
              ))}
            </ol>
          </SortableContext>
        </DndContext>
        <button
          type="button"
          onClick={() => dispatch({ type: "stopAdded", id: uid() })}
          disabled={draft.stops.length >= MAX_STOPS}
          className="mt-3 w-full rounded-md border border-dashed border-border-default py-2.5 text-body text-text-secondary transition-colors duration-150 hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-40"
        >
          + Add another stop
        </button>
        <p className="mt-2 text-xs text-text-muted">
          Leave “stay” blank for a typical visit length. The first and last stops default to no stay.
        </p>
      </div>

      <fieldset>
        <legend className="mb-2 block text-section-label">
          Departure{draft.city ? ` (${draft.city.name} time)` : ""}
        </legend>
        <div className="flex gap-2">
          <input
            type="date"
            style={{ minWidth: 0 }}
            aria-label="Departure date"
            value={draft.date}
            onChange={(e) => dispatch({ type: "dateChanged", date: e.target.value })}
            className="input-base"
          />
          <input
            type="time"
            style={{ minWidth: 0 }}
            aria-label="Departure time"
            value={draft.time}
            onChange={(e) => dispatch({ type: "timeChanged", time: e.target.value })}
            className="input-base"
          />
        </div>
        <p className="mt-1 text-xs text-text-muted">
          {draft.city
            ? "You start at stop 1 at this time; the first journey leaves after any stay there."
            : "Choose a city to set its local time."}
        </p>
        {dep.kind === "nonexistent" && (
          <p role="alert" className="mt-1 text-xs text-error-text">
            The clocks skip this time on that date in {draft.city?.name}. Choose another time.
          </p>
        )}
        {dep.kind === "invalid" && (
          <p role="alert" className="mt-1 text-xs text-error-text">
            That isn&apos;t a valid date and time.
          </p>
        )}
        {dep.kind === "ambiguous" && (
          <div role="radiogroup" aria-label="Which occurrence of this time?" className="mt-2 space-y-1 text-xs">
            <p className="text-text-secondary">
              {draft.time} happens twice on this date because the clocks go back. Which one?
            </p>
            {dep.options.map((o) => (
              <label key={o.occurrence} className="flex items-center gap-2">
                <input
                  type="radio"
                  name="occurrence"
                  checked={draft.occurrence === o.occurrence}
                  onChange={() => dispatch({ type: "occurrenceChanged", occurrence: o.occurrence })}
                />
                {o.occurrence === 1 ? "First" : "Second"} {draft.time} ({o.offsetLabel})
              </label>
            ))}
          </div>
        )}
      </fieldset>

      <fieldset>
        <legend className="mb-2 block text-section-label">Mode</legend>
        <div className="space-y-2">
          {MODES.map(({ value, label }) => (
            <label
              key={value}
              className={`flex cursor-pointer items-center gap-3 rounded-md border px-4 py-3 transition-colors duration-150 ${
                draft.mode === value ? "border-accent bg-accent-soft" : "border-border-default hover:border-border-strong"
              }`}
            >
              <input
                type="radio"
                name="mode"
                value={value}
                checked={draft.mode === value}
                onChange={() => dispatch({ type: "modeChanged", mode: value })}
                className="sr-only"
              />
              <span className={`h-[18px] w-[18px] rounded-full border-2 ${draft.mode === value ? "border-[6px] border-accent" : "border-border-default"}`} />
              <span className="text-base font-medium text-text-primary">{label}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="space-y-2">
        {running && (
          <div className="flex items-center gap-2">
            <p role="status" aria-live="polite" className="flex-1 text-sm text-text-secondary" data-testid="plan-progress">
              {progress}
            </p>
            <button
              type="button"
              onClick={onCancel}
              className="rounded-md border border-border-default px-4 py-2 text-sm font-medium text-text-primary hover:border-border-strong"
            >
              Cancel
            </button>
          </div>
        )}
        <button
          type="submit"
          disabled={!ready.ready}
          title={running ? "Starts a new plan and stops the current update" : undefined}
          className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          Plan ↗
        </button>
        {!running && !ready.ready && ready.reasons.length > 0 && (
          <ul className="space-y-0.5 text-xs text-text-muted" data-testid="plan-blockers">
            {ready.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        )}
      </div>
    </form>
  );
}
