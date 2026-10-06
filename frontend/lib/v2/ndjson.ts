// Bounded NDJSON reader for POST /api/v2/plan/stream.
//
// The response body is newline-delimited JSON: one StreamEvent per line. This
// reader is deliberately strict:
// - each line is size-limited and the event count is capped;
// - every event is runtime-validated (validate.ts);
// - every event must belong to the operation/revision that was requested;
// - the first event must be operation_start, and exactly one terminal event
//   ends the stream; anything after it is ignored.
// If the body ends without a terminal event (connection dropped, proxy
// truncation) or anything is malformed, the result is "incomplete" — never a
// success. There is no automatic reconnection: retrying is the user's choice.

import { ValidationError, streamEvent, type StreamKind, type VStreamEvent } from "./validate.ts";

export const MAX_LINE_CHARS = 512 * 1024;
export const MAX_EVENTS = 400;

export type IncompleteReason =
  | "truncated"
  | "malformed"
  | "oversized"
  | "too_many_events"
  | "wrong_operation"
  | "out_of_order"
  | "network";

export type StreamEnd =
  | { kind: "terminal"; event: Extract<VStreamEvent, { type: "terminal" }> }
  | { kind: "incomplete"; reason: IncompleteReason }
  | { kind: "aborted" };

export interface StreamIdentity {
  operationId: string;
  inputRevision: number;
  /** Which operation the stream belongs to (default "plan"). */
  kind?: StreamKind;
}

function isAbort(err: unknown): boolean {
  return typeof err === "object" && err !== null && (err as { name?: string }).name === "AbortError";
}

export async function readPlanStream(
  body: ReadableStream<Uint8Array>,
  identity: StreamIdentity,
  onEvent: (event: VStreamEvent) => void,
  signal?: AbortSignal,
): Promise<StreamEnd> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let count = 0;
  let started = false;

  const finish = async (end: StreamEnd): Promise<StreamEnd> => {
    try {
      await reader.cancel();
    } catch {
      // already closed
    }
    return end;
  };

  // Returns a StreamEnd to stop, or null to keep reading.
  const handleLine = (line: string): StreamEnd | null => {
    if (!line.trim()) return null;
    if (line.length > MAX_LINE_CHARS) return { kind: "incomplete", reason: "oversized" };
    count += 1;
    if (count > MAX_EVENTS) return { kind: "incomplete", reason: "too_many_events" };
    let event: VStreamEvent;
    try {
      event = streamEvent(JSON.parse(line), "event", identity.kind ?? "plan");
    } catch (err) {
      if (err instanceof SyntaxError || err instanceof ValidationError) {
        return { kind: "incomplete", reason: "malformed" };
      }
      throw err;
    }
    if (event.operation_id !== identity.operationId || event.input_revision !== identity.inputRevision) {
      return { kind: "incomplete", reason: "wrong_operation" };
    }
    if (!started && event.type !== "operation_start") {
      return { kind: "incomplete", reason: "out_of_order" };
    }
    started = true;
    if (event.type === "terminal") return { kind: "terminal", event };
    onEvent(event);
    return null;
  };

  try {
    for (;;) {
      if (signal?.aborted) return finish({ kind: "aborted" });
      const { done, value } = await reader.read();
      if (done) {
        buffer += decoder.decode();
        const tail = handleLine(buffer);
        if (tail) return finish(tail);
        return { kind: "incomplete", reason: "truncated" };
      }
      buffer += decoder.decode(value, { stream: true });
      let newline = buffer.indexOf("\n");
      while (newline !== -1) {
        const line = buffer.slice(0, newline);
        buffer = buffer.slice(newline + 1);
        const end = handleLine(line);
        if (end) return finish(end);
        newline = buffer.indexOf("\n");
      }
      if (buffer.length > MAX_LINE_CHARS) return finish({ kind: "incomplete", reason: "oversized" });
    }
  } catch (err) {
    if (isAbort(err) || signal?.aborted) return { kind: "aborted" };
    return { kind: "incomplete", reason: "network" };
  }
}
