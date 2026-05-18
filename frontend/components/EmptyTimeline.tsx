interface Props {
  stopCount: number;
}

function ghostLabel(i: number, total: number): string {
  if (i === 0) return "Start";
  if (i === total - 1) return "End";
  return `Stop ${i + 1}`;
}

export default function EmptyTimeline({ stopCount }: Props) {
  const count = Math.max(2, stopCount);

  return (
    <div className="opacity-40">
      {/*
        Mirrors the real Timeline layout so ghost markers land on the dotted
        line at left-[5rem]: w-6 (gripper) + w-12 (time) + ½×w-4 (dot) = 5rem
      */}
      <ol className="relative overflow-hidden before:absolute before:bottom-4 before:left-[5rem] before:top-4 before:border-l-2 before:border-dashed before:border-border-subtle">
        {Array.from({ length: count }).map((_, i) => (
          <li key={i} className="flex items-start py-3">
            <div className="w-6 flex-shrink-0" />
            <div className="w-12 flex-shrink-0" />
            <div className="flex w-4 flex-shrink-0 justify-center pt-1.5">
              <div className="relative z-10 h-3 w-3 rounded-full bg-accent" />
            </div>
            <div className="ml-2 min-w-0 flex-1">
              <span className="text-body-strong opacity-50">
                {ghostLabel(i, count)}
              </span>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
