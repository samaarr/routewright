"use client";

import {
  DndContext,
  DragEndEvent,
  DragOverlay,
  DragStartEvent,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useState } from "react";
import type { Plan, StopItem as StopItemType } from "@/lib/types";
import StopCard from "./StopCard";
import LegCard from "./LegCard";

interface Props {
  plan: Plan;
  onReorder: (newQueries: string[]) => void;
  onLegRefresh: (legTimelineIndex: number) => void;
  isReordering: boolean;
  refreshingLegIdx: number | null;
}

// --- SortableStopRow ---
// Thin dnd-kit wrapper around StopCard. Handles transform/transition CSS and
// passes only the drag handle listeners to the gripper button so that clicks
// on names, links, and other interactive children still work.

interface SortableStopRowProps {
  stop: StopItemType;
  isFirst: boolean;
  isLast: boolean;
}

function SortableStopRow({ stop, isFirst, isLast }: SortableStopRowProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: stop.query });

  return (
    <li
      ref={setNodeRef}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.35 : 1,
      }}
      {...attributes}
    >
      <StopCard
        stop={stop}
        isFirst={isFirst}
        isLast={isLast}
        dragHandleProps={listeners as Parameters<typeof StopCard>[0]["dragHandleProps"]}
      />
    </li>
  );
}

// --- Timeline ---

export default function Timeline({
  plan,
  onReorder,
  onLegRefresh,
  isReordering,
  refreshingLegIdx,
}: Props) {
  const [activeId, setActiveId] = useState<string | null>(null);

  const totalStops = plan.timeline.filter((i) => i.item_type === "stop").length;

  const degradedLegs = new Set(
    plan.warnings
      .filter((w) => w.affects_stop_index !== null)
      .map((w) => w.affects_stop_index as number)
  );

  const stopQueries = plan.timeline
    .filter((i): i is StopItemType => i.item_type === "stop")
    .map((s) => s.query);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  );

  function handleDragStart(event: DragStartEvent) {
    setActiveId(event.active.id as string);
  }

  function handleDragCancel() {
    setActiveId(null);
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    setActiveId(null);
    if (!over || active.id === over.id) return;

    const oldIndex = stopQueries.indexOf(active.id as string);
    const newIndex = stopQueries.indexOf(over.id as string);
    if (oldIndex === -1 || newIndex === -1) return;

    onReorder(arrayMove(stopQueries, oldIndex, newIndex));
  }

  const activeStop = activeId
    ? plan.timeline.find(
        (i): i is StopItemType =>
          i.item_type === "stop" && i.query === activeId
      ) ?? null
    : null;

  let stopIndex = 0;
  let legIndex = 0;

  return (
    <DndContext
      sensors={sensors}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onDragCancel={handleDragCancel}
    >
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

        <SortableContext items={stopQueries} strategy={verticalListSortingStrategy}>
          {/*
            Vertical dotted line sits at left-[5rem]:
            w-6 (gripper, 1.5rem) + w-12 (time, 3rem) + ½×w-4 (dot centre, 0.5rem) = 5rem
          */}
          <div className="relative">
            {isReordering && (
              <div className="absolute inset-0 z-20 flex items-center justify-center rounded bg-white/80">
                <p className="text-sm text-zinc-500">Updating route…</p>
              </div>
            )}

            <ol className="relative overflow-hidden before:absolute before:bottom-4 before:left-[5rem] before:top-4 before:border-l before:border-dashed before:border-zinc-200">
              {plan.timeline.map((item, idx) => {
                if (item.item_type === "stop") {
                  const si = stopIndex;
                  stopIndex += 1;
                  return (
                    <SortableStopRow
                      key={item.query}
                      stop={item}
                      isFirst={si === 0}
                      isLast={si === totalStops - 1}
                    />
                  );
                }

                const li = legIndex;
                const lti = idx;
                legIndex += 1;
                return (
                  <li key={idx}>
                    <LegCard
                      leg={item}
                      isFirstLeg={li === 0}
                      isDegraded={degradedLegs.has(li)}
                      legTimelineIndex={lti}
                      onRefresh={onLegRefresh}
                      isRefreshing={refreshingLegIdx === lti}
                    />
                  </li>
                );
              })}
            </ol>
          </div>
        </SortableContext>
      </div>

      {/* Floating ghost of the stop being dragged */}
      <DragOverlay dropAnimation={null}>
        {activeStop ? (
          <div className="rounded border border-blue-200 bg-white shadow-lg">
            <StopCard
              stop={activeStop}
              isFirst={false}
              isLast={false}
              dragHandleProps={undefined}
            />
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}
