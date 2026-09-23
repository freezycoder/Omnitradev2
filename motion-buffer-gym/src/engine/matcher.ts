import { toForwardRelative } from "./facing";
import {
  MOTION_IDS,
  MOTION_STEPS,
  motionPriority,
  windowsFor,
  type MotionWindows,
} from "./motions";
import { isWithinBuffer, isWithinGap } from "./time";
import type { DirectionEvent, Facing, MotionId, Numpad } from "./types";

export interface EvaluationInput {
  readonly entries: readonly DirectionEvent[];
  readonly now: number;
  readonly bufferFrames: number;
  readonly facing: Facing;
  readonly windows: MotionWindows;
  readonly windowScale: number;
}

export interface Evaluation {
  readonly motion: MotionId | null;
  readonly matched: readonly MotionId[];
  readonly considered: readonly DirectionEvent[];
}

function attemptCompletes(
  entries: readonly DirectionEvent[],
  steps: readonly Numpad[],
  gaps: readonly number[],
  facing: Facing,
  startIndex: number,
): boolean {
  const first = entries[startIndex];
  if (!first) return false;
  if (toForwardRelative(first.direction, facing) !== steps[0]) return false;

  let stepIndex = 0;
  let previousTime = first.time;

  for (let index = startIndex + 1; index < entries.length; index += 1) {
    const entry = entries[index];
    if (!entry) continue;
    const forward = toForwardRelative(entry.direction, facing);
    if (forward === 5) continue;

    const expected = steps[stepIndex + 1];
    const maxFrames = gaps[stepIndex];
    if (expected === undefined || maxFrames === undefined || forward !== expected) return false;
    if (!isWithinGap(previousTime, entry.time, maxFrames)) return false;

    stepIndex += 1;
    previousTime = entry.time;
    if (stepIndex === steps.length - 1) return true;
  }

  return false;
}

function chooseLongest(matched: readonly MotionId[]): MotionId | null {
  let best: MotionId | null = null;
  for (const id of matched) {
    if (best === null) {
      best = id;
      continue;
    }
    const lengthGap = MOTION_STEPS[id].length - MOTION_STEPS[best].length;
    if (lengthGap > 0 || (lengthGap === 0 && motionPriority(id) < motionPriority(best))) {
      best = id;
    }
  }
  return best;
}

export function evaluateMotions(input: EvaluationInput): Evaluation {
  const considered = input.entries
    .filter((entry) => isWithinBuffer(input.now, entry.time, input.bufferFrames))
    .slice()
    .sort((left, right) => left.time - right.time);

  const matched: MotionId[] = [];
  for (const id of MOTION_IDS) {
    const steps = MOTION_STEPS[id];
    const gaps = windowsFor(input.windows, id).map((gap) => gap * input.windowScale);
    if (gaps.length !== steps.length - 1) {
      throw new Error(`Motion ${id} window count does not match its steps`);
    }
    const completed = considered.some((_, index) =>
      attemptCompletes(considered, steps, gaps, input.facing, index),
    );
    if (completed) matched.push(id);
  }

  return { motion: chooseLongest(matched), matched, considered };
}
