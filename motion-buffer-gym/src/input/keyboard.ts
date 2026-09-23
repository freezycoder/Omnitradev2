import { arrowsToNumpad } from "../engine/directions";
import { assertNever, type Button, type Numpad } from "../engine/types";

const NUMPAD_CODES: Record<string, Numpad> = {
  Numpad1: 1,
  Numpad2: 2,
  Numpad3: 3,
  Numpad4: 4,
  Numpad5: 5,
  Numpad6: 6,
  Numpad7: 7,
  Numpad8: 8,
  Numpad9: 9,
  Digit1: 1,
  Digit2: 2,
  Digit3: 3,
  Digit4: 4,
  Digit5: 5,
  Digit6: 6,
  Digit7: 7,
  Digit8: 8,
  Digit9: 9,
};

type ArrowCode = "ArrowUp" | "ArrowDown" | "ArrowLeft" | "ArrowRight";

const arrows = {
  up: false,
  down: false,
  left: false,
  right: false,
};

const heldNumpad = new Set<Numpad>();
const numpadOrder: Numpad[] = [];
const queuedButtons: Button[] = [];
const directionListeners = new Set<(direction: Numpad) => void>();
let activity = false;
let facingToggle = false;
let lastEmitted: Numpad | null = null;

function markActivity(): void {
  activity = true;
}

function emitDirection(): void {
  const direction = keyboardDirection();
  if (direction === lastEmitted) return;
  lastEmitted = direction;
  for (const listener of directionListeners) listener(direction);
}

function isArrowCode(code: string): code is ArrowCode {
  switch (code) {
    case "ArrowUp":
    case "ArrowDown":
    case "ArrowLeft":
    case "ArrowRight":
      return true;
    default:
      return false;
  }
}

function setArrow(code: ArrowCode, down: boolean): void {
  switch (code) {
    case "ArrowUp":
      arrows.up = down;
      return;
    case "ArrowDown":
      arrows.down = down;
      return;
    case "ArrowLeft":
      arrows.left = down;
      return;
    case "ArrowRight":
      arrows.right = down;
      return;
    default:
      assertNever(code);
  }
}

function rememberNumpad(direction: Numpad, down: boolean): void {
  if (direction === 5) {
    if (down) {
      heldNumpad.clear();
      numpadOrder.length = 0;
    }
    return;
  }
  if (down) {
    if (!heldNumpad.has(direction)) numpadOrder.push(direction);
    heldNumpad.add(direction);
    return;
  }
  heldNumpad.delete(direction);
}

function onKey(event: KeyboardEvent, down: boolean): void {
  if (event.repeat) return;

  const numpad = NUMPAD_CODES[event.code];
  if (numpad !== undefined) {
    rememberNumpad(numpad, down);
    markActivity();
    emitDirection();
    event.preventDefault();
    return;
  }

  if (isArrowCode(event.code)) {
    setArrow(event.code, down);
    markActivity();
    emitDirection();
    event.preventDefault();
    return;
  }

  if (!down) return;

  if (event.code === "KeyJ" || event.code === "KeyK") {
    queuedButtons.push(event.code === "KeyJ" ? "punch" : "kick");
    markActivity();
    event.preventDefault();
    return;
  }

  if (event.code === "KeyF") {
    facingToggle = true;
    markActivity();
    event.preventDefault();
  }
}

export function keyboardDirection(): Numpad {
  for (let index = numpadOrder.length - 1; index >= 0; index -= 1) {
    const direction = numpadOrder[index];
    if (direction !== undefined && heldNumpad.has(direction)) return direction;
  }
  return arrowsToNumpad(arrows);
}

export function consumeButtons(): Button[] {
  const next = queuedButtons.slice();
  queuedButtons.length = 0;
  return next;
}

export function consumeKeyboardActivity(): boolean {
  const was = activity;
  activity = false;
  return was;
}

export function consumeFacingToggle(): boolean {
  const was = facingToggle;
  facingToggle = false;
  return was;
}

export function subscribeKeyboardDirection(listener: (direction: Numpad) => void): () => void {
  directionListeners.add(listener);
  return () => directionListeners.delete(listener);
}

export function attachKeyboard(target: Window): () => void {
  const down = (event: KeyboardEvent) => onKey(event, true);
  const up = (event: KeyboardEvent) => onKey(event, false);
  target.addEventListener("keydown", down, true);
  target.addEventListener("keyup", up, true);
  return () => {
    target.removeEventListener("keydown", down, true);
    target.removeEventListener("keyup", up, true);
  };
}
