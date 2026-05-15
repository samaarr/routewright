/**
 * Extract HH:MM from an ISO 8601 string without timezone conversion.
 * Slices directly rather than using `new Date()` so the displayed time
 * always matches the planned city time, regardless of the user's browser
 * timezone.
 */
export function fmtTime(iso: string): string {
  return iso.slice(11, 16);
}

export function fmtDuration(seconds: number): string {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h} hr` : `${h} hr ${m} min`;
}
