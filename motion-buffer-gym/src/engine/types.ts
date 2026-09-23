export type Numpad = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9;

export type Facing = "left" | "right";

export type Button = "punch" | "kick";

export type MotionId = "qcf" | "dp" | "hcf";

export type InputSource = "keyboard" | "gamepad";

export interface DirectionEvent {
  readonly direction: Numpad;
  readonly time: number;
}

export function assertNever(value: never): never {
  throw new Error(`Unexpected variant: ${String(value)}`);
}
