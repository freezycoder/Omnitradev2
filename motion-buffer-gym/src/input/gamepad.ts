import { vectorToNumpad } from "../engine/directions";
import type { Button, Numpad } from "../engine/types";

export const STICK_DEADZONE = 0.45;

export interface GamepadSample {
  readonly connected: boolean;
  readonly direction: Numpad;
  readonly pressed: readonly Button[];
  readonly id: string | null;
  readonly mapping: string | null;
}

const FACE_BUTTONS: ReadonlyArray<readonly [number, Button]> = [
  [0, "punch"],
  [2, "punch"],
  [1, "kick"],
  [3, "kick"],
];

const buttonState = new Map<number, boolean[]>();

function buttonDown(button: GamepadButton | undefined): boolean {
  if (!button) return false;
  return button.pressed || button.value >= 0.5;
}

function dpadDirection(pad: Gamepad): Numpad {
  const up = buttonDown(pad.buttons[12]);
  const down = buttonDown(pad.buttons[13]);
  const left = buttonDown(pad.buttons[14]);
  const right = buttonDown(pad.buttons[15]);
  const x = left === right ? 0 : left ? -1 : 1;
  const y = up === down ? 0 : up ? 1 : -1;
  if (x === 0 && y === 0) return 5;
  return vectorToNumpad(x, y, 0.5);
}

function readPads(): readonly (Gamepad | null)[] {
  if (typeof navigator === "undefined" || typeof navigator.getGamepads !== "function") return [];
  try {
    return navigator.getGamepads();
  } catch {
    return [];
  }
}

export function sampleGamepads(): GamepadSample {
  const pads = readPads();
  let pad: Gamepad | null = null;
  for (const candidate of pads) {
    if (candidate?.connected) {
      pad = candidate;
      break;
    }
  }

  if (!pad) {
    buttonState.clear();
    return { connected: false, direction: 5, pressed: [], id: null, mapping: null };
  }

  const stick = vectorToNumpad(pad.axes[0] ?? 0, -(pad.axes[1] ?? 0), STICK_DEADZONE);
  const hat = dpadDirection(pad);
  const direction = hat === 5 ? stick : hat;
  const previous = buttonState.get(pad.index) ?? [];
  const next = pad.buttons.map((button) => buttonDown(button));
  const pressed = new Set<Button>();
  for (const [index, button] of FACE_BUTTONS) {
    if (next[index] && !previous[index]) pressed.add(button);
  }
  buttonState.set(pad.index, next);

  return {
    connected: true,
    direction,
    pressed: [...pressed],
    id: pad.id,
    mapping: pad.mapping || "unknown",
  };
}
