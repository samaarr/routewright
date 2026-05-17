import type { LegItem } from "@/lib/types";
import { fmtTime, fmtDuration } from "@/lib/utils";

// "Take the H2, 11 min" → "Take the H2, 12:36 → 12:47 (11 min)"
// Fallback for non-standard summaries: "8 min (transit) — 12:36 → 12:44"
function formatLegSummary(leg: LegItem): string {
  const depart = fmtTime(leg.depart_at);
  const arrive = fmtTime(leg.arrive_at);
  const duration = fmtDuration(leg.duration_seconds);
  const match = leg.summary.match(/^(.+?),\s*\d+\s*min$/);
  if (match) {
    return `${match[1]}, ${depart} → ${arrive} (${duration})`;
  }
  return `${leg.summary} — ${depart} → ${arrive}`;
}

function RefreshIcon({ spinning }: { spinning: boolean }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      aria-hidden="true"
      className={`h-3.5 w-3.5 ${spinning ? "animate-spin" : ""}`}
    >
      <path d="M13.5 8a5.5 5.5 0 1 1-1.39-3.65" />
      <polyline points="13.5 2 13.5 5.5 10 5.5" />
    </svg>
  );
}

interface Props {
  leg: LegItem;
  isFirstLeg: boolean;
  isDegraded: boolean;
  legTimelineIndex: number;
  onRefresh: (legTimelineIndex: number) => void;
  isRefreshing: boolean;
}

export default function LegCard({
  leg,
  isFirstLeg,
  isDegraded,
  legTimelineIndex,
  onRefresh,
  isRefreshing,
}: Props) {
  return (
    <div className="py-1 pl-20">
      <div className="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
        <span className="text-zinc-400">↓</span>
        <span className={`text-sm ${isDegraded ? "text-amber-700" : "text-zinc-600"}`}>
          {isDegraded && "⚠ "}
          {formatLegSummary(leg)}
        </span>
        <span className="text-zinc-300">·</span>
        <a
          href={leg.map_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm text-blue-600 underline underline-offset-2 hover:text-blue-800"
        >
          Get directions ↗
        </a>
        <button
          type="button"
          onClick={() => onRefresh(legTimelineIndex)}
          disabled={isRefreshing}
          aria-label="Refresh this leg with current transit times"
          className="-m-2 p-2 text-zinc-400 hover:text-zinc-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshIcon spinning={isRefreshing} />
        </button>
      </div>

      {isDegraded && (
        <p className="mt-0.5 text-xs text-amber-600">
          Schedule unavailable — estimated time shown.
        </p>
      )}

      {/* Caption only on first leg — teaches the live-times model once */}
      {isFirstLeg && (
        <p className="mt-0.5 text-xs text-zinc-400">
          Tap when you&apos;re heading out — live times open in Google Maps.
        </p>
      )}
    </div>
  );
}
