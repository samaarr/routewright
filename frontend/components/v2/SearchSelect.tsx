"use client";

// Explicit-selection combobox for a city or a stop (D13, D26, D34-D36).
//
// Typing never selects anything: suggestions appear after a 300 ms pause
// (two-character minimum), the Search button searches immediately for any
// nonblank text, and only choosing a suggestion — then confirming it with the
// backend — produces a selection. Editing the text after choosing clears the
// selection (the parent does that on onQueryChange). A confirmation that
// returns after the user has typed again is ignored.
//
// Session tokens: one per search session, sent with every suggestion request
// and with the confirming lookup, then rotated (see backend autocomplete.py
// for what Google does and does not discount).

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { ApiError, messageFor } from "@/lib/v2/client.ts";
import { SuggestionSearch, type SearchState } from "@/lib/v2/search.ts";
import type { VSuggestion, VSuggestions } from "@/lib/v2/validate.ts";

export function newSessionToken(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `s${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.kind === "rate_limited") {
      return error.retryAfterSeconds
        ? `Too many searches. Try again in about ${Math.ceil(error.retryAfterSeconds / 60)} min.`
        : "Too many searches. Wait a little and try again.";
    }
    return error.message;
  }
  return messageFor("unexpected");
}

interface Props<T> {
  label: string;
  placeholder: string;
  query: string;
  selected: boolean;
  context: string; // search context (e.g. selected city ID); changing it invalidates results
  disabled?: boolean;
  invalid?: boolean;
  describedBy?: string;
  fetchSuggestions: (query: string, sessionToken: string, signal: AbortSignal) => Promise<VSuggestions>;
  confirm: (placeId: string, sessionToken: string, signal: AbortSignal) => Promise<T>;
  onQueryChange: (query: string) => void;
  onSelected: (value: T, suggestion: VSuggestion) => void;
  testId?: string;
}

export default function SearchSelect<T>({
  label,
  placeholder,
  query,
  selected,
  context,
  disabled,
  invalid,
  describedBy,
  fetchSuggestions,
  confirm,
  onQueryChange,
  onSelected,
  testId,
}: Props<T>) {
  const listId = useId();
  const statusId = useId();
  const [state, setState] = useState<SearchState>({ kind: "idle" });
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const tokenRef = useRef<string>(newSessionToken());
  const editSeq = useRef(0);
  const confirmController = useRef<AbortController | null>(null);
  const fetchRef = useRef(fetchSuggestions);
  fetchRef.current = fetchSuggestions;

  const search = useMemo(
    () =>
      new SuggestionSearch({
        setTimer: (fn, ms) => window.setTimeout(fn, ms),
        clearTimer: (h) => window.clearTimeout(h as number),
        fetch: (q, _ctx, signal) => fetchRef.current(q, tokenRef.current, signal),
        onState: (s) => {
          setState(s);
          setActive(0);
          if (s.kind === "results" || s.kind === "error") setOpen(true);
        },
      }),
    [],
  );

  useEffect(() => () => {
    search.cancel();
    confirmController.current?.abort();
  }, [search]);

  // A new search context (e.g. a different city) makes old suggestions stale:
  // drop them and, if the user has unconfirmed text, search again in the new
  // context (debounced as usual) rather than silently dropping their search.
  const latest = useRef({ query, selected });
  latest.current = { query, selected };
  const firstContext = useRef(true);
  useEffect(() => {
    if (firstContext.current) {
      firstContext.current = false;
      return;
    }
    search.cancel();
    setOpen(false);
    if (!latest.current.selected) search.input(latest.current.query, context);
  }, [context, search]);

  function handleChange(value: string) {
    editSeq.current += 1;
    confirmController.current?.abort();
    setConfirming(null);
    setConfirmError(null);
    onQueryChange(value);
    search.input(value, context);
  }

  async function choose(s: VSuggestion) {
    const seq = editSeq.current;
    confirmController.current?.abort();
    const controller = new AbortController();
    confirmController.current = controller;
    setOpen(false);
    setConfirming(s.primary_text);
    setConfirmError(null);
    search.cancel();
    try {
      const value = await confirm(s.place_id, tokenRef.current, controller.signal);
      if (seq !== editSeq.current || controller.signal.aborted) return; // edited meanwhile
      tokenRef.current = newSessionToken(); // session concluded
      onSelected(value, s);
    } catch (err) {
      if (controller.signal.aborted || seq !== editSeq.current) return;
      setConfirmError(errorText(err));
    } finally {
      if (seq === editSeq.current) setConfirming(null);
    }
  }

  const items = state.kind === "results" ? state.result.suggestions : [];
  const showList = open && !disabled && (state.kind === "results" || state.kind === "error");

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown" && items.length) {
      e.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(items.length - 1, i + 1));
    } else if (e.key === "ArrowUp" && items.length) {
      e.preventDefault();
      setActive((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault(); // never submit the form from a search box
      if (showList && items[active]) void choose(items[active]);
      else search.searchNow(query, context);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  let status: string | null = null;
  if (confirming) status = `Confirming ${confirming}…`;
  else if (confirmError) status = confirmError;
  else if (state.kind === "loading") status = "Searching…";
  else if (state.kind === "results" && state.result.status === "no_matches") status = "No matches. Try different words.";
  else if (state.kind === "error") status = errorText(state.error);

  const isError = Boolean(confirmError) || state.kind === "error";

  return (
    <div className="relative min-w-0 flex-1" data-testid={testId}>
      <div className="flex items-center gap-1">
        <div className="relative min-w-0 flex-1">
          <input
            type="text"
            role="combobox"
            aria-label={label}
            aria-expanded={showList}
            aria-controls={listId}
            aria-autocomplete="list"
            aria-invalid={invalid || undefined}
            aria-describedby={[statusId, describedBy].filter(Boolean).join(" ")}
            aria-activedescendant={showList && items[active] ? `${listId}-${active}` : undefined}
            placeholder={placeholder}
            value={query}
            disabled={disabled}
            onChange={(e) => handleChange(e.target.value)}
            onKeyDown={onKeyDown}
            onFocus={() => state.kind === "results" && setOpen(true)}
            onBlur={() => window.setTimeout(() => setOpen(false), 150)}
            className={`input-base pr-7 ${invalid ? "border-error-border" : ""}`}
            style={{ textOverflow: "ellipsis" }}
          />
          {selected && (
            <span
              className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-xs text-accent"
              aria-label="Selected"
              title="Selected"
            >
              ✓
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => search.searchNow(query, context)}
          disabled={disabled || !query.trim()}
          className="flex-shrink-0 rounded-md border border-border-default p-2 text-text-secondary transition-colors hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-40"
          aria-label={`Search ${label}`}
          title="Search now"
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden="true">
            <circle cx="7" cy="7" r="4.5" />
            <path d="M10.5 10.5 14 14" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      <p
        id={statusId}
        role="status"
        aria-live="polite"
        className={`mt-1 min-h-0 text-xs ${isError ? "text-error-text" : "text-text-muted"} ${status ? "" : "sr-only"}`}
      >
        {status ?? ""}
      </p>
      {!selected && query.trim() && !status && !showList && (
        <p className="mt-1 text-xs text-text-muted">Choose a suggestion to confirm this place.</p>
      )}

      {showList && items.length > 0 && (
        <ul
          id={listId}
          role="listbox"
          aria-label={`${label} suggestions`}
          className="absolute left-0 right-0 z-30 mt-1 max-h-64 overflow-y-auto rounded-md border border-border-default bg-pane-bg py-1 shadow-floating"
        >
          {items.map((s, i) => (
            <li
              key={s.place_id}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => void choose(s)}
              onMouseEnter={() => setActive(i)}
              className={`cursor-pointer px-3 py-2 text-sm ${i === active ? "bg-accent-soft" : ""}`}
            >
              <span className="block text-text-primary">{s.primary_text}</span>
              {s.secondary_text && <span className="block text-xs text-text-muted">{s.secondary_text}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
