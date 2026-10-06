// HTTP client for the v2 selection and planning endpoints.
//
// All responses are runtime-validated. Errors are classified so the UI can
// tell "no matches" (a successful, empty search) apart from invalid input,
// the per-IP search limit, the shared provider allowance, unavailable usage
// control, a busy server, provider failure and network problems.

import { readPlanStream, type StreamEnd } from "./ndjson.ts";
import {
  selectedCity,
  selectedPlace,
  suggestions,
  type VSelectedCity,
  type VSelectedPlace,
  type VStreamEvent,
  type VSuggestions,
  type VViewport,
} from "./validate.ts";

export type ApiErrorKind =
  | "invalid_input"
  | "rate_limited"
  | "quota_exceeded"
  | "usage_control"
  | "busy"
  | "provider_unavailable"
  | "place_invalid"
  | "timezone"
  | "departure"
  | "network"
  | "unexpected";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly code: string;
  readonly retryAfterSeconds: number | null;
  readonly details: Record<string, unknown> | null;

  constructor(
    kind: ApiErrorKind,
    code: string,
    message: string,
    retryAfterSeconds: number | null = null,
    details: Record<string, unknown> | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.code = code;
    this.retryAfterSeconds = retryAfterSeconds;
    this.details = details;
  }
}

const KIND_BY_CODE: Record<string, ApiErrorKind> = {
  rate_limit_exceeded: "rate_limited",
  quota_exceeded: "quota_exceeded",
  usage_control_unavailable: "usage_control",
  provider_capacity: "busy",
  capacity_exceeded: "busy",
  provider_unavailable: "provider_unavailable",
  place_temporary: "provider_unavailable",
  service_unavailable: "provider_unavailable",
  place_invalid: "place_invalid",
  timezone_unresolved: "timezone",
  timezone_conflict: "timezone",
  departure_timezone_mismatch: "timezone",
  validation_error: "invalid_input",
  invalid_query: "invalid_input",
  duplicate_instance_id: "invalid_input",
  request_too_large: "invalid_input",
};

const DEFAULT_MESSAGES: Record<ApiErrorKind, string> = {
  invalid_input: "Check the highlighted fields and try again.",
  rate_limited: "You've made a lot of requests. Wait a little and try again.",
  quota_exceeded: "Today's search and planning allowance has been used up. Try again tomorrow.",
  usage_control: "Usage checks are unavailable right now, so nothing was sent. Try again shortly.",
  busy: "The service is busy. Try again in a moment.",
  provider_unavailable: "Google's place service didn't respond. Try again shortly.",
  place_invalid: "A selected place could not be confirmed. Please select it again.",
  timezone: "The trip's timezone could not be confirmed.",
  departure: "Check the departure date and time.",
  network: "Couldn't reach RouteWright. Check your connection and try again.",
  unexpected: "Something went wrong. Try again.",
};

// In dev, NEXT_PUBLIC_API_URL is unset and requests use the Next.js rewrite
// proxy (/api/* → http://localhost:8000/api/*).
const BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

function isAbort(err: unknown): boolean {
  return typeof err === "object" && err !== null && (err as { name?: string }).name === "AbortError";
}

async function errorFrom(res: Response): Promise<ApiError> {
  const retry = Number(res.headers.get("retry-after"));
  const retryAfter = Number.isFinite(retry) && retry > 0 ? retry : null;
  let code = `http_${res.status}`;
  let message: string | null = null;
  let details: Record<string, unknown> | null = null;
  try {
    const body = (await res.json()) as Record<string, unknown>;
    const detail = body.detail;
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      details = detail as Record<string, unknown>;
      if (typeof details.error === "string") code = details.error;
      if (typeof details.message === "string") message = details.message;
    } else if (typeof body.error === "string") {
      code = body.error;
    }
  } catch {
    // non-JSON error body
  }
  let kind: ApiErrorKind = KIND_BY_CODE[code] ?? (code.startsWith("departure_") ? "departure" : "unexpected");
  if (kind === "unexpected" && res.status === 429) kind = "rate_limited";
  if (kind === "unexpected" && res.status === 422) kind = "invalid_input";
  return new ApiError(kind, code, message ?? DEFAULT_MESSAGES[kind], retryAfter, details);
}

