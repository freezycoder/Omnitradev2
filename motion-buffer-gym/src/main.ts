import { characterById, type CharacterId } from "./engine/characters";
import { evaluateMotions } from "./engine/matcher";
import { createRing, pruneRing, pushChange, type RingState } from "./engine/ring-buffer";
import { assertNever, type Button, type Facing, type InputSource, type Numpad } from "./engine/types";
import { sampleGamepads, type GamepadSample } from "./input/gamepad";
import {
  attachKeyboard,
  consumeButtons,
  consumeFacingToggle,
  consumeKeyboardActivity,
  keyboardDirection,
  subscribeKeyboardDirection,
} from "./input/keyboard";
import { trimTimeline, type TimelineItem } from "./model";
import { mountGym, type ViewState } from "./view";

interface Session {
  characterId: CharacterId;
  bufferFrames: number;
  windowScale: number;
  facing: Facing;
  ring: RingState;
  timeline: TimelineItem[];
  nextId: number;
  held: Numpad;
  source: InputSource;
  padConnected: boolean;
  origin: number;
}

const kite = characterById("kite");
const session: Session = {
  characterId: kite.id,
  bufferFrames: kite.bufferFrames,
  windowScale: 1,
  facing: "right",
  ring: createRing(64),
  timeline: [],
  nextId: 1,
  held: 5,
  source: "keyboard",
  padConnected: false,
  origin: performance.now(),
};

let pointerHeld: Numpad | null = null;
let lastPadDirection: Numpad = 5;
let latestPad: GamepadSample = {
  connected: false,
  direction: 5,
  pressed: [],
  id: null,
  mapping: null,
};

const view = mountGym({
  onCharacter: selectCharacter,
  onBufferFrames: setBufferFrames,
  onWindowScale: setWindowScale,
  onFacing: () => {
    session.facing = toggleFacing(session.facing);
    view.paint(viewState());
  },
  onPunch: () => commitButton("punch", performance.now()),
  onKick: () => commitButton("kick", performance.now()),
  onHoldDirection: (direction) => {
    pointerHeld = direction;
    session.source = "keyboard";
    applyDirection(direction, performance.now());
    view.paint(viewState());
  },
  onReleaseDirection: () => {
    if (pointerHeld === null) return;
    pointerHeld = null;
    applyDirection(resolveDirection(latestPad), performance.now());
    view.paint(viewState());
  },
});

attachKeyboard(window);
subscribeKeyboardDirection((direction) => {
  const sourceChanged = session.source !== "keyboard";
  session.source = "keyboard";
  if (pointerHeld !== null) {
    if (sourceChanged) view.paint(viewState());
    return;
  }
  if (applyDirection(direction, performance.now()) || sourceChanged) view.paint(viewState());
});
view.paint(viewState());
requestAnimationFrame(frame);

function frame(now: number): void {
  const keyboardButtons = consumeButtons();
  const keyboardActive = consumeKeyboardActivity();
  const facingPressed = consumeFacingToggle();
  latestPad = sampleGamepads();
  let dirty = false;

  if (facingPressed) {
    session.facing = toggleFacing(session.facing);
    dirty = true;
  }

  if (latestPad.connected && (latestPad.direction !== lastPadDirection || latestPad.pressed.length > 0)) {
    const padChanged = latestPad.direction !== lastPadDirection;
    lastPadDirection = latestPad.direction;
    const keyboardHeld = keyboardDirection() !== 5;
    if (latestPad.pressed.length > 0 || (padChanged && (!keyboardHeld || latestPad.direction !== 5))) {
      session.source = "gamepad";
    }
  }
  if (!latestPad.connected) {
    lastPadDirection = 5;
    if (session.source === "gamepad") session.source = "keyboard";
  }
  if (keyboardActive || keyboardButtons.length > 0 || pointerHeld !== null) session.source = "keyboard";

  if (latestPad.connected !== session.padConnected) {
    session.padConnected = latestPad.connected;
    dirty = true;
  }

  if (applyDirection(resolveDirection(latestPad), now)) dirty = true;

  for (const button of [...keyboardButtons, ...latestPad.pressed]) {
    commitButton(button, now);
    dirty = true;
  }

  if (dirty) view.paint(viewState());
  requestAnimationFrame(frame);
}

function resolveDirection(pad: GamepadSample): Numpad {
  if (pointerHeld !== null) return pointerHeld;
  if (session.source === "gamepad" && pad.connected && pad.direction !== 5) return pad.direction;
  return keyboardDirection();
}

function applyDirection(direction: Numpad, now: number): boolean {
  const pruned = pruneRing(session.ring, now, session.bufferFrames);
  const pushed = pushChange(pruned, direction, now);
  const changed = session.held !== direction || pruned !== session.ring || pushed.recorded;
  session.held = direction;
  session.ring = pushed.state;
  if (pushed.recorded) {
    session.timeline = trimTimeline(
      session.timeline.concat({
        id: session.nextId,
        time: now,
        kind: "direction",
        direction,
      }),
    );
    session.nextId += 1;
  }
  return changed;
}

function commitButton(button: Button, now: number): void {
  applyDirection(resolveDirection(latestPad), now);
  session.ring = pruneRing(session.ring, now, session.bufferFrames);
  const character = characterById(session.characterId);
  const evaluation = evaluateMotions({
    entries: session.ring.entries,
    now,
    bufferFrames: session.bufferFrames,
    facing: session.facing,
    windows: character.windows,
    windowScale: session.windowScale,
  });
  session.timeline = trimTimeline(
    session.timeline.concat({
      id: session.nextId,
      time: now,
      kind: "judgment",
      button,
      motion: evaluation.motion,
      considered: evaluation.considered.map((entry) => entry.direction),
      facing: session.facing,
    }),
  );
  session.nextId += 1;
  view.paint(viewState());
}

function selectCharacter(id: CharacterId): void {
  const character = characterById(id);
  session.characterId = character.id;
  session.bufferFrames = character.bufferFrames;
  session.windowScale = 1;
  session.ring = pruneRing(session.ring, performance.now(), session.bufferFrames);
  view.paint(viewState());
}

function setBufferFrames(frames: number): void {
  session.bufferFrames = clamp(frames, 4, 40);
  session.ring = pruneRing(session.ring, performance.now(), session.bufferFrames);
  view.paint(viewState());
}

function setWindowScale(scale: number): void {
  session.windowScale = clamp(scale, 0.25, 2);
  view.paint(viewState());
}

function toggleFacing(facing: Facing): Facing {
  switch (facing) {
    case "right":
      return "left";
    case "left":
      return "right";
    default:
      return assertNever(facing);
  }
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function viewState(): ViewState {
  return {
    characterId: session.characterId,
    bufferFrames: session.bufferFrames,
    windowScale: session.windowScale,
    facing: session.facing,
    held: session.held,
    entries: session.ring.entries,
    timeline: session.timeline,
    source: session.source,
    padConnected: session.padConnected,
    origin: session.origin,
  };
}
