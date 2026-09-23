import type { Numpad } from "./types";

const NUMPAD_FROM_VECTOR: Record<string, Numpad> = {
  "-1,1": 7,
  "0,1": 8,
  "1,1": 9,
  "-1,0": 4,
  "0,0": 5,
  "1,0": 6,
  "-1,-1": 1,
  "0,-1": 2,
  "1,-1": 3,
};

function axisSign(value: number, deadzone: number): -1 | 0 | 1 {
  if (!Number.isFinite(value) || Math.abs(value) < deadzone) return 0;
  return value > 0 ? 1 : -1;
}

export function vectorToNumpad(x: number, y: number, deadzone: number): Numpad {
  const key = `${axisSign(x, deadzone)},${axisSign(y, deadzone)}`;
  return NUMPAD_FROM_VECTOR[key] ?? 5;
}

export interface ArrowHold {
  readonly up: boolean;
  readonly down: boolean;
  readonly left: boolean;
  readonly right: boolean;
}

export function arrowsToNumpad(arrows: ArrowHold): Numpad {
  const x = arrows.left === arrows.right ? 0 : arrows.left ? -1 : 1;
  const y = arrows.up === arrows.down ? 0 : arrows.up ? 1 : -1;
  return vectorToNumpad(x, y, 0.5);
}
