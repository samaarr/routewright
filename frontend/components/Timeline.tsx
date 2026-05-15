import type { Plan } from "@/lib/types";
import StopCard from "./StopCard";
import LegCard from "./LegCard";

interface Props {
  plan: Plan;
}

export default function Timeline({ plan }: Props) {
  // Build a Set of leg indices that have a degraded warning.
  // affects_stop_index on a warning equals the leg index (leg i runs from
  // stop[i] to stop[i+1], so its index matches the originating stop index).
  const degradedLegs = new Set(
    plan.warnings
      .filter((w) => w.affects_stop_index !== null)
      .map((w) => w.affects_stop_index as number)
  );

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

      <ol>
        {plan.timeline.map((item, idx) => {
          if (item.item_type === "stop") {
            return (
              <li key={idx}>
                <StopCard stop={item} />
              </li>
            );
          }

          // LegItem — capture and increment before JSX so closures are consistent
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
