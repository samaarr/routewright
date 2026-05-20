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
  // UUIDs parallel to plan.timeline stop items (stopIds[i] ↔ i-th stop in
  // timeline). Never derived from query strings — fixes the duplicate-drag
  // bug where two stops with the same query shared a dnd-kit id.
  stopIds: string[];
  onReorder: (newIds: string[]) => void;
  onLegRefresh: (legTimelineIndex: number) => void;
  onStayEdit: (stopId: string, minutes: number) => void;
  isReordering: boolean;
  refreshingLegIdx: number | null;
}

// --- SortableStopRow ---

interface SortableStopRowProps {
  id: string;
  stop: StopItemType;
  isFirst: boolean;
  isLast: boolean;
  animationDelay: string;
  onStayEdit: (stopId: string, minutes: number) => void;
}

function SortableStopRow({ id, stop, isFirst, isLast, animationDelay, onStayEdit }: SortableStopRowProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id });

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
      {/* Inner wrapper owns the entrance animation so dnd-kit's inline
          opacity:1 on the <li> doesn't override the keyframe's opacity:0
          starting state. */}
      <div className="animate-fade-up" style={{ animationDelay }}>
        <StopCard
          stop={stop}
          isFirst={isFirst}
          isLast={isLast}
          dragHandleProps={listeners as Parameters<typeof StopCard>[0]["dragHandleProps"]}
          onStayEdit={(m) => onStayEdit(id, m)}
        />
      </div>
    </li>
  );
}

// --- Timeline ---

export default function Timeline({
  plan,
  stopIds,
  onReorder,
  onLegRefresh,
  onStayEdit,
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

  // Build a UUID → StopItem map so DragOverlay can find the active stop
  // without relying on query-string lookups (which break on duplicates).
  const stops = plan.timeline.filter(
    (i): i is StopItemType => i.item_type === "stop"
  );
  const idToStop = new Map(stopIds.map((id, i) => [id, stops[i]]));

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

    const oldIndex = stopIds.indexOf(active.id as string);
    const newIndex = stopIds.indexOf(over.id as string);
    if (oldIndex === -1 || newIndex === -1) return;

    // arrayMove on UUIDs — no ambiguity even with duplicate query strings.
    onReorder(arrayMove(stopIds, oldIndex, newIndex));
  }

  const activeStop = activeId ? (idToStop.get(activeId) ?? null) : null;

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
        <SortableContext items={stopIds} strategy={verticalListSortingStrategy}>
          {/*
            Vertical dotted line sits at left-[5rem]:
            w-6 (gripper, 1.5rem) + w-12 (time, 3rem) + ½×w-4 (dot centre, 0.5rem) = 5rem
          */}
          <div className="relative">
            {isReordering && (
              <div className="absolute inset-0 z-20 flex items-center justify-center rounded bg-pane-bg/80">
                <p className="text-body text-text-tertiary">Updating route…</p>
              </div>
            )}

            <ol className="relative overflow-hidden before:absolute before:bottom-4 before:left-[5rem] before:top-4 before:border-l-2 before:border-dashed before:border-border-subtle">
              {plan.timeline.map((item, idx) => {
                if (item.item_type === "stop") {
                  const si = stopIndex;
                  const id = stopIds[si] ?? `stop-${si}`;
                  stopIndex += 1;
                  return (
                    <SortableStopRow
                      key={id}
                      id={id}
                      stop={item}
                      isFirst={si === 0}
                      isLast={si === totalStops - 1}
                      animationDelay={`${Math.min(idx * 40, 400)}ms`}
                      onStayEdit={onStayEdit}
                    />
                  );
                }

                const li = legIndex;
                const lti = idx;
                legIndex += 1;
                return (
                  <li
                    key={`leg-${idx}`}
                    className="animate-fade-up"
                    style={{ animationDelay: `${Math.min(idx * 40, 400)}ms` }}
                  >
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

      <DragOverlay dropAnimation={null}>
        {activeStop ? (
          <div className="rounded border border-accent-faint bg-bg-elevated shadow-floating">
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
