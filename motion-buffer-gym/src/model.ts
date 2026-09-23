import type { Button, Facing, MotionId, Numpad } from "./engine/types";

export type TimelineItem =
  | {
      readonly id: number;
      readonly time: number;
      readonly kind: "direction";
      readonly direction: Numpad;
    }
  | {
      readonly id: number;
      readonly time: number;
      readonly kind: "judgment";
      readonly button: Button;
      readonly motion: MotionId | null;
      readonly considered: readonly Numpad[];
      readonly facing: Facing;
    };

export const TIMELINE_LIMIT = 80;

export function trimTimeline(items: readonly TimelineItem[]): TimelineItem[] {
  if (items.length <= TIMELINE_LIMIT) return items.slice();
  return items.slice(items.length - TIMELINE_LIMIT);
}