async function postJson(path: string, body: unknown, signal?: AbortSignal): Promise<unknown> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (isAbort(err)) throw err;
    throw new ApiError("network", "network", DEFAULT_MESSAGES.network);
  }
  if (!res.ok) throw await errorFrom(res);
  try {
    return await res.json();
  } catch (err) {
    if (isAbort(err)) throw err;
    throw new ApiError("unexpected", "malformed_response", DEFAULT_MESSAGES.unexpected);
  }
}

function validated<T>(parse: (v: unknown) => T, value: unknown): T {
  try {
    return parse(value);
  } catch {
    throw new ApiError("unexpected", "malformed_response", DEFAULT_MESSAGES.unexpected);
  }
}

export function messageFor(kind: ApiErrorKind): string {
  return DEFAULT_MESSAGES[kind];
}

export async function suggestCities(query: string, sessionToken: string, signal?: AbortSignal): Promise<VSuggestions> {
  const body = await postJson("/api/v2/suggest/cities", { query, session_token: sessionToken }, signal);
  return validated(suggestions, body);
}

export async function suggestPlaces(
  query: string,
  sessionToken: string,
  cityViewport: VViewport | null,
  signal?: AbortSignal,
): Promise<VSuggestions> {
  const body = await postJson(
    "/api/v2/suggest/places",
    { query, session_token: sessionToken, ...(cityViewport ? { city_viewport: cityViewport } : {}) },
    signal,
  );
  return validated(suggestions, body);
}

export async function selectCity(placeId: string, sessionToken: string | null, signal?: AbortSignal): Promise<VSelectedCity> {
  const body = await postJson(
    "/api/v2/select/city",
    { place_id: placeId, ...(sessionToken ? { session_token: sessionToken } : {}) },
    signal,
  );
  return validated(selectedCity, body);
}

export async function selectPlace(placeId: string, sessionToken: string | null, signal?: AbortSignal): Promise<VSelectedPlace> {
  const body = await postJson(
    "/api/v2/select/place",
    { place_id: placeId, ...(sessionToken ? { session_token: sessionToken } : {}) },
    signal,
  );
  return validated(selectedPlace, body);
}

export interface PlanStreamRequest {
  operation_id: string;
  input_revision: number;
  city: { place_id: string; name: string; lat: number; lng: number };
  stops: {
    instance_id: string;
    selection: { place_id: string; name: string; lat: number; lng: number };
    stay_minutes?: number;
  }[];
  departure: { local_date: string; local_time: string; timezone: string; occurrence?: 1 | 2 };
  mode: "transit" | "walking" | "driving";
}

/**
 * Start one streamed plan. Resolves when the stream ends (terminal, incomplete
 * or aborted). Throws ApiError for HTTP errors returned before streaming.
 */
export async function streamPlan(
  request: PlanStreamRequest,
  onEvent: (event: VStreamEvent) => void,
  signal: AbortSignal,
): Promise<StreamEnd> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/api/v2/plan/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
      body: JSON.stringify(request),
      signal,
    });
  } catch (err) {
    if (isAbort(err)) return { kind: "aborted" };
    throw new ApiError("network", "network", DEFAULT_MESSAGES.network);
  }
  if (!res.ok) throw await errorFrom(res);
  if (!res.body || !(res.headers.get("content-type") ?? "").includes("application/x-ndjson")) {
    return { kind: "incomplete", reason: "malformed" };
  }
  return readPlanStream(
    res.body,
    { operationId: request.operation_id, inputRevision: request.input_revision },
    onEvent,
    signal,
  );
}
