// Debounced suggestion search for one input (D35).
//
// - Typing schedules a search after a 300 ms pause; each keystroke resets the
//   timer. Automatic searches need at least two characters after whitespace
//   normalisation.
// - searchNow() (the explicit Search button) runs immediately for any
//   nonblank text, including one character.
// - A new search aborts the in-flight one; responses whose query/context no
//   longer match are ignored, so old suggestions never populate a new search.
// - The same query + context is not requested twice concurrently or again
//   while its results are showing.
// Cancelling a pending timer costs nothing; a request already sent remains
// counted by the server even if its response is ignored.

import type { VSuggestions } from "./validate.ts";

export const DEBOUNCE_MS = 300;
export const AUTO_MIN_CHARS = 2;

export type SearchState =
  | { kind: "idle" }
  | { kind: "waiting" }
  | { kind: "loading"; query: string }
  | { kind: "results"; query: string; result: VSuggestions }
  | { kind: "error"; query: string; error: unknown };

export interface SearchDeps {
  setTimer: (fn: () => void, ms: number) => unknown;
  clearTimer: (handle: unknown) => void;
  fetch: (query: string, context: string, signal: AbortSignal) => Promise<VSuggestions>;
  onState: (state: SearchState) => void;
}

export function normaliseQuery(q: string): string {
  return q.split(/\s+/).filter(Boolean).join(" ");
}

export class SuggestionSearch {
  private deps: SearchDeps;
  private timer: unknown = null;
  private controller: AbortController | null = null;
  private seq = 0;
  private active: { key: string; settled: boolean } | null = null;

  constructor(deps: SearchDeps) {
    this.deps = deps;
  }

  /** Typing. Resets the timer; schedules an automatic search if long enough. */
  input(query: string, context: string): void {
    this.clearTimer();
    const q = normaliseQuery(query);
    if (q.length < AUTO_MIN_CHARS) {
      this.abort();
      this.deps.onState({ kind: "idle" });
      return;
    }
    if (this.active?.key === `${context}\u0000${q}`) return; // already fetched/fetching
    this.deps.onState({ kind: "waiting" });
    this.timer = this.deps.setTimer(() => {
      this.timer = null;
      this.run(q, context);
    }, DEBOUNCE_MS);
  }

  /** Explicit Search action: any nonblank text, immediately. */
  searchNow(query: string, context: string): void {
    this.clearTimer();
    const q = normaliseQuery(query);
    if (!q) return;
    if (this.active?.key === `${context}\u0000${q}` && !this.active.settled) return;
    this.run(q, context);
  }

  /** Stop everything (selection made, input cleared, component unmounted). */
  cancel(): void {
    this.clearTimer();
    this.abort();
    this.active = null;
    this.deps.onState({ kind: "idle" });
  }

  private clearTimer(): void {
    if (this.timer !== null) {
      this.deps.clearTimer(this.timer);
      this.timer = null;
    }
  }

  private abort(): void {
    this.controller?.abort();
    this.controller = null;
    this.seq += 1;
    this.active = null;
  }

  private run(q: string, context: string): void {
    this.abort();
    const seq = this.seq;
    const controller = new AbortController();
    this.controller = controller;
    const key = `${context}\u0000${q}`;
    this.active = { key, settled: false };
    this.deps.onState({ kind: "loading", query: q });
    this.deps.fetch(q, context, controller.signal).then(
      (result) => {
        if (seq !== this.seq) return; // superseded
        if (this.active) this.active.settled = true;
        this.deps.onState({ kind: "results", query: q, result });
      },
      (error) => {
        if (seq !== this.seq || controller.signal.aborted) return;
        this.active = null; // allow a retry of the same query
        this.deps.onState({ kind: "error", query: q, error });
      },
    );
  }
}
