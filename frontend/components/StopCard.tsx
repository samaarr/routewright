import type { StopItem } from "@/lib/types";
import { fmtTime } from "@/lib/utils";

interface Props {
  stop: StopItem;
  isFirst: boolean;
  isLast: boolean;
}

export default function StopCard({ stop, isFirst, isLast }: Props) {
  const showStayInfo = !isFirst && !isLast && stop.stay_minutes > 0;

  return (
    <div className="flex items-start py-2.5">
      {/* Arrival time — right-aligned in fixed column */}
      <span className="w-12 flex-shrink-0 pt-0.5 text-right text-sm font-semibold tabular-nums text-zinc-900">
        {fmtTime(stop.arrive_at)}
      </span>

      {/* Dot — centered over the dotted vertical line (line is at left-[3.5rem]) */}
      <div className="flex w-4 flex-shrink-0 justify-center pt-1">
        <div className="relative z-10 h-2.5 w-2.5 rounded-full border-2 border-blue-500 bg-white" />
      </div>

      {/* Content — name + optional stay/leave info */}
      <div className="ml-2 min-w-0 flex-1">
        <div className="flex flex-col sm:flex-row sm:items-baseline sm:gap-2">
          <span className="font-medium text-zinc-900">{stop.name}</span>

          {showStayInfo && (
            <span className="text-sm text-zinc-400">
              · stay {stop.stay_minutes} min · leave {fmtTime(stop.depart_at)}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
