import type { LegItem } from "@/lib/types";

interface Props {
  leg: LegItem;
  isFirstLeg: boolean;
  isDegraded: boolean;
}

export default function LegCard({ leg, isFirstLeg, isDegraded }: Props) {
  return (
    <div className="py-1 pl-16">
      <div className="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
        <span className="text-zinc-400">↓</span>
        <span className={`text-sm ${isDegraded ? "text-amber-700" : "text-zinc-600"}`}>
          {isDegraded && "⚠ "}
          {leg.summary}
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
