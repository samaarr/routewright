import type { Plan } from "@/lib/types";
import StopCard from "./StopCard";
import LegCard from "./LegCard";

interface Props {
  plan: Plan;
}

export default function Timeline({ plan }: Props) {
  const totalStops = plan.timeline.filter((i) => i.item_type === "stop").length;

  // Leg indices that have a degraded-schedule warning.
  const degradedLegs = new Set(
    plan.warnings
      .filter((w) => w.affects_stop_index !== null)
      .map((w) => w.affects_stop_index as number)
  );

  let stopIndex = 0;
  let legIndex = 0;

  return (
    <div>
      <div className="mb-5 flex items-center justify-between">
        <p className="text-sm font-medium text-zinc-500">{plan.city}</p>
        <a
          href={plan.overview_map_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm text-blue-600 underline underline-offset-2 hover:text-blue-800"
        >
          Overview map ↗
        </a>
      </div>

      {/*
        Dotted vertical line: single pseudo on <ol> at left-[3.5rem].
        3rem (w-12 time col) + 0.5rem (centre of w-4 dot col) = 3.5rem.
        overflow-hidden clips the line flush with the list bounds.
      */}
      <ol className="relative overflow-hidden before:absolute before:bottom-4 before:left-[3.5rem] before:top-4 before:border-l before:border-dashed before:border-zinc-200">
        {plan.timeline.map((item, idx) => {
          if (item.item_type === "stop") {
            const si = stopIndex;
            stopIndex += 1;
            return (
              <li key={idx}>
                <StopCard
                  stop={item}
                  isFirst={si === 0}
                  isLast={si === totalStops - 1}
                />
              </li>
            );
          }

          const li = legIndex;
          legIndex += 1;
          return (
            <li key={idx}>
              <LegCard
                leg={item}
                isFirstLeg={li === 0}
                isDegraded={degradedLegs.has(li)}
              />
            </li>
          );
        })}
      </ol>
    </div>
  );
}
