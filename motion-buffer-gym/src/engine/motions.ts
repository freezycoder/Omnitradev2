import { assertNever, type MotionId, type Numpad } from "./types";

export const MOTION_IDS = ["qcf", "dp", "hcf"] as const;

export const MOTION_STEPS: Record<MotionId, readonly Numpad[]> = {
  qcf: [2, 3, 6],
  dp: [6, 2, 3],
  hcf: [4, 1, 2, 3, 6],
};

export interface MotionWindows {
  readonly qcf: readonly [number, number];
  readonly dp: readonly [number, number];
  readonly hcf: readonly [number, number, number, number];
}

const MOTION_PRIORITY: Record<MotionId, number> = {
  hcf: 0,
  dp: 1,
  qcf: 2,
};

export function motionName(id: MotionId): string {
  switch (id) {
    case "qcf":
      return "QCF";
    case "dp":
      return "DP";
    case "hcf":
      return "HCF";
    default:
      return assertNever(id);
  }
}

export function buttonName(button: "punch" | "kick"): string {
  switch (button) {
    case "punch":
      return "Punch";
    case "kick":
      return "Kick";
    default:
      return assertNever(button);
  }
}

export function windowsFor(windows: MotionWindows, id: MotionId): readonly number[] {
  switch (id) {
    case "qcf":
      return windows.qcf;
    case "dp":
      return windows.dp;
    case "hcf":
      return windows.hcf;
    default:
      return assertNever(id);
  }
}

export function motionPriority(id: MotionId): number {
  switch (id) {
    case "hcf":
      return MOTION_PRIORITY.hcf;
    case "dp":
      return MOTION_PRIORITY.dp;
    case "qcf":
      return MOTION_PRIORITY.qcf;
    default:
      return assertNever(id);
  }
}
