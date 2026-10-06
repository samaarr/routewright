// Shared builders for unit tests: shapes mirror the backend's JSON output.
export const OP = "op-1";
export const REV = 4;

export function stop(id: string, extra: Record<string, unknown> = {}) {
  return {
    item_type: "stop",
    instance_id: id,
    place_id: `P_${id}`,
    name: `Stop ${id}`,
    address: null,
    lat: 53.34,
    lng: -6.26,
    arrive_at: "2026-10-21T09:00:00Z",
    depart_at: "2026-10-21T10:00:00Z",
    stay_minutes: 60,
    stay_source: "default",
    map_url: "https://www.google.com/maps/search/?api=1&query=1,1",
    hours_status: "open",
    hours_detail: { closes_at: "17:00", hours_source: "weekly", exceptions_unconfirmed: true },
    ...extra,
  };
}

export function leg(from: string, to: string) {
  return {
    item_type: "leg",
    from_stop_id: from,
    to_stop_id: to,
    from_name: `Stop ${from}`,
    to_name: `Stop ${to}`,
    mode: "transit",
    duration_seconds: 1200,
    journey_seconds: 1200,
    distance_meters: 1000,
    depart_at: "2026-10-21T10:00:00Z",
    arrive_at: "2026-10-21T10:20:00Z",
    summary: "Bus 15, 20 min",
    map_url: "https://www.google.com/maps/dir/?api=1",
  };
}

export function plan(kind: "complete" | "partial" = "complete", extra: Record<string, unknown> = {}) {
  const base = {
    result_type: kind,
    operation_id: OP,
    input_revision: REV,
    city: "Dublin",
    mode: "transit",
    timezone: "Europe/Dublin",
    timeline:
      kind === "complete"
        ? [stop("a"), leg("a", "b"), stop("b")]
        : [
            stop("a"),
            { item_type: "failed_leg", from_stop_id: "a", to_stop_id: "b", from_name: "A", to_name: "B", failure_reason: "no_route", failure_message: "No transit route found." },
            { item_type: "unknown_stop", instance_id: "b", place_id: "P_b", name: "Stop b" },
          ],
    overview_map_url: "https://www.google.com/maps/dir/?api=1",
    warnings: [],
  };
  return kind === "partial" ? { ...base, failed_at_leg_index: 0, failure_reason: "no_route", ...extra } : { ...base, ...extra };
}

export function ev(type: string, extra: Record<string, unknown> = {}, op = OP, rev = REV) {
  return { operation_id: op, input_revision: rev, type, ...extra };
}

export const START = ev("operation_start", { phases: ["verification", "routing"] });
export const TERMINAL_OK = ev("terminal", { outcome: { outcome_type: "plan", result: plan() } });

export function ndjsonStream(chunks: (string | Uint8Array)[], { close = true } = {}): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(typeof c === "string" ? enc.encode(c) : c);
      if (close) controller.close();
    },
  });
}

export const line = (o: unknown) => JSON.stringify(o) + "\n";
