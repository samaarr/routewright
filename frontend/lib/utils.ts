// Render an ISO 8601 UTC string as HH:MM.
// When tz is provided (IANA zone from plan.timezone) times display in the
// destination's local zone — a Tokyo trip from Dublin shows JST, not IST.
// Falls back to browser local when tz is omitted.
export function fmtTime(iso: string, tz?: string): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    ...(tz ? { timeZone: tz } : {}),
  });
}

export function fmtDuration(seconds: number): string {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h} hr` : `${h} hr ${m} min`;
}
