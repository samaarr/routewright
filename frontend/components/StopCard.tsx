import type { StopItem } from "@/lib/types";
import { fmtTime } from "@/lib/utils";

interface Props {
  stop: StopItem;
}

export default function StopCard({ stop }: Props) {
  return (
    <div className="flex items-start gap-3 py-4">
      {/* Timeline dot */}
      <div className="mt-1.5 h-3 w-3 flex-shrink-0 rounded-full border-2 border-blue-500 bg-white" />

      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium uppercase tracking-wide text-zinc-400">
          {stop.name}
        </p>
        {/* Times are visually dominant */}
        <p className="mt-0.5 text-2xl font-semibold tabular-nums text-zinc-900">
          {fmtTime(stop.arrive_at)}
          <span className="mx-2 text-zinc-300">→</span>
          {fmtTime(stop.depart_at)}
        </p>
        <p className="mt-0.5 text-sm text-zinc-500">
          {stop.stay_minutes} min
          {stop.stay_source === "user" && (
            <span className="ml-1 text-zinc-400">(set by you)</span>
          )}
        </p>
      </div>
    </div>
  );
}
