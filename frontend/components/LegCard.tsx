import type { LegItem } from "@/lib/types";
import WarningBadge from "./WarningBadge";

interface Props {
  leg: LegItem;
  isFirstLeg: boolean;
  isDegraded: boolean;
}

export default function LegCard({ leg, isFirstLeg, isDegraded }: Props) {
  return (
    <div className="flex items-start gap-3">
      {/* Connecting line segment — aligns with the stop dots */}
      <div className="flex w-3 flex-shrink-0 justify-center">
        <div
          className={`w-px flex-1 ${isDegraded ? "bg-amber-300" : "bg-zinc-200"}`}
        />
      </div>

      <div
        className={`mb-1 min-w-0 flex-1 rounded-md px-3 py-2 ${
          isDegraded ? "border border-amber-200 bg-amber-50" : "bg-zinc-100"
        }`}
      >
        {isDegraded && (
          <div className="mb-1.5">
            <WarningBadge />
          </div>
        )}

        {/* Summary verbatim from the API — no parsing or augmentation */}
        <p className="text-sm text-zinc-600">{leg.summary}</p>

        {/* Button is small and secondary — hierarchy signals times are the plan */}
        <a
          href={leg.map_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1.5 inline-block text-sm font-medium text-blue-600 underline underline-offset-2 hover:text-blue-800"
        >
          Get directions ↗
        </a>

        {/* Caption only on the first leg — teaches the model once */}
        {isFirstLeg && (
          <p className="mt-1 text-xs text-zinc-400">
            Tap when you&apos;re heading out — live times open in Google Maps.
          </p>
        )}
      </div>
    </div>
  );
}
