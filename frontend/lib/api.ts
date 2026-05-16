import type { LegItem, Plan, PlanRequest, TransportMode } from "./types";

export interface RefreshLegRequest {
  from_lat: number;
  from_lng: number;
  from_name: string;
  to_lat: number;
  to_lng: number;
  to_name: string;
  mode: TransportMode;
  city: string;
}

// In dev, NEXT_PUBLIC_API_URL is unset and requests hit the Next.js rewrite
// proxy (/api/* → http://localhost:8000/api/*).
// In production, set NEXT_PUBLIC_API_URL to the Railway backend URL.
const BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

export async function postPlan(req: PlanRequest): Promise<Plan> {
  const res = await fetch(`${BASE}/api/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    // Surface the backend's detail message verbatim so users can fix bad stops.
    // e.g. 400: "Could not geocode stop: 'Nonexistent Place'"
    const body = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(body.detail ?? `Request failed (${res.status})`);
  }

  return res.json() as Promise<Plan>;
}

export async function postRefreshLeg(req: RefreshLegRequest): Promise<LegItem> {
  const res = await fetch(`${BASE}/api/refresh-leg`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(body.detail ?? `Refresh failed (${res.status})`);
  }

  return res.json() as Promise<LegItem>;
}
