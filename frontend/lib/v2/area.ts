// Outside-area preview against the selected city's viewport (D25, D44).
// Mirrors backend app/services/area.py. The viewport is Google's suggested
// framing for the city, not an administrative boundary; outside stops are
// allowed. Boundary points count as inside; low_lng > high_lng means the
// viewport crosses the antimeridian.

import type { VViewport } from "./validate.ts";

export type AreaStatus = "inside" | "outside" | "unavailable";

export const OUTSIDE_AREA_MESSAGE = "Outside the selected city's suggested area.";
export const AREA_UNAVAILABLE_MESSAGE =
  "The suggested-area check is unavailable for this city.";

export function areaStatus(viewport: VViewport | null, lat: number, lng: number): AreaStatus {
  if (!viewport) return "unavailable";
  if (lat < viewport.low_lat || lat > viewport.high_lat) return "outside";
  const inside =
    viewport.low_lng <= viewport.high_lng
      ? lng >= viewport.low_lng && lng <= viewport.high_lng
      : lng >= viewport.low_lng || lng <= viewport.high_lng;
  return inside ? "inside" : "outside";
}
