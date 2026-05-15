// Fixture response used during Day 9 development.
// Exercises all visual states: normal leg, degraded leg, warning badge,
// user-overridden stay vs default stay.
// Remove once PlannerPage wires the real API (Day 10).

import type { Plan } from "./types";

export const FIXTURE_PLAN: Plan = {
  generated_at: "2026-06-01T10:00:00Z",
  city: "Dublin, Ireland",
  mode: "transit",
  timeline: [
    {
      item_type: "stop",
      query: "Trinity College",
      name: "Trinity College Dublin",
      address: null,
      lat: 53.3440,
      lng: -6.2546,
      arrive_at: "2026-06-01T10:00:00Z",
      depart_at: "2026-06-01T11:00:00Z",
      stay_minutes: 60,
      stay_source: "default",
      map_url: "https://www.google.com/maps/search/?api=1&query=Trinity+College+Dublin",
    },
    {
      item_type: "leg",
      from_name: "Trinity College Dublin",
      to_name: "The Temple Bar Pub",
      mode: "transit",
      duration_seconds: 1080,
      distance_meters: 1200,
      depart_at: "2026-06-01T11:00:00Z",
      arrive_at: "2026-06-01T11:18:00Z",
      summary: "Take the 13, 18 min",
      map_url: "https://www.google.com/maps/dir/?api=1&origin=Trinity+College&destination=Temple+Bar&travelmode=transit",
    },
    {
      item_type: "stop",
      query: "Temple Bar",
      name: "The Temple Bar Pub",
      address: null,
      lat: 53.3454,
      lng: -6.2672,
      arrive_at: "2026-06-01T11:18:00Z",
      depart_at: "2026-06-01T13:48:00Z",
      stay_minutes: 150,
      stay_source: "user",
      map_url: "https://www.google.com/maps/search/?api=1&query=Temple+Bar+Dublin",
    },
    {
      item_type: "leg",
      from_name: "The Temple Bar Pub",
      to_name: "Guinness Storehouse",
      mode: "transit",
      duration_seconds: 900,
      distance_meters: 2100,
      depart_at: "2026-06-01T13:48:00Z",
      arrive_at: "2026-06-01T14:03:00Z",
      summary: "Route unavailable — check Google Maps",
      map_url: "https://www.google.com/maps/dir/?api=1&origin=Temple+Bar&destination=Guinness+Storehouse&travelmode=transit",
    },
    {
      item_type: "stop",
      query: "Guinness Storehouse",
      name: "Guinness Storehouse",
      address: null,
      lat: 53.3418,
      lng: -6.2867,
      arrive_at: "2026-06-01T14:03:00Z",
      depart_at: "2026-06-01T15:33:00Z",
      stay_minutes: 90,
      stay_source: "default",
      map_url: "https://www.google.com/maps/search/?api=1&query=Guinness+Storehouse+Dublin",
    },
  ],
  overview_map_url:
    "https://www.google.com/maps/dir/?api=1&origin=Trinity+College&destination=Guinness+Storehouse&travelmode=driving&waypoints=Temple+Bar",
  warnings: [
    {
      severity: "warning",
      message:
        "Could not fetch route: The Temple Bar Pub → Guinness Storehouse. Showing estimated time.",
      affects_stop_index: 1,
    },
  ],
};
