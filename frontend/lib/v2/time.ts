// Destination-local departure analysis (D14, D28, D29).
//
// Uses Intl with the trip city's IANA zone — never the device timezone — to
// find every UTC instant at which the entered wall-clock time occurs:
//   0 instants → the clock skips that time (nonexistent; choose another);
//   1 instant  → ordinary time;
//   2 instants → repeated hour after clocks go back; the user must choose the
//                first (earlier) or second (later) occurrence, shown with its
//                UTC offset. "Standard"/"summer" labels are avoided because
//                they differ by location.
// The server re-validates everything; this only drives the form UX.

export interface Occurrence {
  occurrence: 1 | 2;
  utcMs: number;
  offsetLabel: string; // e.g. "UTC+01:00"
}

export type DepartureCheck =
  | { kind: "incomplete" }
  | { kind: "invalid" }
  | { kind: "nonexistent" }
  | { kind: "ok"; utcMs: number; offsetLabel: string }
  | { kind: "ambiguous"; options: [Occurrence, Occurrence] };

const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const TIME_RE = /^([01]\d|2[0-3]):([0-5]\d)$/;
const formatters = new Map<string, Intl.DateTimeFormat>();

function formatter(tz: string): Intl.DateTimeFormat {
  let f = formatters.get(tz);
  if (!f) {
    f = new Intl.DateTimeFormat("en-GB", {
      timeZone: tz,
      hourCycle: "h23",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    formatters.set(tz, f);
  }
  return f;
}

/** Offset of ``tz`` from UTC at instant ``ms``, in minutes. */
export function offsetMinutes(tz: string, ms: number): number {
  const parts: Record<string, number> = {};
  for (const p of formatter(tz).formatToParts(new Date(ms))) {
    if (p.type !== "literal") parts[p.type] = Number(p.value);
  }
  const asUtc = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second);
  return Math.round((asUtc - Math.floor(ms / 1000) * 1000) / 60000);
}

export function offsetLabel(minutes: number): string {
  const sign = minutes < 0 ? "-" : "+";
  const abs = Math.abs(minutes);
  return `UTC${sign}${String(Math.floor(abs / 60)).padStart(2, "0")}:${String(abs % 60).padStart(2, "0")}`;
}

export function isValidZone(tz: string): boolean {
  try {
    formatter(tz);
    return true;
  } catch {
    return false;
  }
}

export function checkDeparture(date: string, time: string, tz: string | null): DepartureCheck {
  if (!date || !time || !tz) return { kind: "incomplete" };
  const d = DATE_RE.exec(date);
  const t = TIME_RE.exec(time);
  if (!d || !t || !isValidZone(tz)) return { kind: "invalid" };
  const [y, mo, da] = [Number(d[1]), Number(d[2]), Number(d[3])];
  const wall = Date.UTC(y, mo - 1, da, Number(t[1]), Number(t[2]));
  const check = new Date(wall);
  if (check.getUTCFullYear() !== y || check.getUTCMonth() !== mo - 1 || check.getUTCDate() !== da) {
    return { kind: "invalid" };
  }
  const day = 86_400_000;
  const offsets = new Set([offsetMinutes(tz, wall - day), offsetMinutes(tz, wall), offsetMinutes(tz, wall + day)]);
  const instants = [...offsets]
    .map((o) => ({ utcMs: wall - o * 60_000, o }))
    .filter(({ utcMs, o }) => offsetMinutes(tz, utcMs) === o)
    .sort((a, b) => a.utcMs - b.utcMs)
    .filter((x, i, all) => i === 0 || x.utcMs !== all[i - 1].utcMs);
  if (instants.length === 0) return { kind: "nonexistent" };
  if (instants.length === 1) return { kind: "ok", utcMs: instants[0].utcMs, offsetLabel: offsetLabel(instants[0].o) };
  const [a, b] = instants;
  return {
    kind: "ambiguous",
    options: [
      { occurrence: 1, utcMs: a.utcMs, offsetLabel: offsetLabel(a.o) },
      { occurrence: 2, utcMs: b.utcMs, offsetLabel: offsetLabel(b.o) },
    ],
  };
}
